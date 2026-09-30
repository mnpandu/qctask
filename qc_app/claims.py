"""Gradio claim review and editor callbacks."""

import gradio as gr
import psycopg

import claim_workflow as qc

from . import (
    config,
    database,
    errors,
    identity,
    messaging,
    messaging_service,
    presentation,
    repository,
)


def expand_claim_panels(selected, count):
    updates = [gr.update(open=index == selected) for index in range(count)]
    # Gradio wraps single-output results itself, including layout updates.
    return updates[0] if count == 1 else updates


def qc_comment_options(decision, saved=None):
    if decision == "Agree":
        return dict(choices=["Completed"], value="Completed", interactive=False)
    if decision in qc.QC_COMMENT_OPTIONS:
        saved = qc.LEGACY_QC_COMMENTS.get(saved, saved)
        choices = list(qc.QC_COMMENT_OPTIONS[decision])
        return dict(choices=choices, value=saved if saved in choices else None, interactive=True)
    return dict(choices=[], value=None, interactive=False)


def update_qc_comment(decision):
    return gr.update(**qc_comment_options(decision))


def save_claim_form(task_id, claim_id, categories, decision, comment, user=None):
    identity.require_qc_nurse(user)
    try:
        with database.connect_db() as conn:
            qc.save_claim_decision(
                conn,
                task_id,
                config.CASE_ID,
                claim_id,
                decision,
                comment,
                identity.actor_id(user),
                categories,
            )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    return (
        f"Claim {claim_id} saved: {decision}.",
        gr.update(label=f"{claim_id}    |    QC Review: {decision}"),
        gr.update(interactive=False),
    )


def save_claim_edit_form(
    task_id,
    claim_id,
    clinical_determination,
    generic_reason_code,
    coding,
    decision_remarks,
    other,
    points,
    decision,
    comment,
    user=None,
):
    identity.require_qc_nurse(user)
    categories = [
        name
        for name, checked in zip(
            qc.QC_REVIEW_CATEGORIES,
            (
                clinical_determination,
                generic_reason_code,
                coding,
                decision_remarks,
                other,
            ),
        )
        if checked
    ]
    try:
        with database.connect_db() as conn:
            qc.save_claim_decision(
                conn,
                task_id,
                config.CASE_ID,
                claim_id,
                decision,
                comment,
                identity.actor_id(user),
                categories,
                points,
            )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    except psycopg.Error:
        raise errors.database_error() from None
    return (
        f"QC review updated for {claim_id}.",
        gr.update(visible=False),
        claim_review_summary_html(task_id, claim_id),
    )


def claim_review_summary_html(task_id, claim_id):
    metadata = repository.task_metadata(task_id)
    if metadata is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    item = next(
        (
            claim
            for claim in metadata[3].get("claimsForReviews", [])
            if claim.get("claimNumber") == claim_id
        ),
        None,
    )
    if item is None:
        raise gr.Error("This claim is no longer part of the selected task.")
    return presentation.render_claim_review_summary(item)


def open_claim_editor(task_id, claim_id, user=None):
    identity.require_user(user)
    metadata = repository.task_metadata(task_id)
    if metadata is None:
        raise gr.Error("Task no longer exists. Refresh the task list.")
    item = next(
        (
            claim
            for claim in metadata[3].get("claimsForReviews", [])
            if claim.get("claimNumber") == claim_id
        ),
        None,
    )
    if item is None:
        raise gr.Error("This claim is no longer part of the selected task.")
    details = item.get("qcReviewDetails", {})
    try:
        with database.connect_db() as conn:
            recipient = messaging_service.claim_note_reply_recipient(
                conn, task_id, claim_id, identity.actor_id(user)
            )
    except psycopg.Error:
        raise errors.database_error() from None
    return (
        gr.update(visible=True),
        messaging.claim_conversation_html(task_id, claim_id),
        gr.update(value=recipient),
        gr.update(value=presentation.review_area_checked(details, "Clinical Determination")),
        gr.update(value=presentation.review_area_checked(details, "Generic Reason Code")),
        gr.update(value=presentation.review_area_checked(details, "Coding")),
        gr.update(value=presentation.review_area_checked(details, "Decision Remarks")),
        gr.update(value=presentation.review_area_checked(details, "Other")),
        gr.update(value=details.get("points", "")),
        gr.update(
            value=(
                "Action Required"
                if details.get("qcReview") == "Returned for Corrections"
                else details.get("qcReview")
            )
        ),
        gr.update(
            **{**qc_comment_options(
                "Action Required"
                if details.get("qcReview") == "Returned for Corrections"
                else details.get("qcReview"),
                details.get("qcReviewComment"),
            ), "interactive": identity.can_manage(user) and details.get("qcReview") != "Agree"}
        ),
    )


def open_claim_editor_group(task_id, claim_id, user=None):
    values = open_claim_editor(task_id, claim_id, user)
    selected = [
        area for area, update in zip(qc.QC_REVIEW_CATEGORIES, values[3:8]) if update["value"]
    ]
    return (*values[:3], gr.update(value=selected, visible=True), *values[8:])


def save_claim_edit_group(task_id, claim_id, areas, points, decision, comment, user=None):
    checked = [area in (areas or []) for area in qc.QC_REVIEW_CATEGORIES]
    return save_claim_edit_form(task_id, claim_id, *checked, points, decision, comment, user)
