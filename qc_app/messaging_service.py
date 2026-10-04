"""Conversation persistence within caller-owned transactions."""

import claim_workflow as qc

from . import config, identity


def claim_note_reply_recipient(conn, task_id, claim_id, current_actor=None):
    last_message = conn.execute(
        """
        SELECT sender_racf, recipient_racf
        FROM qc_store.qctask_claim_messages
        WHERE task_id = :p1 AND claim_number = :p2
        ORDER BY created_dts DESC, message_id DESC
        FETCH FIRST 1 ROWS ONLY
    """,
        (task_id, claim_id),
    ).fetchone()
    if last_message is None:
        return current_actor or config.ACTOR_ID
    sender, recipient = last_message
    return recipient if sender == (current_actor or config.ACTOR_ID) else sender


def notification_recipients(recipient):
    return [recipient.strip()] if recipient and recipient.strip() else []


def persist_claim_note(conn, task_id, claim_id, recipient, message, user=None):
    qc.lock_task(conn, task_id, config.CASE_ID)
    if claim_id not in {row[0] for row in qc.review_view(conn, task_id)[0]}:
        raise ValueError("This claim does not belong to the selected task.")
    task = conn.execute(
        """
        SELECT COALESCE(assigned_to, '') FROM qc_store.qctask_task
        WHERE task_id = :p1 AND case_id = :p2
    """,
        (task_id, config.CASE_ID),
    ).fetchone()
    if task is None:
        raise ValueError("Select an active task first.")
    assigned_racf = task[0]
    message_id = conn.execute(
        """
        INSERT INTO qc_store.qctask_claim_messages
            (task_id, claim_number, sender_racf, recipient_racf, assigned_racf, message_text)
        VALUES (:p1, :p2, :p3, :p4, :p5, :p6)
        RETURNING message_id
    """,
        (task_id, claim_id, identity.actor_id(user), recipient, assigned_racf or None, message),
    ).fetchone()[0]
    for user in notification_recipients(recipient):
        conn.execute(
            """
        INSERT INTO qc_store.qctask_notifications
            (message_id, task_id, claim_number, recipient_racf, notification_text)
        VALUES (:p1, :p2, :p3, :p4, :p5)
    """,
            (message_id, task_id, claim_id, user, message),
        )
