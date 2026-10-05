"""Gradio task callbacks and transaction boundaries."""

import gradio as gr
import psycopg

import claim_workflow as qc

from . import config, database, errors, identity, presentation, repository, task_service


def refresh_tasks(user=None):
    if user is not None:
        identity.require_user(user)
    try:
        with database.connect_db() as conn:
            return repository.list_tasks(conn)
    except psycopg.Error:
        raise errors.database_error() from None


def refresh_task_view(user, revision):
    return refresh_tasks(user), revision + 1


def prepare_review(task_name):
    if task_name not in config.TASK_TYPES:
        return gr.update(visible=False), [], gr.update(choices=[], value=[]), ""
    try:
        with database.connect_db() as conn:
            available = qc.eligible_claims(conn, config.CASE_ID)
    except psycopg.Error:
        raise errors.database_error() from None
    claims = [
        [str(claim.get(column, "")) for column in config.CLAIM_COLUMNS] for _, claim in available
    ]
    ids = [claim_id for claim_id, _ in available]
    return (
        gr.update(visible=True),
        claims,
        gr.update(
            choices=ids,
            value=ids,
            interactive=task_name != config.TASK_TYPES[0],
        ),
        "",
    )


def create_task(task_name, claim_ids, comments, user=None):
    identity.require_manage(user)
    try:
        with database.connect_db() as conn:
            task_id = task_service.persist_task(conn, task_name, claim_ids, comments, user)
            rows = repository.list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    return (
        rows,
        gr.update(visible=False),
        gr.update(value=None),
        f"Task {task_id} created. Status: Not Started.",
    )


def cancel_review():
    return gr.update(visible=False), gr.update(value=None), "Task creation cancelled."


def open_task(table, evt: gr.SelectData):
    task_id = int(table[evt.index[0]][0])
    try:
        with database.connect_db() as conn:
            row = conn.execute(
                "SELECT t.task_status, COALESCE(t.assigned_to_name, ''), "
                "COALESCE(t.task_comment, ''), d.task_canonical "
                "FROM pic_master.task t JOIN pic_master.task_details d ON d.task_id = t.task_id "
                "WHERE t.task_id = %s AND t.case_id = %s AND t.status = 'Active'",
                (task_id, config.CASE_ID),
            ).fetchone()
    except psycopg.Error:
        raise errors.database_error() from None
    if row is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    return (
        task_id,
        gr.update(visible=True),
        row[0],
        row[1],
        row[2],
        row[3],
        gr.update(
            choices=[c["claimNumber"] for c in row[3]["claimsForReviews"]],
            value=[c["claimNumber"] for c in row[3]["claimsForReviews"]],
        ),
    )


def save_details(task_id, status, assigned_to, comments, claim_ids, user=None):
    identity.require_manage(user)
    if task_id is None:
        raise gr.Error("Select a task first.")
    try:
        with database.connect_db() as conn:
            details = task_service.persist_update(
                conn, task_id, status, assigned_to, comments, claim_ids, user
            )
            rows = repository.list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    return rows, details, f"Task {task_id} updated."


def review_outputs(conn, task_id):
    rows, current = qc.review_view(conn, task_id)
    status, canonical = conn.execute(
        "SELECT t.task_status, d.task_canonical FROM pic_master.task t "
        "JOIN pic_master.task_details d ON d.task_id = t.task_id WHERE t.task_id = %s",
        (task_id,),
    ).fetchone()
    queue = [[r[0], r[1], r[2].get("outcome", ""), r[2].get("notes", "")] for r in rows]
    pending = any(r[1] == "Created" for r in rows)
    return (
        repository.list_tasks(conn),
        status,
        canonical,
        queue,
        current[0] if current else None,
        current[3] if current else {},
        current[2].get("outcome", "") if current else "",
        current[2].get("notes", "") if current else "",
        gr.update(interactive=pending and current is None and status != "Completed"),
        gr.update(interactive=current is not None),
        gr.update(interactive=current is not None),
    )


def run_review(action, task_id, claim_id=None, outcome="", notes="", user=None):
    identity.require_manage(user)
    if task_id is None:
        raise gr.Error("Select a task first.")
    try:
        with database.connect_db() as conn:
            qc.lock_task(conn, task_id, config.CASE_ID)
            if action == "start":
                qc.start_next(conn, task_id, config.CASE_ID, identity.actor_id(user))
            elif action in ("draft", "complete"):
                qc.save_review(
                    conn,
                    task_id,
                    config.CASE_ID,
                    claim_id,
                    outcome,
                    notes,
                    action == "complete",
                    identity.actor_id(user),
                )
            return review_outputs(conn, task_id)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None


def perform_task_action(task_id, action, user=None):
    identity.require_manage(user)
    try:
        with database.connect_db() as conn:
            changed = task_service.task_action(conn, task_id, action, user)
            rows = repository.list_tasks(conn)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    if changed is False:
        return rows, "This task is already completed. The task view has been refreshed."
    messages = {
        "assign": "Task assigned to you.",
        "delete": "Task deleted.",
        "finish": "Task completed.",
    }
    return rows, messages[action]


def perform_task_action_and_refresh_view(task_id, action, user, revision):
    rows, message = perform_task_action(task_id, action, user)
    return rows, message, revision + 1


def refresh_task_heading(task_id):
    with database.connect_db() as conn:
        row = next(r for r in repository.list_tasks(conn) if r[0] == task_id)
    assigned_id, creator_id, creator_name, _ = repository.task_metadata(task_id)
    label = presentation.task_row_label(row)
    fields = [
        ("Task ID", task_id),
        ("Task Name", row[1]),
        ("Task Status", row[2]),
        ("Created Date", row[4]),
        ("Assigned to RACF", assigned_id),
        ("Assigned to Name", row[3]),
        ("Created by RACF", creator_id),
        ("Created by Name", creator_name),
    ]
    return presentation.display_fields(fields), gr.update(label=label)
