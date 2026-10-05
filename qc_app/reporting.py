"""Read-only reports for the current case."""

from html import escape

import psycopg

from . import config, database, errors, identity, repository

REPORT_HEADERS = [*config.TASK_COLUMNS, "Claim", "QC Status", "QC Review", "QC Comment",
                  "Review Areas", "Contract Points", "Nurse Points", "Reviewed By", "Conversation Notes"]


def load_report(user):
    if not user:
        return []
    identity.require_user(user)
    try:
        with database.connect_db() as conn:
            tasks = repository.list_tasks(conn)
            reviews = conn.execute(
                """
                SELECT t.task_id, d.task_canonical
                FROM pic_master.task t JOIN pic_master.task_details d USING (task_id)
                WHERE t.case_id = %s AND t.status = 'Active' ORDER BY t.task_id DESC
                """, (config.CASE_ID,)
            ).fetchall()
            notes = conn.execute(
                """
                SELECT m.task_id, m.claim_number, m.sender_racf, m.recipient_racf,
                       m.message_text, to_char(m.created_dts, 'YYYY-MM-DD HH24:MI:SS')
                FROM pic_master.qc_claim_messages m JOIN pic_master.task t USING (task_id)
                WHERE t.case_id = %s AND t.status = 'Active'
                ORDER BY m.created_dts DESC, m.message_id DESC
                """, (config.CASE_ID,)
            ).fetchall()
    except psycopg.Error:
        raise errors.database_error() from None
    reviews_by_task = dict(reviews)
    notes_by_claim = {}
    for task_id, claim_id, sender, recipient, message, sent_on in notes:
        notes_by_claim.setdefault((task_id, claim_id), []).append(
            f"{sent_on} | {sender} to {recipient}: {message}"
        )
    rows = []
    for task in tasks:
        task_id = task[0]
        items = list(reviews_by_task.get(task_id, {}).get("claimsForReviews", []))
        claim_ids = {item.get("claimNumber", "") for item in items}
        # Preserve conversations even if a claim is no longer in the canonical list.
        items.extend({"claimNumber": claim_id} for tid, claim_id in notes_by_claim
                     if tid == task_id and claim_id not in claim_ids)
        for item in items or [{}]:
            claim_id = item.get("claimNumber", "")
            details = item.get("qcReviewDetails", {})
            rows.append([
                *task, claim_id, item.get("qcReviewStatus", ""),
                details.get("qcReview", ""), details.get("qcReviewComment", ""),
                ", ".join(details.get("reviewCategories", [])), details.get("points", ""),
                details.get("nursePoints", ""), details.get("reviewedBy", ""),
                "\n\n".join(notes_by_claim.get((task_id, claim_id), [])),
            ])
    return rows


def render_report(rows):
    if not rows:
        return '<p class="qc-empty">No tasks to report.</p>'
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    sections = []
    for task_id, task_rows in grouped.items():
        task = task_rows[0]
        metadata = "".join(
            f'<div><strong>{escape(label)}</strong><span>{escape(str(value))}</span></div>'
            for label, value in zip(config.TASK_COLUMNS[2:7], task[2:7])
        )
        headers = "".join(f'<th scope="col">{escape(label)}</th>' for label in REPORT_HEADERS[8:])
        body = "".join(
            '<tr>' + "".join(f'<td>{escape(str(value))}</td>' for value in row[8:]) + '</tr>'
            for row in task_rows
        )
        sections.append(
            '<section class="report-task">'
            f'<h3>Task {escape(str(task_id))} - {escape(str(task[1]))}</h3>'
            f'<div class="report-metadata">{metadata}</div>'
            + (f'<p class="report-comment"><strong>Task comments:</strong> {escape(str(task[7]))}</p>' if task[7] else '')
            + '<div class="report-table-scroll">'
            f'<table aria-label="Task {escape(str(task_id))} claim reviews and notes">'
            f'<thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'
            '</div></section>'
        )
    return '<div class="task-reports">' + "".join(sections) + '</div>'


def load_report_html(user):
    if not user:
        return '<p class="qc-empty">Sign in to view reporting.</p>'
    return render_report(load_report(user))
