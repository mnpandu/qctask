"""Unread alert queries and Gradio callbacks."""

from html import escape

import gradio as gr
import oracledb

from . import database, errors, identity


def notifications_html(user=None):
    current_actor = identity.actor_id(identity.require_user(user))
    try:
        with database.connect_db() as conn:
            rows = conn.execute(
                """
                SELECT n.notification_id, n.task_id, COALESCE(n.claim_number, ''),
                       COALESCE(m.sender_racf, 'System'), n.notification_text, n.created_dts
                FROM qc_store.qctask_notifications n
                LEFT JOIN qc_store.qctask_claim_messages m ON m.message_id = n.message_id
                WHERE n.recipient_racf = :p1 AND n.read_dts IS NULL
                ORDER BY n.created_dts DESC, n.notification_id DESC
                FETCH FIRST 50 ROWS ONLY
            """,
                (current_actor,),
            ).fetchall()
    except oracledb.Error:
        raise errors.database_error() from None
    if not rows:
        return '<p class="qc-empty">No unread alerts.</p>'
    return (
        '<div class="qc-alerts">'
        + "".join(
            '<div class="qc-message"><strong>Task '
            + escape(str(task_id))
            + " / Claim "
            + escape(str(claim_id))
            + "</strong><small>From "
            + escape(str(sender))
            + " | "
            + escape(str(created))
            + "</small><p>"
            + escape(str(message))
            + "</p></div>"
            for _, task_id, claim_id, sender, message, created in rows
        )
        + "</div>"
    )


def notification_badge(user=None):
    if not user:
        return "Alerts (0)"
    identity.require_user(user)
    try:
        with database.connect_db() as conn:
            count = conn.execute(
                """
                SELECT count(*) FROM qc_store.qctask_notifications
                WHERE recipient_racf = :p1 AND read_dts IS NULL
            """,
                (identity.actor_id(user),),
            ).fetchone()[0]
    except oracledb.Error:
        raise errors.database_error() from None
    return gr.update(value=f"Alerts ({count})")


def open_alerts(user=None):
    identity.require_user(user)
    return gr.update(visible=True), notifications_html(user), notification_badge(user)


def close_alerts():
    return gr.update(visible=False)


def mark_notifications_read(user=None):
    identity.require_user(user)
    try:
        with database.connect_db() as conn:
            conn.execute(
                """
                UPDATE qc_store.qctask_notifications SET read_dts = CURRENT_TIMESTAMP
                WHERE recipient_racf = :p1 AND read_dts IS NULL
            """,
                (identity.actor_id(user),),
            )
    except oracledb.Error:
        raise errors.database_error() from None
    return notifications_html(user), notification_badge(user)
