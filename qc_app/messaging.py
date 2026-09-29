"""Conversation rendering and Gradio note callbacks."""

from html import escape

import gradio as gr
import psycopg

from . import database, errors, identity, messaging_service


def claim_conversation_html(task_id, claim_id):
    try:
        with database.connect_db() as conn:
            rows = conn.execute(
                """
                SELECT sender_racf, recipient_racf, message_text, created_dts
                FROM pic_master.qc_claim_messages
                WHERE task_id = %s AND claim_number = %s
                ORDER BY created_dts, message_id
            """,
                (task_id, claim_id),
            ).fetchall()
    except psycopg.Error:
        raise errors.database_error() from None
    if not rows:
        return '<p class="qc-empty">No notes in this conversation yet.</p>'
    return (
        '<div class="qc-conversation">'
        + "".join(
            '<div class="qc-message"><strong>'
            + escape(str(sender))
            + " to "
            + escape(str(recipient))
            + "</strong><small>"
            + escape(str(created))
            + "</small><p>"
            + escape(str(message))
            + "</p></div>"
            for sender, recipient, message, created in rows
        )
        + "</div>"
    )


def send_claim_note_form(task_id, claim_id, recipient, message, user=None):
    identity.require_user(user)
    recipient = (recipient or "").strip()
    message = (message or "").strip()
    recipient = recipient or identity.actor_id(user)
    if len(recipient) > 100:
        raise gr.Error("RACF/user name must be 100 characters or fewer.")
    if not message or len(message) > 4000:
        raise gr.Error("Enter a note of 1 to 4,000 characters.")
    try:
        with database.connect_db() as conn:
            messaging_service.persist_claim_note(conn, task_id, claim_id, recipient, message, user)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    return (
        f"Note sent to {recipient}; the assigned nurse was alerted when assigned.",
        claim_conversation_html(task_id, claim_id),
        gr.update(value=""),
    )
