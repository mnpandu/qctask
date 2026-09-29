"""Sign-in and sign-out callbacks."""

import gradio as gr

from . import config, notifications, tasks


def login_user(username):
    user = config.USERS.get(username)
    if user is None:
        raise gr.Error("Choose a valid user name.")
    return (
        user,
        gr.update(visible=False),
        gr.update(value=f"Signed in as {user['name']}", visible=True),
        tasks.refresh_tasks(user),
        notifications.notification_badge(user),
    )


def logout_user():
    return (
        None,
        gr.update(visible=True),
        gr.update(value="", visible=True),
        [],
        "Alerts (0)",
    )
