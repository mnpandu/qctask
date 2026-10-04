"""Task mutations within caller-owned transactions."""

from qc_app.database import JsonDocument

import claim_workflow as qc

from . import config, identity


def persist_task(conn, task_name, claim_ids, comments, user=None):
    if task_name not in config.TASK_TYPES:
        raise ValueError("Select a valid review type.")
    # Serialize eligibility checks and reservations for this case.
    conn.lock_case(config.CASE_ID)
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
        INSERT INTO qc_store.qctask_task
            (task_name, task_status, status, case_id, task_comment,
             task_queue_name, created_by, created_by_name)
        VALUES (:p1, 'Not Started', 'Active', :p2, :p3, 'QC Nurse', :p4, :p5)
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
        INSERT INTO qc_store.qctask_task_details (task_id, task_canonical, status, created_by)
        VALUES (:p1, :p2, 'Active', :p3)
    """,
        (task_id, JsonDocument(details), identity.actor_id(user)),
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
        UPDATE qc_store.qctask_task SET assigned_to_name = :p1, task_comment = :p2,
        updated_by = :p3, updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p4
    """,
        (assigned_to or None, comments or "", identity.actor_id(user), task_id),
    )
    return conn.execute(
        "SELECT task_canonical FROM qc_store.qctask_task_details WHERE task_id = :p1",
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
            "SELECT assigned_to FROM qc_store.qctask_task WHERE task_id = :p1",
            (task_id,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE qc_store.qctask_task SET assigned_to = :p1, assigned_to_name = :p2,
            task_status = 'In Progress', task_cmpled_dts = NULL,
            updated_by = :p3, updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p4
        """,
            (recipient, identity.actor_name(user), recipient, task_id),
        )
        if previous != recipient:
            conn.execute(
                """
                INSERT INTO qc_store.qctask_notifications
                    (task_id, recipient_racf, notification_text)
                VALUES (:p1, :p2, :p3)
            """,
                (task_id, recipient, f"Task {task_id} was assigned to you."),
            )
    elif action == "delete":
        for claim_id, _, _, _ in qc.review_view(conn, task_id)[0]:
            conn.execute("UPDATE qc_store.qctask_claim_details SET qc_status = 'Released', updated_dts = CURRENT_TIMESTAMP WHERE case_id = :p1 AND claim_number = :p2", (config.CASE_ID, claim_id))
        conn.execute("DELETE FROM qc_store.qctask_task_details WHERE task_id = :p1", (task_id,))
        conn.execute("DELETE FROM qc_store.qctask_task WHERE task_id = :p1", (task_id,))
    elif action == "finish":
        for claim_id, claim_status, _, _ in qc.review_view(conn, task_id)[0]:
            if claim_status == "Created":
                conn.execute("UPDATE qc_store.qctask_claim_details SET qc_status = 'Released', updated_dts = CURRENT_TIMESTAMP WHERE case_id = :p1 AND claim_number = :p2", (config.CASE_ID, claim_id))
        qc.sync_canonical(conn, task_id, identity.actor_id(user))
        conn.execute(
            """
            UPDATE qc_store.qctask_task SET task_status = 'Completed',
            task_cmpled_dts = COALESCE(task_cmpled_dts, CURRENT_TIMESTAMP),
            updated_by = :p1, updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p2
        """,
            (identity.actor_id(user), task_id),
        )
    else:
        raise ValueError("Unknown task action.")
    return True
