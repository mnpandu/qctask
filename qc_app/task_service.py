"""Task mutations within caller-owned transactions."""

from psycopg.types.json import Jsonb

import claim_workflow as qc

from . import config, identity


def persist_task(conn, task_name, claim_ids, comments, user=None):
    if task_name not in config.TASK_TYPES:
        raise ValueError("Select a valid review type.")
    # Serialize eligibility checks and reservations for this case.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (config.CASE_ID,))
    available = {claim_id: data for claim_id, data in qc.eligible_claims(conn, config.CASE_ID)}
    selected = (
        list(available)
        if task_name == config.TASK_TYPES[0]
        else list(dict.fromkeys(claim_ids or []))
    )
    if not selected:
        raise ValueError(
            "No eligible claims selected. Refresh the review type to check available claims."
        )
    if not set(selected).issubset(available):
        raise ValueError("Some claims are no longer eligible. Select the review type again.")
    if len(comments or "") > 4000:
        raise ValueError("Comments must be 4,000 characters or fewer.")
    task_id = conn.execute(
        """
        INSERT INTO pic_master.task
            (task_name, task_status, status, case_id, task_comment,
             task_queue_name, created_by, created_by_name)
        VALUES (%s, 'Not Started', 'Active', %s, %s, 'QC Nurse', %s, %s)
        RETURNING task_id
    """,
        (
            task_name,
            config.CASE_ID,
            comments or "",
            identity.actor_id(user),
            identity.actor_name(user),
        ),
    ).fetchone()[0]
    details = {"claimsForReviews": [{"claimNumber": claim_id} for claim_id in selected]}
    conn.execute(
        """
        INSERT INTO pic_master.task_details (task_id, task_canonical, status, created_by)
        VALUES (%s, %s, 'Active', %s)
    """,
        (task_id, Jsonb(details), identity.actor_id(user)),
    )
    qc.add_reviews(conn, task_id, config.CASE_ID, selected)
    qc.sync_canonical(conn, task_id, identity.actor_id(user))
    return task_id


def persist_update(conn, task_id, status, assigned_to, comments, claim_ids=None, user=None):
    if len(assigned_to or "") > 100 or len(comments or "") > 4000:
        raise ValueError("Assignee name must be at most 100 characters; comments at most 4,000.")
    qc.lock_task(conn, task_id, config.CASE_ID)
    # Workflow status and claim membership are controlled by the review queue.
    conn.execute(
        """
        UPDATE pic_master.task SET assigned_to_name = %s, task_comment = %s,
        updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
    """,
        (assigned_to or None, comments or "", identity.actor_id(user), task_id),
    )
    return conn.execute(
        "SELECT task_canonical FROM pic_master.task_details WHERE task_id = %s",
        (task_id,),
    ).fetchone()[0]


def task_action(conn, task_id, action, user=None):
    status = qc.lock_task(conn, task_id, config.CASE_ID)
    if status == "Completed" and action in ("assign", "finish"):
        # A repeated click or stale browser view must not reopen or rewrite the task.
        return False
    if action == "assign":
        recipient = identity.actor_id(user)
        previous = conn.execute(
            "SELECT assigned_to FROM pic_master.task WHERE task_id = %s",
            (task_id,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE pic_master.task SET assigned_to = %s, assigned_to_name = %s,
            task_status = 'In Progress', task_cmpled_dts = NULL,
            updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
        """,
            (recipient, identity.actor_name(user), recipient, task_id),
        )
        if previous != recipient:
            conn.execute(
                """
                INSERT INTO pic_master.qc_notifications
                    (task_id, recipient_racf, notification_text)
                VALUES (%s, %s, %s)
            """,
                (task_id, recipient, f"Task {task_id} was assigned to you."),
            )
    elif action == "delete":
        conn.execute(
            """
            UPDATE pic_master.claim_details c SET qc_status = 'Released',
                updated_dts = CURRENT_TIMESTAMP
            WHERE c.case_id = %s AND c.claim_number IN (
                SELECT j->>'claimNumber' FROM pic_master.task_details d,
                LATERAL jsonb_array_elements(d.task_canonical->'claimsForReviews') j
                WHERE d.task_id = %s)
        """,
            (config.CASE_ID, task_id),
        )
        conn.execute("DELETE FROM pic_master.task_details WHERE task_id = %s", (task_id,))
        conn.execute("DELETE FROM pic_master.task WHERE task_id = %s", (task_id,))
    elif action == "finish":
        conn.execute(
            """
            UPDATE pic_master.claim_details c SET qc_status = 'Released',
                updated_dts = CURRENT_TIMESTAMP
            WHERE c.case_id = %s AND c.qc_status = 'Created'
              AND c.claim_number IN (
                SELECT j->>'claimNumber'
                FROM pic_master.task t
                JOIN pic_master.task_details d ON d.task_id = t.task_id,
                LATERAL jsonb_array_elements(d.task_canonical->'claimsForReviews') j
                WHERE t.task_id = %s AND t.task_status <> 'Completed')
        """,
            (config.CASE_ID, task_id),
        )
        qc.sync_canonical(conn, task_id, identity.actor_id(user))
        conn.execute(
            """
            UPDATE pic_master.task SET task_status = 'Completed',
            task_cmpled_dts = COALESCE(task_cmpled_dts, CURRENT_TIMESTAMP),
            updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
        """,
            (identity.actor_id(user), task_id),
        )
    else:
        raise ValueError("Unknown task action.")
    return True
