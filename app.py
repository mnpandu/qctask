"""Run with: python app.py. PostgreSQL settings can be overridden with PG* variables."""

from html import escape
from functools import partial
from pathlib import Path

import logging
import os

import gradio as gr
import psycopg
from psycopg.types.json import Jsonb
import claim_workflow as qc

TASK_TYPES = ["QC Nurse Full Review", "QC Nurse Partial Review"]
TASK_COLUMNS = ["Task ID", "Task Name", "Status", "Assigned To", "Created On", "Completed On", "Claims", "Comments"]
CLAIM_COLUMNS = ["Claim ID", "Provider ID", "Date of Service", "Procedure Code", "Billed Amount", "Allowed Amount", "Paid Amount", "Claim Status"]


def connect_db():
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        connect_timeout=5,
    )


# A numeric case ID is required by the reference schema; 1 is the demo case.
CASE_ID = int(os.getenv("QC_CASE_ID", "1"))
ACTOR_ID = os.getenv("QC_USER_ID", "demo")
ACTOR_NAME = os.getenv("QC_USER_NAME", "Demo User")
USERS = {
    "pandu": {"id": "pandu", "name": "Pandu", "role": "QC Nurse"},
    "regine": {"id": "regine", "name": "Regine", "role": "Nurse"},
}


def actor_id(user=None):
    return user["id"] if user else ACTOR_ID


def actor_name(user=None):
    return user["name"] if user else ACTOR_NAME


def require_user(user):
    if not user or USERS.get(user.get("id")) != user:
        raise gr.Error("Sign in as Pandu or Regine to continue.")
    return user


def login_user(username):
    user = USERS.get(username)
    if user is None:
        raise gr.Error("Choose a valid user name.")
    return (
        user,
        gr.update(visible=False),
        gr.update(value=f"Signed in as {user['name']}", visible=True),
        refresh_tasks(user),
        notification_badge(user),
    )


def logout_user():
    return (
        None,
        gr.update(visible=True),
        gr.update(value="", visible=True),
        [],
        "Alerts (0)",
    )


def initialize_db():
    with connect_db() as conn:
        is_new = conn.execute("SELECT to_regclass('pic_master.task') IS NULL").fetchone()[0]
        conn.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8-sig"))
        # Carry forward tasks saved by the earlier version on the first upgrade.
        if is_new and conn.execute("SELECT to_regclass('public.task') IS NOT NULL").fetchone()[0]:
            conn.execute("""
                INSERT INTO pic_master.task
                    (task_id, task_name, task_status, assigned_to_name, created_dts,
                     task_cmpled_dts, case_id, task_comment, created_by, created_by_name)
                SELECT t.id, t.task_name, t.status, t.assigned_to, t.created_on,
                       t.completed_on, %s, d.details->>'comments', %s, %s
                FROM public.task t LEFT JOIN public.task_details d ON d.task_id = t.id
            """, (CASE_ID, ACTOR_ID, ACTOR_NAME))
            conn.execute("""
                INSERT INTO pic_master.task_details (task_id, task_canonical, created_by, updated_dts)
                SELECT t.id,
                       jsonb_build_object('claimsForReviews', COALESCE(
                           (SELECT jsonb_agg(jsonb_build_object('claimNumber', c->>'Claim ID'))
                            FROM jsonb_array_elements(COALESCE(d.details->'claims', '[]'::jsonb)) AS c),
                           '[]'::jsonb)),
                       %s, d.updated_on
                FROM public.task t LEFT JOIN public.task_details d ON d.task_id = t.id
            """, (ACTOR_ID,))
            conn.execute("""
                SELECT setval(pg_get_serial_sequence('pic_master.task', 'task_id'),
                              COALESCE(max(task_id), 1), count(*) > 0)
                FROM pic_master.task
            """)



def list_tasks(conn):
    rows = conn.execute("""
        SELECT t.task_id, t.task_name, t.task_status,
               COALESCE(t.assigned_to_name, t.assigned_to, 'Unassigned'),
               to_char(t.created_dts, 'YYYY-MM-DD HH24:MI:SS'),
               COALESCE(to_char(t.task_cmpled_dts, 'YYYY-MM-DD HH24:MI:SS'), ''),
               COALESCE(jsonb_array_length(d.task_canonical->'claimsForReviews'), 0),
               COALESCE(t.task_comment, '')
        FROM pic_master.task t LEFT JOIN pic_master.task_details d ON d.task_id = t.task_id
        WHERE t.case_id = %s AND t.status = 'Active'
        ORDER BY t.task_id DESC
    """, (CASE_ID,)).fetchall()
    return [list(row) for row in rows]


def database_error():
    logging.exception("PostgreSQL operation failed")
    return gr.Error("Could not access PostgreSQL. Check the database connection and server log.")


def refresh_tasks(user=None):
    if user is not None:
        require_user(user)
    try:
        with connect_db() as conn:
            return list_tasks(conn)
    except psycopg.Error:
        raise database_error() from None


def refresh_task_view(user, revision):
    return refresh_tasks(user), revision + 1


def prepare_review(task_name):
    if task_name not in TASK_TYPES:
        return gr.update(visible=False), [], gr.update(choices=[], value=[]), ""
    try:
        with connect_db() as conn:
            available = qc.eligible_claims(conn, CASE_ID)
    except psycopg.Error:
        raise database_error() from None
    claims = [[str(claim.get(column, "")) for column in CLAIM_COLUMNS] for _, claim in available]
    ids = [claim_id for claim_id, _ in available]
    return gr.update(visible=True), claims, gr.update(
        choices=ids, value=ids, interactive=task_name != TASK_TYPES[0],
    ), ""


def persist_task(conn, task_name, claim_ids, comments, user=None):
    if task_name not in TASK_TYPES:
        raise ValueError("Select a valid review type.")
    # Serialize eligibility checks and reservations for this case.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (CASE_ID,))
    available = {claim_id: data for claim_id, data in qc.eligible_claims(conn, CASE_ID)}
    selected = list(available) if task_name == TASK_TYPES[0] else list(dict.fromkeys(claim_ids or []))
    if not selected:
        raise ValueError("No eligible claims selected. Refresh the review type to check available claims.")
    if not set(selected).issubset(available):
        raise ValueError("Some claims are no longer eligible. Select the review type again.")
    if len(comments or "") > 4000:
        raise ValueError("Comments must be 4,000 characters or fewer.")
    task_id = conn.execute("""
        INSERT INTO pic_master.task
            (task_name, task_status, status, case_id, task_comment,
             task_queue_name, created_by, created_by_name)
        VALUES (%s, 'Not Started', 'Active', %s, %s, 'QC Nurse', %s, %s)
        RETURNING task_id
    """, (task_name, CASE_ID, comments or "", actor_id(user), actor_name(user))).fetchone()[0]
    details = {"claimsForReviews": [{"claimNumber": claim_id} for claim_id in selected]}
    conn.execute("""
        INSERT INTO pic_master.task_details (task_id, task_canonical, status, created_by)
        VALUES (%s, %s, 'Active', %s)
    """, (task_id, Jsonb(details), actor_id(user)))
    qc.add_reviews(conn, task_id, CASE_ID, selected)
    qc.sync_canonical(conn, task_id, actor_id(user))
    return task_id


def create_task(task_name, claim_ids, comments, user=None):
    require_user(user)
    try:
        with connect_db() as conn:
            task_id = persist_task(conn, task_name, claim_ids, comments, user)
            rows = list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    return rows, gr.update(visible=False), gr.update(value=None), f"Task {task_id} created. Status: Not Started."


def cancel_review():
    return gr.update(visible=False), gr.update(value=None), "Task creation cancelled."


STATUSES = ["Not Started", "In Progress", "Completed"]


def open_task(table, evt: gr.SelectData):
    task_id = int(table[evt.index[0]][0])
    try:
        with connect_db() as conn:
            row = conn.execute(
                "SELECT t.task_status, COALESCE(t.assigned_to_name, ''), "
                "COALESCE(t.task_comment, ''), d.task_canonical "
                "FROM pic_master.task t JOIN pic_master.task_details d ON d.task_id = t.task_id "
                "WHERE t.task_id = %s AND t.case_id = %s AND t.status = 'Active'",
                (task_id, CASE_ID),
            ).fetchone()
    except psycopg.Error:
        raise database_error() from None
    if row is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    return task_id, gr.update(visible=True), row[0], row[1], row[2], row[3], gr.update(
        choices=[c["claimNumber"] for c in row[3]["claimsForReviews"]],
        value=[c["claimNumber"] for c in row[3]["claimsForReviews"]],
    )


def persist_update(conn, task_id, status, assigned_to, comments, claim_ids=None, user=None):
    if len(assigned_to or "") > 100 or len(comments or "") > 4000:
        raise ValueError("Assignee name must be at most 100 characters; comments at most 4,000.")
    qc.lock_task(conn, task_id, CASE_ID)
    # Workflow status and claim membership are controlled by the review queue.
    conn.execute("""
        UPDATE pic_master.task SET assigned_to_name = %s, task_comment = %s,
        updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
    """, (assigned_to or None, comments or "", actor_id(user), task_id))
    return conn.execute(
        "SELECT task_canonical FROM pic_master.task_details WHERE task_id = %s", (task_id,),
    ).fetchone()[0]


def save_details(task_id, status, assigned_to, comments, claim_ids, user=None):
    if task_id is None:
        raise gr.Error("Select a task first.")
    try:
        with connect_db() as conn:
            details = persist_update(conn, task_id, status, assigned_to, comments, claim_ids, user)
            rows = list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    return rows, details, f"Task {task_id} updated."


def review_outputs(conn, task_id):
    rows, current = qc.review_view(conn, task_id)
    status, canonical = conn.execute(
        "SELECT t.task_status, d.task_canonical FROM pic_master.task t "
        "JOIN pic_master.task_details d ON d.task_id = t.task_id WHERE t.task_id = %s",
        (task_id,),
    ).fetchone()
    queue = [[r[0], r[1], r[2].get("outcome", ""), r[2].get("notes", "")] for r in rows]
    pending = any(r[1] == 'Created' for r in rows)
    return (
        list_tasks(conn), status, canonical, queue,
        current[0] if current else None, current[3] if current else {},
        current[2].get("outcome", "") if current else "",
        current[2].get("notes", "") if current else "",
        gr.update(interactive=pending and current is None and status != 'Completed'),
        gr.update(interactive=current is not None), gr.update(interactive=current is not None),
    )


def run_review(action, task_id, claim_id=None, outcome="", notes="", user=None):
    if task_id is None:
        raise gr.Error("Select a task first.")
    try:
        with connect_db() as conn:
            qc.lock_task(conn, task_id, CASE_ID)
            if action == 'start':
                qc.start_next(conn, task_id, CASE_ID, actor_id(user))
            elif action in ('draft', 'complete'):
                qc.save_review(conn, task_id, CASE_ID, claim_id, outcome, notes,
                               action == 'complete', actor_id(user))
            return review_outputs(conn, task_id)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None


def task_action(conn, task_id, action, user=None):
    qc.lock_task(conn, task_id, CASE_ID)
    if action == "assign":
        recipient = actor_id(user)
        previous = conn.execute(
            "SELECT assigned_to FROM pic_master.task WHERE task_id = %s",
            (task_id,),
        ).fetchone()[0]
        conn.execute("""
            UPDATE pic_master.task SET assigned_to = %s, assigned_to_name = %s,
            task_status = 'In Progress', task_cmpled_dts = NULL,
            updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
        """, (recipient, actor_name(user), recipient, task_id))
        if previous != recipient:
            conn.execute("""
                INSERT INTO pic_master.qc_notifications
                    (task_id, recipient_racf, notification_text)
                VALUES (%s, %s, %s)
            """, (task_id, recipient, f"Task {task_id} was assigned to you."))
    elif action == "delete":
        conn.execute("""
            UPDATE pic_master.claim_details c SET qc_status = 'Released',
                updated_dts = CURRENT_TIMESTAMP
            WHERE c.case_id = %s AND c.claim_number IN (
                SELECT j->>'claimNumber' FROM pic_master.task_details d,
                LATERAL jsonb_array_elements(d.task_canonical->'claimsForReviews') j
                WHERE d.task_id = %s)
        """, (CASE_ID, task_id))
        conn.execute("DELETE FROM pic_master.task_details WHERE task_id = %s", (task_id,))
        conn.execute("DELETE FROM pic_master.task WHERE task_id = %s", (task_id,))
    elif action == "finish":
        conn.execute("""
            UPDATE pic_master.claim_details c SET qc_status = 'Released',
                updated_dts = CURRENT_TIMESTAMP
            WHERE c.case_id = %s AND c.qc_status = 'Created'
              AND c.claim_number IN (
                SELECT j->>'claimNumber'
                FROM pic_master.task t
                JOIN pic_master.task_details d ON d.task_id = t.task_id,
                LATERAL jsonb_array_elements(d.task_canonical->'claimsForReviews') j
                WHERE t.task_id = %s AND t.task_status <> 'Completed')
        """, (CASE_ID, task_id))
        qc.sync_canonical(conn, task_id, actor_id(user))
        conn.execute("""
            UPDATE pic_master.task SET task_status = 'Completed',
            task_cmpled_dts = COALESCE(task_cmpled_dts, CURRENT_TIMESTAMP),
            updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
        """, (actor_id(user), task_id))
    else:
        raise ValueError("Unknown task action.")


def perform_task_action(task_id, action, user=None):
    require_user(user)
    try:
        with connect_db() as conn:
            task_action(conn, task_id, action, user)
            rows = list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    messages = {"assign": "Task assigned to you.", "delete": "Task deleted.", "finish": "Task completed."}
    return rows, messages[action]


def task_metadata(task_id):
    with connect_db() as conn:
        row = conn.execute("""
            SELECT COALESCE(t.assigned_to, ''), COALESCE(t.created_by, ''),
                   COALESCE(created_by_name, ''), d.task_canonical
            FROM pic_master.task t JOIN pic_master.task_details d USING (task_id)
            WHERE t.task_id = %s AND t.case_id = %s AND t.status = 'Active'
        """, (task_id, CASE_ID)).fetchone()
    return row


def save_task_comments(task_id, comments, user=None):
    require_user(user)
    try:
        with connect_db() as conn:
            qc.lock_task(conn, task_id, CASE_ID)
            if len(comments or '') > 4000:
                raise ValueError('Comments must be 4,000 characters or fewer.')
            conn.execute("UPDATE pic_master.task SET task_comment = %s, updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s", (comments, actor_id(user), task_id))
            rows = list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    return rows, "Comments saved."


def task_row_label(row):
    return "\t".join(str(value or "?").replace("\t", " ") for value in
                     (row[0], row[1], CASE_ID, row[2], row[3], row[4], row[5]))


def refresh_task_heading(task_id):
    with connect_db() as conn:
        row = next(r for r in list_tasks(conn) if r[0] == task_id)
    assigned_id, creator_id, creator_name, _ = task_metadata(task_id)
    label = task_row_label(row)
    fields = [("Task ID", task_id), ("Task Name", row[1]), ("Task Status", row[2]), ("Created Date", row[4]),
              ("Assigned to RACF", assigned_id), ("Assigned to Name", row[3]),
              ("Created by RACF", creator_id), ("Created by Name", creator_name)]
    return display_fields(fields), gr.update(label=label)


def claims_for_review_html(canonical):
    numbers = [str(claim['claimNumber']) for claim in canonical.get('claimsForReviews', [])]
    items = ''.join('<li>' + escape(number) + '</li>' for number in numbers)
    return (
        '<section class="claim-list-section" aria-label="Claims for review">'
        '<div class="claim-list-heading"><strong>Claims For Review</strong>'
        f'<span>{len(numbers)} claims</span></div>'
        '<div class="claim-list-scroll" tabindex="0" role="region" aria-label="Claim numbers">'
        + ('<ul class="claim-number-list">' + items + '</ul>' if numbers else '<p>No claims.</p>')
        + '</div></section>'
    )


def display_fields(fields):
    return '<div class="task-fields">' + ''.join(
        '<div><strong>' + escape(label) + '</strong><span>' + escape(str(value or '?')) + '</span></div>'
        for label, value in fields
    ) + '</div>'


def expand_claim_panels(selected, count):
    return [gr.update(open=index == selected) for index in range(count)]


def qc_comment_options(decision, saved=None):
    if decision == 'Agree':
        return dict(choices=['Completed'], value='Completed', interactive=False)
    if decision == 'Action Required':
        if saved == 'Correction Required':
            saved = 'Correction required'
        choices = ['Response Required', 'Correction required']
        return dict(choices=choices, value=saved if saved in choices else None, interactive=True)
    return dict(choices=[], value=None, interactive=False)


def update_qc_comment(decision):
    return gr.update(**qc_comment_options(decision))


def save_claim_form(task_id, claim_id, categories, decision, comment, user=None):
    require_user(user)
    try:
        with connect_db() as conn:
            qc.save_claim_decision(
                conn, task_id, CASE_ID, claim_id, decision, comment, actor_id(user),
                categories,
            )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    return (
        f"Claim {claim_id} saved: {decision}.",
        gr.update(label=f"{claim_id}    |    QC Review: {decision}"),
        gr.update(interactive=False),
    )


def save_claim_edit_form(
    task_id, claim_id, clinical_determination, generic_reason_code, coding,
    decision_remarks, other, points, decision, comment, user=None,
):
    require_user(user)
    categories = [
        name for name, checked in zip(
            qc.QC_REVIEW_CATEGORIES,
            (
                clinical_determination, generic_reason_code, coding,
                decision_remarks, other,
            ),
        )
        if checked
    ]
    try:
        with connect_db() as conn:
            qc.save_claim_decision(
                conn, task_id, CASE_ID, claim_id, decision, comment, actor_id(user),
                categories, points,
            )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    return (
        f"QC review updated for {claim_id}.",
        gr.update(visible=False),
        claim_review_summary_html(task_id, claim_id),
    )


def review_area_checked(details, category):
    field = qc.QC_REVIEW_CATEGORY_FIELDS[category]
    if field in details:
        return bool(details[field])
    return category in details.get('reviewCategories', [])


def claim_review_summary_html(task_id, claim_id):
    metadata = task_metadata(task_id)
    if metadata is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    item = next(
        (claim for claim in metadata[3].get('claimsForReviews', [])
         if claim.get('claimNumber') == claim_id),
        None,
    )
    if item is None:
        raise gr.Error("This claim is no longer part of the selected task.")
    return _claim_review_summary_html(item)


def _claim_review_summary_html(item):
    claim_id = item['claimNumber']
    details = item.get('qcReviewDetails', {})
    decision = details.get('qcReview', '')
    comment = details.get('qcReviewComment', '')
    reviewer = details.get('reviewedBy', '')
    categories = ', '.join(
        category for category in qc.QC_REVIEW_CATEGORIES
        if review_area_checked(details, category)
    )
    points = details.get('points', '')
    return (
        '<div class="qc-review-row"><strong>' + escape(str(claim_id)) +
        '</strong><span>' + escape(str(decision)) + '</span><span>' +
        escape(str(comment)) + '</span><span>' + escape(categories) +
        '</span><span>' + escape(str(points)) + '</span><small>Reviewed by ' +
        escape(str(reviewer)) + '</small></div>'
    )


def open_claim_editor(task_id, claim_id, user=None):
    require_user(user)
    metadata = task_metadata(task_id)
    if metadata is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    item = next(
        (claim for claim in metadata[3].get('claimsForReviews', [])
         if claim.get('claimNumber') == claim_id),
        None,
    )
    if item is None:
        raise gr.Error("This claim is no longer part of the selected task.")
    details = item.get('qcReviewDetails', {})
    try:
        with connect_db() as conn:
            recipient = claim_note_reply_recipient(conn, task_id, claim_id, actor_id(user))
    except psycopg.Error:
        raise database_error() from None
    return (
        gr.update(visible=True),
        claim_conversation_html(task_id, claim_id),
        gr.update(value=recipient),
        gr.update(value=review_area_checked(details, 'Clinical Determination')),
        gr.update(value=review_area_checked(details, 'Generic Reason Code')),
        gr.update(value=review_area_checked(details, 'Coding')),
        gr.update(value=review_area_checked(details, 'Decision Remarks')),
        gr.update(value=review_area_checked(details, 'Other')),
        gr.update(value=details.get('points', '')),
        gr.update(value=(
            'Action Required' if details.get('qcReview') == 'Returned for Corrections'
            else details.get('qcReview')
        )),
        gr.update(**qc_comment_options(
            'Action Required' if details.get('qcReview') == 'Returned for Corrections'
            else details.get('qcReview'),
            details.get('qcReviewComment'),
        )),
    )


def open_claim_editor_group(task_id, claim_id, user=None):
    values = open_claim_editor(task_id, claim_id, user)
    selected = [area for area, update in zip(qc.QC_REVIEW_CATEGORIES, values[3:8]) if update['value']]
    return (*values[:3], gr.update(value=selected, visible=True), *values[8:])


def save_claim_edit_group(task_id, claim_id, areas, points, decision, comment, user=None):
    checked = [area in (areas or []) for area in qc.QC_REVIEW_CATEGORIES]
    return save_claim_edit_form(task_id, claim_id, *checked, points, decision, comment, user)


def claim_note_reply_recipient(conn, task_id, claim_id, current_actor=None):
    last_message = conn.execute("""
        SELECT sender_racf, recipient_racf
        FROM pic_master.qc_claim_messages
        WHERE task_id = %s AND claim_number = %s
        ORDER BY created_dts DESC, message_id DESC
        LIMIT 1
    """, (task_id, claim_id)).fetchone()
    if last_message is None:
        return current_actor or ACTOR_ID
    sender, recipient = last_message
    return recipient if sender == (current_actor or ACTOR_ID) else sender


def notification_recipients(recipient, assigned_racf):
    return list(dict.fromkeys(
        user.strip() for user in (recipient, assigned_racf or '') if user and user.strip()
    ))


def persist_claim_note(conn, task_id, claim_id, recipient, message, user=None):
    qc.lock_task(conn, task_id, CASE_ID)
    if claim_id not in {row[0] for row in qc.review_view(conn, task_id)[0]}:
        raise ValueError("This claim does not belong to the selected task.")
    task = conn.execute("""
        SELECT COALESCE(assigned_to, '') FROM pic_master.task
        WHERE task_id = %s AND case_id = %s
    """, (task_id, CASE_ID)).fetchone()
    if task is None:
        raise ValueError("Select an active task first.")
    assigned_racf = task[0]
    message_id = conn.execute("""
        INSERT INTO pic_master.qc_claim_messages
            (task_id, claim_number, sender_racf, recipient_racf, assigned_racf, message_text)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING message_id
    """,     (task_id, claim_id, actor_id(user), recipient, assigned_racf or None, message)).fetchone()[0]
    for user in notification_recipients(recipient, assigned_racf):
        conn.execute("""
        INSERT INTO pic_master.qc_notifications
            (message_id, task_id, claim_number, recipient_racf, notification_text)
        VALUES (%s, %s, %s, %s, %s)
    """, (message_id, task_id, claim_id, user, message))


def claim_conversation_html(task_id, claim_id):
    try:
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT sender_racf, recipient_racf, message_text, created_dts
                FROM pic_master.qc_claim_messages
                WHERE task_id = %s AND claim_number = %s
                ORDER BY created_dts, message_id
            """, (task_id, claim_id)).fetchall()
    except psycopg.Error:
        raise database_error() from None
    if not rows:
        return '<p class="qc-empty">No notes in this conversation yet.</p>'
    return '<div class="qc-conversation">' + ''.join(
        '<div class="qc-message"><strong>' + escape(str(sender)) + ' to ' +
        escape(str(recipient)) + '</strong><small>' +
        escape(str(created)) + '</small><p>' + escape(str(message)) +
        '</p></div>'
        for sender, recipient, message, created in rows
    ) + '</div>'


def send_claim_note_form(task_id, claim_id, recipient, message, user=None):
    require_user(user)
    recipient = (recipient or '').strip()
    message = (message or '').strip()
    recipient = recipient or actor_id(user)
    if len(recipient) > 100:
        raise gr.Error("RACF/user name must be 100 characters or fewer.")
    if not message or len(message) > 4000:
        raise gr.Error("Enter a note of 1 to 4,000 characters.")
    try:
        with connect_db() as conn:
            persist_claim_note(conn, task_id, claim_id, recipient, message, user)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise database_error() from None
    return (
        f"Note sent to {recipient}; the assigned nurse was alerted when assigned.",
        claim_conversation_html(task_id, claim_id),
        gr.update(value=""),
    )


def notifications_html(user=None):
    current_actor = actor_id(require_user(user))
    try:
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT n.notification_id, n.task_id, COALESCE(n.claim_number, ''),
                       COALESCE(m.sender_racf, 'System'), n.notification_text, n.created_dts
                FROM pic_master.qc_notifications n
                LEFT JOIN pic_master.qc_claim_messages m USING (message_id)
                WHERE n.recipient_racf = %s AND n.read_dts IS NULL
                ORDER BY n.created_dts DESC, n.notification_id DESC
                LIMIT 50
            """, (current_actor,)).fetchall()
    except psycopg.Error:
        raise database_error() from None
    if not rows:
        return '<p class="qc-empty">No unread alerts.</p>'
    return '<div class="qc-alerts">' + ''.join(
        '<div class="qc-message"><strong>Task ' + escape(str(task_id)) +
        ' / Claim ' + escape(str(claim_id)) + '</strong><small>From ' +
        escape(str(sender)) + ' | ' + escape(str(created)) +
        '</small><p>' + escape(str(message)) + '</p></div>'
        for _, task_id, claim_id, sender, message, created in rows
    ) + '</div>'


def notification_badge(user=None):
    if not user:
        return "Alerts (0)"
    require_user(user)
    try:
        with connect_db() as conn:
            count = conn.execute("""
                SELECT count(*) FROM pic_master.qc_notifications
                WHERE recipient_racf = %s AND read_dts IS NULL
            """, (actor_id(user),)).fetchone()[0]
    except psycopg.Error:
        raise database_error() from None
    return gr.update(value=f"Alerts ({count})")


def open_alerts(user=None):
    require_user(user)
    return gr.update(visible=True), notifications_html(user), notification_badge(user)


def close_alerts():
    return gr.update(visible=False)


def mark_notifications_read(user=None):
    require_user(user)
    try:
        with connect_db() as conn:
            conn.execute("""
                UPDATE pic_master.qc_notifications SET read_dts = CURRENT_TIMESTAMP
                WHERE recipient_racf = %s AND read_dts IS NULL
            """, (actor_id(user),))
    except psycopg.Error:
        raise database_error() from None
    return notifications_html(user), notification_badge(user)


def completed_claims(canonical):
    return [
        item for item in canonical.get('claimsForReviews', [])
        if item.get('qcReviewStatus') in qc.REVIEWED_STATUSES
        and item.get('qcReviewDetails', {}).get('qcReview')
        in (*qc.QC_DECISIONS, 'Returned for Corrections')
    ]


TASK_ROW_JS = """() => {
    const alignRows = () => {
        document.querySelectorAll('.task-summary > button.label-wrap > span:not(.icon)').forEach(label => {
            if (label.children.length) return;
            const values = label.textContent.split('\t');
            if (values.length !== 7) return;
            label.replaceChildren(...values.map(value => {
                const cell = document.createElement('span');
                cell.textContent = value;
                return cell;
            }));
        });
    };
    let scheduled = false;
    new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; alignRows(); });
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
    alignRows();
}"""

CSS = """
.qc-component-loader { display: none !important; }
.gradio-container { max-width: 1450px !important; }
.gradio-container .qc-overlay {
 position: fixed !important; inset: 0 !important; z-index: 1000 !important;
 width: 100vw !important; height: 100dvh !important; max-height: 100dvh !important;
 background: rgba(15, 23, 42, .58) !important; padding: 4vh 4vw !important;
 overflow-y: auto !important; border: 0 !important;
}
.gradio-container .qc-dialog {
 background: #fff !important; color: #172b4d !important;
 width: 100% !important; max-width: 1250px; margin: auto;
 padding: 24px !important; border-radius: 8px !important;
 box-shadow: 0 16px 60px #0005;
}
.qc-results { width: 100%; border-collapse: collapse; }
.qc-results th { background: #edf2f7; color: #172b4d; text-align: left; }
.qc-results th, .qc-results td { padding: 10px; border-bottom: 1px solid #d5dce3; }
.qc-empty { text-align: center; padding: 16px; }
.qc-review-header { display: grid; grid-template-columns: 1.2fr 1fr 1.5fr 2fr .7fr 1.2fr; gap: 12px; padding: 8px 12px; background: #edf2f7; font-weight: 700; }
.qc-review-row { display: grid; grid-template-columns: 1.2fr 1fr 1.5fr 2fr .7fr 1.2fr; gap: 12px; align-items: center; padding: 10px 12px; }
.qc-review-row small { color: #52677f; }
.gradio-container .qc-area-group { padding: 12px !important; background: #fff !important; }
.gradio-container .qc-area-group .wrap { display: flex !important; flex-direction: column; gap: 8px; }
.gradio-container .qc-area-group label { display: flex !important; min-height: 40px; color: #172b4d !important; background: #f1f5f9 !important; border: 1px solid #94a3b8 !important; }
.gradio-container .qc-area-group label span { color: #172b4d !important; }
.gradio-container .qc-area-group input[type="checkbox"] { appearance: auto !important; width: 20px !important; height: 20px !important; opacity: 1 !important; accent-color: #1764a2; }
.qc-message { border: 1px solid #d5dce3; padding: 10px 12px; margin: 8px 0; }
.qc-message small { display: block; color: #52677f; margin-top: 4px; }
.qc-message p { white-space: pre-wrap; margin: 8px 0 0; }
.qc-login-overlay {
 position: fixed !important; inset: 0 !important; z-index: 3000 !important;
 width: 100vw !important; height: 100dvh !important; max-height: 100dvh !important;
 background: rgba(15, 23, 42, .94) !important;
 align-items: center; justify-content: center; padding: 24px !important;
}
.qc-login-overlay > .qc-login-card {
 width: min(440px, 100%); background: #fff; padding: 28px;
 border-radius: 10px; box-shadow: 0 16px 60px #0005;
}
.qc-user-bar {
 position: fixed !important; top: 12px; right: 18px; z-index: 1200;
 width: auto !important; background: white; padding: 8px 12px;
 border: 1px solid #d5dce3; border-radius: 8px; box-shadow: 0 4px 18px #0002;
 display: flex !important; flex-wrap: nowrap !important; align-items: center;
 gap: 8px; white-space: nowrap;
}
.qc-user-name { text-align: center !important; margin: 8px auto 16px !important; }
.qc-user-name p { text-align: center !important; margin: 0 !important; font-size: 18px; font-weight: 600; }
.qc-alert-popup {
 position: fixed !important; top: 68px; right: 18px; z-index: 1300;
 width: min(440px, calc(100vw - 36px)); max-height: 70vh; overflow-y: auto;
 background: white; border: 1px solid #d5dce3; border-radius: 8px;
 box-shadow: 0 12px 36px #0003; padding: 14px;
}
.gradio-container .task-header { background-color: #3b4148 !important; color: #fff !important; padding: 10px 12px 10px 38px;
 display: grid; grid-template-columns: .7fr 1.7fr 1fr 1fr 1fr 1.2fr 1.2fr; gap: 12px; font-size: 12px; }
.gradio-container .task-header span { color: #fff !important; font-weight: 700; }
.task-entry { border: 1px solid #d5dce3 !important; border-radius: 0 !important; }
.gradio-container .task-entry > button.label-wrap {
 display: flex !important; flex-direction: row !important;
 justify-content: flex-start !important; gap: 10px; padding: 10px 12px;
 background-color: #edf2f7 !important; color: #172b4d !important;
}
.gradio-container .task-entry > button.label-wrap > span:not(.icon) {
 order: 1; flex: 1 1 auto; text-align: left; white-space: pre-wrap; color: #172b4d !important;
}
.gradio-container .task-entry > button.label-wrap > span.icon {
 order: 0; flex: 0 0 16px; width: 16px; margin: 0 !important;
 color: #174c7a !important; text-align: center;
}
.gradio-container .task-entry > button.label-wrap:focus-visible { outline: 2px solid #1764a2; }
.gradio-container .task-summary > button.label-wrap > span:not(.icon) {
 display: grid !important; grid-template-columns: .7fr 1.7fr 1fr 1fr 1fr 1.2fr 1.2fr;
 gap: 12px; min-width: 0; align-items: center;
}
.task-summary > button.label-wrap > span:not(.icon) > span {
 min-width: 0; overflow-wrap: anywhere; white-space: normal; font-size: 12px;
}
.task-fields { display: grid; grid-template-columns: repeat(4, 1fr); gap: 25px; padding: 14px 8px; }
.task-fields strong { display:block; font-size: 11px; text-transform: uppercase; margin-bottom: 8px; }
.task-fields span { font-size: 13px; }
.claim-list-section { padding: 14px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; }
.claim-list-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; color: #172b4d; }
.claim-list-heading > span { font-size: 12px; color: #475569; background: #edf2f7; border-radius: 12px; padding: 3px 10px; }
.claim-list-scroll { max-height: 200px; overflow-y: auto; scrollbar-gutter: stable; }
.claim-list-scroll:focus-visible { outline: 2px solid #1764a2; outline-offset: 3px; }
.claim-number-list { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 !important; margin: 0 !important; list-style: none !important; }
.claim-number-list > li { margin: 0 !important; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 4px; background: #f1f5f9; color: #172b4d; font-family: ui-monospace, monospace; font-size: 13px; max-width: 100%; overflow-wrap: anywhere; user-select: text; }
.qc-bar { background: #174c7a; color: white; padding: 6px 10px; font-weight: bold; }
.task-actions button { background: #1764a2; color: white; border-radius: 2px; }
@media(max-width: 700px) { .task-fields { grid-template-columns: repeat(2, 1fr); } }
"""

with gr.Blocks(title="Tasks", theme=gr.themes.Soft(primary_hue="blue"), css=CSS, js=TASK_ROW_JS, analytics_enabled=False) as demo:
    # Load this component's frontend before it is used inside dynamic task popups.
    gr.CheckboxGroup(choices=list(qc.QC_REVIEW_CATEGORIES), elem_classes="qc-component-loader")
    task_rows = gr.State([])
    user_state = gr.State(None)
    with gr.Column(elem_classes="qc-login-overlay") as login_panel:
        with gr.Column(elem_classes="qc-login-card"):
            gr.Markdown("## Sign in")
            gr.Markdown("Choose your user name to open the QC workspace.")
            login_choice = gr.Dropdown(
                choices=[("Pandu (QC Nurse)", "pandu"), ("Regine (Nurse)", "regine")],
                label="User name", value=None, filterable=False,
            )
            login_button = gr.Button("Sign in", variant="primary")
    user_banner = gr.Markdown("", elem_classes="qc-user-name")
    with gr.Row(elem_classes="qc-user-bar"):
        alert_button = gr.Button("Alerts (0)", size="sm")
        logout_button = gr.Button("Sign out", size="sm")
    with gr.Column(visible=False, elem_classes="qc-alert-popup") as alert_popup:
        notifications_panel = gr.HTML('<p class="qc-empty">No unread alerts.</p>')
        with gr.Row():
            mark_alerts_read = gr.Button("Mark Read", size="sm")
            close_alert_button = gr.Button("Close", size="sm")
    alert_timer = gr.Timer(15)
    task_view_revision = gr.State(0)
    with gr.Tab("Tasks"):
        with gr.Row():
            gr.Markdown("## Tasks")
            task_dropdown = gr.Dropdown(choices=TASK_TYPES, value=None, label="Create Task", filterable=False)
        notice = gr.Markdown("")
        with gr.Column(visible=False) as review_panel:
            claims_table = gr.Dataframe(value=[], headers=CLAIM_COLUMNS, interactive=False, type="array")
            selected_claims = gr.Dropdown(choices=[], value=[], multiselect=True, label="Claims to include")
            comments = gr.Textbox(label="Comments", lines=3)
            with gr.Row():
                cancel_button = gr.Button("Cancel")
                create_button = gr.Button("Create", variant="primary", interactive=False)
        selected_claims.change(lambda ids: gr.update(interactive=bool(ids)), selected_claims, create_button, queue=False)
        task_dropdown.input(prepare_review, task_dropdown, [review_panel, claims_table, selected_claims, comments])
        create_button.click(create_task, [task_dropdown, selected_claims, comments, user_state],
                            [task_rows, review_panel, task_dropdown, notice])
        cancel_button.click(cancel_review, outputs=[review_panel, task_dropdown, notice])
        gr.HTML('<div class="task-header"><span>TASK ID</span><span>TASK NAME</span><span>CASE NUMBER</span><span>STATUS</span><span>ASSIGNED TO</span><span>CREATED ON</span><span>COMPLETED ON</span></div>')

        @gr.render(inputs=[task_rows, user_state, task_view_revision])
        def render_tasks(rows, user, _revision):
            if not user:
                gr.Markdown("Sign in to view tasks.")
                return
            if not rows:
                gr.Markdown("No tasks to display.")
            for index, row in enumerate(rows):
                task_id = row[0]
                metadata = task_metadata(task_id)
                if metadata is None:
                    continue
                assigned_id, creator_id, creator_name, canonical = metadata
                label = task_row_label(row)
                with gr.Accordion(label, open=index == 0, elem_classes=["task-entry", "task-summary"], key=f"task-{task_id}") as task_expansion:
                    task_id_state = gr.State(task_id)
                    with gr.Row():
                        with gr.Column(scale=4):
                            summary = gr.HTML(display_fields([
                                ("Task ID", task_id), ("Task Name", row[1]), ("Task Status", row[2]), ("Created Date", row[4]),
                                ("Assigned to RACF", assigned_id), ("Assigned to Name", row[3]),
                                ("Created by RACF", creator_id), ("Created by Name", creator_name),
                            ]))
                        with gr.Column(scale=1, elem_classes="task-actions"):
                            assign = gr.Button("SELF ASSIGN", size="sm")
                            delete = gr.Button("DELETE TASK", size="sm")
                    comment = gr.Textbox(value=row[7], label="Comments", lines=2)
                    save = gr.Button("Save Comments", size="sm")
                    with gr.Row():
                        gr.Markdown("")
                        finish = gr.Button("Complete Task", scale=0, size="sm")
                    gr.HTML(claims_for_review_html(canonical))
                    review = gr.Button("+ Review Claims", size="sm")
                    gr.HTML('<div class="qc-bar">QC Review Information</div>')
                    gr.HTML('<div class="qc-review-header"><span>Claim</span><span>QC Review</span><span>QC Review Comment</span><span>Review Areas</span><span>Points</span><span>Reviewed By</span></div>')
                    for item in completed_claims(canonical):
                        claim_id = item['claimNumber']
                        review_details = item.get('qcReviewDetails', {})
                        saved_decision = review_details['qcReview']
                        edit_decision_value = (
                            'Action Required' if saved_decision == 'Returned for Corrections'
                            else saved_decision
                        )
                        with gr.Row(equal_height=True):
                            with gr.Column(scale=5, min_width=0):
                                claim_summary = gr.HTML(_claim_review_summary_html(item))
                            with gr.Column(scale=1, min_width=70):
                                edit_claim = gr.Button("Edit", size="sm")
                        with gr.Column(visible=False, elem_classes="qc-overlay") as edit_overlay:
                            with gr.Column(elem_classes="qc-dialog"):
                                gr.Markdown(f"### Claim {claim_id}")
                                close_edit = gr.Button("Close", size="sm")
                                gr.Markdown("#### Select Review Areas")
                                gr.Markdown("Check each area that applies to this claim.")
                                edit_areas = gr.CheckboxGroup(
                                    choices=list(qc.QC_REVIEW_CATEGORIES),
                                    value=[area for area in qc.QC_REVIEW_CATEGORIES if review_area_checked(review_details, area)],
                                    label="Review Areas", show_label=False, interactive=True,
                                    elem_classes="qc-area-group",
                                )
                                edit_points = gr.Textbox(
                                    value=review_details.get('points', ''),
                                    label="Points", max_length=100,
                                )
                                with gr.Row():
                                    edit_decision = gr.Dropdown(
                                        choices=list(qc.QC_DECISIONS), value=edit_decision_value,
                                        label="QC Review",
                                    )
                                    edit_comment = gr.Dropdown(
                                        label="QC Review Comment",
                                        **qc_comment_options(edit_decision_value, review_details.get('qcReviewComment')),
                                    )
                                edit_decision.change(update_qc_comment, edit_decision, edit_comment, queue=False)
                                edit_notice = gr.Markdown("")
                                save_edit = gr.Button("Save Points and QC Review", variant="primary")
                                edit_claim_id_state = gr.State(claim_id)
                                save_edit.click(
                                    save_claim_edit_group,
                                    [
                                        task_id_state, edit_claim_id_state, edit_areas,
                                        edit_points, edit_decision, edit_comment, user_state,
                                    ],
                                    [edit_notice, edit_overlay, claim_summary],
                                ).then(refresh_task_heading, task_id_state, [summary, task_expansion])
                                gr.Markdown("#### Conversation and notes")
                                conversation = gr.HTML('<p class="qc-empty">Open this editor to load notes.</p>')
                                recipient = gr.Textbox(
                                    label="Send note to RACF/user name (optional; blank sends to yourself)",
                                    max_length=100,
                                )
                                note_text = gr.Textbox(label="Note", lines=3, max_length=4000)
                                send_note = gr.Button("Send Note", variant="primary")
                                note_notice = gr.Markdown("")
                                send_note.click(
                                    send_claim_note_form,
                                    [task_id_state, edit_claim_id_state, recipient, note_text, user_state],
                                    [note_notice, conversation, note_text],
                                ).then(notifications_html, user_state, notifications_panel).then(
                                    notification_badge, user_state, alert_button,
                                )
                        edit_claim.click(
                            open_claim_editor_group, [task_id_state, edit_claim_id_state, user_state],
                            [
                                edit_overlay, conversation, recipient, edit_areas,
                                edit_points, edit_decision, edit_comment,
                            ],
                        )
                        close_edit.click(lambda: gr.update(visible=False), outputs=edit_overlay)
                    with gr.Column(visible=False, elem_classes="qc-overlay") as work_panel:
                        with gr.Column(elem_classes="qc-dialog"):
                            gr.Markdown(f"### Review Claims ? Task {task_id}")
                            close_popup = gr.Button("Close", size="sm")
                            gr.Markdown("Expand a claim to enter its QC review.")
                            with connect_db() as conn:
                                claim_rows, _ = qc.review_view(conn, task_id)
                            claim_panels = []
                            for claim_id, claim_status, review_details, data in claim_rows:
                                with gr.Accordion(
                                    f"{claim_id}    |    QC Review: {claim_status}", open=False,
                                    elem_classes="task-entry", key=f"claim-{task_id}-{claim_id}",
                                ) as claim_panel:
                                    claim_panels.append(claim_panel)
                                    gr.HTML(display_fields([(column, data.get(column, '')) for column in CLAIM_COLUMNS]))
                                    claim_id_state = gr.State(claim_id)
                                    saved_decision = 'Action Required' if claim_status == 'Returned for Corrections' else claim_status
                                    categories = gr.CheckboxGroup(
                                        choices=list(qc.QC_REVIEW_CATEGORIES),
                                        value=review_details.get('reviewCategories', []),
                                        label="Review Areas",
                                    )
                                    with gr.Row():
                                        decision = gr.Dropdown(
                                            choices=list(qc.QC_DECISIONS),
                                            value=saved_decision if saved_decision in qc.QC_DECISIONS else None,
                                            label="QC Review", interactive=True,
                                        )
                                        review_comment = gr.Dropdown(
                                            label="QC Review Comment",
                                            **qc_comment_options(saved_decision, review_details.get('qcReviewComment')),
                                        )
                                    decision.change(update_qc_comment, decision, review_comment, queue=False)
                                    save_claim = gr.Button(
                                        "Save", variant="primary",
                                        interactive=claim_status not in qc.REVIEWED_STATUSES,
                                    )
                                    claim_notice = gr.Markdown("")
                                    save_claim.click(
                                        save_claim_form,
                                        [
                                            task_id_state, claim_id_state, categories,
                                            decision, review_comment, user_state,
                                        ],
                                        [claim_notice, claim_panel, save_claim],
                                    ).then(
                                        refresh_task_heading, task_id_state, [summary, task_expansion],
                                    ).then(
                                        refresh_task_view,
                                        [user_state, task_view_revision],
                                        [task_rows, task_view_revision],
                                    )
                            for claim_index, panel in enumerate(claim_panels):
                                panel.expand(partial(expand_claim_panels, claim_index, len(claim_panels)), outputs=claim_panels, queue=False)
                    close_popup.click(lambda: gr.update(visible=False), outputs=work_panel)
                    assign.click(lambda tid, user: perform_task_action(tid, 'assign', user), [task_id_state, user_state], [task_rows, notice]).then(
                        notification_badge, user_state, alert_button,
                    )
                    delete.click(lambda tid, user: perform_task_action(tid, 'delete', user), [task_id_state, user_state], [task_rows, notice])
                    finish.click(lambda tid, user: perform_task_action(tid, 'finish', user), [task_id_state, user_state], [task_rows, notice])
                    save.click(save_task_comments, [task_id_state, comment, user_state], [task_rows, notice])
                    review.click(lambda: gr.update(visible=True), outputs=work_panel)
        refresh = gr.Button("Refresh Tasks", size="sm")
        refresh.click(
            refresh_task_view, [user_state, task_view_revision],
            [task_rows, task_view_revision],
        )
    login_button.click(
        login_user, login_choice,
        [user_state, login_panel, user_banner, task_rows, alert_button],
    )
    logout_button.click(
        logout_user,
        outputs=[user_state, login_panel, user_banner, task_rows, alert_button],
    )
    alert_button.click(open_alerts, user_state, [alert_popup, notifications_panel, alert_button])
    close_alert_button.click(close_alerts, outputs=alert_popup)
    mark_alerts_read.click(mark_notifications_read, user_state, [notifications_panel, alert_button])
    alert_timer.tick(notification_badge, user_state, alert_button)


if __name__ == "__main__":
    initialize_db()
    demo.launch(share=True)
