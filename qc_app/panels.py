"""Claim editor and review panel components, composed inside a task view."""

from dataclasses import dataclass
from functools import partial

import gradio as gr

import claim_workflow as qc

from . import claims, config, database, messaging, notifications, presentation, tasks


@dataclass(frozen=True)
class TaskViewBindings:
    """Components shared by a task's panels and event chains."""

    task_id_state: gr.State
    user_state: gr.State
    task_rows: gr.State
    task_view_revision: gr.State
    summary: gr.HTML
    task_expansion: gr.Accordion
    notifications_panel: gr.HTML
    alert_button: gr.Button


def build_completed_claims(canonical, bindings: TaskViewBindings):
    for item in presentation.completed_claims(canonical):
        claim_id = item["claimNumber"]
        review_details = item.get("qcReviewDetails", {})
        saved_decision = review_details["qcReview"]
        edit_decision_value = (
            "Action Required" if saved_decision == "Returned for Corrections" else saved_decision
        )
        with gr.Row(equal_height=True):
            with gr.Column(scale=5, min_width=0):
                claim_summary = gr.HTML(presentation.render_claim_review_summary(item))
            with gr.Column(scale=1, min_width=70):
                edit_claim = gr.Button("Edit", size="sm")
        with gr.Column(visible=False, elem_classes="qc-overlay") as edit_overlay:
            with gr.Column(elem_classes="qc-dialog"):
                gr.Markdown(f"### Claim {claim_id}")
                close_edit = gr.Button("Close", size="sm")
                gr.Markdown("#### Select Review Areas")
                gr.Markdown("Check each area that applies to this claim.")
                edit_areas = gr.CheckboxGroup(
                    choices=list(qc.QC_REVIEW_CATEGORIES),
                    value=[
                        area
                        for area in qc.QC_REVIEW_CATEGORIES
                        if presentation.review_area_checked(review_details, area)
                    ],
                    label="Review Areas",
                    show_label=False,
                    interactive=True,
                    elem_classes="qc-area-group",
                )
                edit_points = gr.Textbox(
                    value=review_details.get("points", ""),
                    label="Points",
                    max_length=100,
                )
                with gr.Row():
                    edit_decision = gr.Dropdown(
                        choices=list(qc.QC_DECISIONS),
                        value=edit_decision_value,
                        label="QC Review",
                    )
                    edit_comment = gr.Dropdown(
                        label="QC Review Comment",
                        **claims.qc_comment_options(
                            edit_decision_value, review_details.get("qcReviewComment")
                        ),
                    )
                edit_decision.change(
                    claims.update_qc_comment, edit_decision, edit_comment
                )
                edit_notice = gr.Markdown("")
                save_edit = gr.Button("Save Points and QC Review", variant="primary")
                edit_claim_id_state = gr.State(claim_id)
                save_edit.click(
                    claims.save_claim_edit_group,
                    [
                        bindings.task_id_state,
                        edit_claim_id_state,
                        edit_areas,
                        edit_points,
                        edit_decision,
                        edit_comment,
                        bindings.user_state,
                    ],
                    [edit_notice, edit_overlay, claim_summary],
                ).then(
                    tasks.refresh_task_heading,
                    bindings.task_id_state,
                    [bindings.summary, bindings.task_expansion],
                )
                gr.Markdown("#### Conversation and notes")
                conversation = gr.HTML('<p class="qc-empty">Open this editor to load notes.</p>')
                recipient = gr.Textbox(
                    label="Send note to RACF/user name (optional; blank sends to yourself)",
                    max_length=100,
                )
                note_text = gr.Textbox(label="Note", lines=3, max_length=4000)
                send_note = gr.Button("Send Note", variant="primary")
                note_notice = gr.Markdown("")
                send_note.click(
                    messaging.send_claim_note_form,
                    [
                        bindings.task_id_state,
                        edit_claim_id_state,
                        recipient,
                        note_text,
                        bindings.user_state,
                    ],
                    [note_notice, conversation, note_text],
                ).then(
                    notifications.notifications_html,
                    bindings.user_state,
                    bindings.notifications_panel,
                ).then(
                    notifications.notification_badge,
                    bindings.user_state,
                    bindings.alert_button,
                )
        edit_claim.click(
            claims.open_claim_editor_group,
            [bindings.task_id_state, edit_claim_id_state, bindings.user_state],
            [
                edit_overlay,
                conversation,
                recipient,
                edit_areas,
                edit_points,
                edit_decision,
                edit_comment,
            ],
        )
        close_edit.click(lambda: gr.update(visible=False), outputs=edit_overlay)


def build_review_panel(task_id: int, bindings: TaskViewBindings):
    with gr.Column(visible=False, elem_classes="qc-overlay") as work_panel:
        with gr.Column(elem_classes="qc-dialog"):
            gr.Markdown(f"### Review Claims ? Task {task_id}")
            close_popup = gr.Button("Close", size="sm")
            gr.Markdown("Expand a claim to enter its QC review.")
            with database.connect_db() as conn:
                claim_rows, _ = qc.review_view(conn, task_id)
            claim_panels = []
            for claim_id, claim_status, review_details, data in claim_rows:
                with gr.Accordion(
                    f"{claim_id}    |    QC Review: {claim_status}",
                    open=False,
                    elem_classes="task-entry",
                    key=f"claim-{task_id}-{claim_id}",
                ) as claim_panel:
                    claim_panels.append(claim_panel)
                    gr.HTML(
                        presentation.display_fields(
                            [(column, data.get(column, "")) for column in config.CLAIM_COLUMNS]
                        )
                    )
                    claim_id_state = gr.State(claim_id)
                    saved_decision = (
                        "Action Required"
                        if claim_status == "Returned for Corrections"
                        else claim_status
                    )
                    categories = gr.CheckboxGroup(
                        choices=list(qc.QC_REVIEW_CATEGORIES),
                        value=review_details.get("reviewCategories", []),
                        label="Review Areas",
                    )
                    with gr.Row():
                        decision = gr.Dropdown(
                            choices=list(qc.QC_DECISIONS),
                            value=saved_decision if saved_decision in qc.QC_DECISIONS else None,
                            label="QC Review",
                            interactive=True,
                        )
                        review_comment = gr.Dropdown(
                            label="QC Review Comment",
                            **claims.qc_comment_options(
                                saved_decision, review_details.get("qcReviewComment")
                            ),
                        )
                    decision.change(claims.update_qc_comment, decision, review_comment)
                    save_claim = gr.Button(
                        "Save",
                        variant="primary",
                        interactive=claim_status not in qc.REVIEWED_STATUSES,
                    )
                    claim_notice = gr.Markdown("")
                    save_claim.click(
                        claims.save_claim_form,
                        [
                            bindings.task_id_state,
                            claim_id_state,
                            categories,
                            decision,
                            review_comment,
                            bindings.user_state,
                        ],
                        [claim_notice, claim_panel, save_claim],
                    ).then(
                        tasks.refresh_task_heading,
                        bindings.task_id_state,
                        [bindings.summary, bindings.task_expansion],
                    ).then(
                        tasks.refresh_task_view,
                        [bindings.user_state, bindings.task_view_revision],
                        [bindings.task_rows, bindings.task_view_revision],
                    )
            for claim_index, panel in enumerate(claim_panels):
                panel.expand(
                    partial(claims.expand_claim_panels, claim_index, len(claim_panels)),
                    outputs=claim_panels,
                    queue=False,
                )
    close_popup.click(lambda: gr.update(visible=False), outputs=work_panel)
    return work_panel
