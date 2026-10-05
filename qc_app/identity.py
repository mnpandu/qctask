"""Session identity validation and audit labels."""

import gradio as gr

from . import config


def actor_id(user=None):
    return user["id"] if user else config.ACTOR_ID


def actor_name(user=None):
    return user["name"] if user else config.ACTOR_NAME


def require_user(user):
    if not user or config.USERS.get(user.get("id")) != user:
        raise gr.Error("Sign in as Pandu or Regine to continue.")
    return user


def can_manage(user):
    return bool(user and config.USERS.get(user.get("id")) == user and user.get("role") in ("Nurse", "QC Nurse"))


def require_manage(user):
    require_user(user)
    if not can_manage(user):
        raise gr.Error("Only nurses and QC nurses can change tasks or QC reviews.")
    return user
