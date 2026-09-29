"""Conversation persistence within caller-owned transactions."""

import claim_workflow as qc

from . import config, identity


def claim_note_reply_recipient(conn, task_id, claim_id, current_actor=None):
    last_message = conn.execute(
        """
        SELECT sender_racf, recipient_racf
        FROM pic_master.qc_claim_messages
        WHERE task_id = %s AND claim_number = %s
        ORDER BY created_dts DESC, message_id DESC
        LIMIT 1
    """,
        (task_id, claim_id),
    ).fetchone()
    if last_message is None:
        return current_actor or config.ACTOR_ID
    sender, recipient = last_message
    return recipient if sender == (current_actor or config.ACTOR_ID) else sender


def notification_recipients(recipient, assigned_racf):
    return list(
        dict.fromkeys(
            user.strip() for user in (recipient, assigned_racf or "") if user and user.strip()
        )
    )


def persist_claim_note(conn, task_id, claim_id, recipient, message, user=None):
    qc.lock_task(conn, task_id, config.CASE_ID)
    if claim_id not in {row[0] for row in qc.review_view(conn, task_id)[0]}:
        raise ValueError("This claim does not belong to the selected task.")
    task = conn.execute(
        """
        SELECT COALESCE(assigned_to, '') FROM pic_master.task
        WHERE task_id = %s AND case_id = %s
    """,
        (task_id, config.CASE_ID),
    ).fetchone()
    if task is None:
        raise ValueError("Select an active task first.")
    assigned_racf = task[0]
    message_id = conn.execute(
        """
        INSERT INTO pic_master.qc_claim_messages
            (task_id, claim_number, sender_racf, recipient_racf, assigned_racf, message_text)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING message_id
    """,
        (task_id, claim_id, identity.actor_id(user), recipient, assigned_racf or None, message),
    ).fetchone()[0]
    for user in notification_recipients(recipient, assigned_racf):
        conn.execute(
            """
        INSERT INTO pic_master.qc_notifications
            (message_id, task_id, claim_number, recipient_racf, notification_text)
        VALUES (%s, %s, %s, %s, %s)
    """,
            (message_id, task_id, claim_id, user, message),
        )
