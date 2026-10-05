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
    can_manage: bool = True


def build_completed_claims(canonical, bindings: TaskViewBindings):
    for item in presentation.completed_claims(canonical):
        claim_id = item["claimNumber"]
        review_details = item.get("qcReviewDetails", {})
        decision_choices, edit_decision_value, review_editable = qc.review_decision_options(
            item.get("qcReviewStatus"), review_details
        )
        with gr.Row(equal_height=True):
            with gr.Column(scale=5, min_width=0):
                claim_summary = gr.HTML(presentation.render_claim_review_summary(item))
            with gr.Column(scale=1, min_width=70):
                edit_claim = gr.Button(
                    "Edit" if bindings.can_manage else "Conversation and notes", size="sm"
                )
        with gr.Column(visible=False, elem_classes="qc-overlay") as edit_overlay:
            with gr.Column(elem_classes="qc-dialog"):
                gr.Markdown(f"### Claim {claim_id}")
                close_edit = gr.Button("Close", size="sm")
                gr.Markdown("#### Select Review Areas")
                gr.Markdown("Check each area that applies to this claim.")
                with gr.Row(elem_classes="qc-review-areas-row"):
                    edit_points = gr.Textbox(
                        value=review_details.get("points", ""),
                        label="Contract Points",
                        interactive=bindings.can_manage,
                        max_length=10,
                        lines=1,
                        scale=0,
                        min_width=0,
                        elem_classes="qc-review-points",
                    )
                    edit_nurse_points = gr.Textbox(
                        value=review_details.get("nursePoints", ""),
                        label="Nurse Points",
                        interactive=bindings.can_manage,
                        max_length=10,
                        lines=1,
                        scale=0,
                        min_width=0,
                        elem_classes="qc-review-points",
                    )
                    edit_areas = gr.CheckboxGroup(
                        choices=list(qc.QC_REVIEW_CATEGORIES),
                        value=[
                            area
                            for area in qc.QC_REVIEW_CATEGORIES
                            if presentation.review_area_checked(review_details, area)
                        ],
                        label="Review Areas",
                        interactive=bindings.can_manage,
                        scale=1,
                        min_width=0,
                        elem_classes="qc-area-group",
                    )
                with gr.Row():
                    edit_decision = gr.Dropdown(
                        choices=decision_choices,
                        value=edit_decision_value,
                        label="QC Review",
                        interactive=bindings.can_manage and review_editable,
                    )
                    edit_comment = gr.Dropdown(
                        label="QC Review Comment",
                        **{
                            **claims.qc_comment_options(
                                edit_decision_value, review_details.get("qcReviewComment")
                            ),
                            "interactive": bindings.can_manage
                            and review_editable
                            and edit_decision_value != "Agree",
                        },
                    )
                if bindings.can_manage:
                    edit_decision.change(
                        claims.update_qc_comment,
                        edit_decision,
                        edit_comment,
                        key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-79-change",
                    )
                edit_notice = gr.Markdown("")
                save_edit = gr.Button(
                    "Save Points and QC Review", variant="primary", visible=bindings.can_manage
                )
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
                        edit_nurse_points,
                    ],
                    [edit_notice, edit_overlay, claim_summary],
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-85-click",
                ).then(
                    tasks.refresh_task_heading,
                    bindings.task_id_state,
                    [bindings.summary, bindings.task_expansion],
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-85-then",
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
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-111-click",
                ).then(
                    notifications.notifications_html,
                    bindings.user_state,
                    bindings.notifications_panel,
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-111-then",
                ).then(
                    notifications.notification_badge,
                    bindings.user_state,
                    bindings.alert_button,
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-111-then",
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
                edit_nurse_points,
            ],
            key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-130-click",
        )
        close_edit.click(
            lambda: gr.update(visible=False),
            outputs=edit_overlay,
            key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-143-click",
        )


def build_review_panel(task_id: int, bindings: TaskViewBindings):
    with gr.Column(visible=False, elem_classes="qc-overlay") as work_panel:
        with gr.Column(elem_classes="qc-dialog"):
            gr.Markdown(f"### Review Claims ? Task {task_id}")
            close_popup = gr.Button("Close", size="sm")
            gr.Markdown(
                "Expand a claim to enter its QC review."
                if bindings.can_manage
                else "Expand a claim to view its details."
            )
            with database.connect_db() as conn:
                claim_rows, _ = qc.review_view(conn, task_id)
            gr.HTML(presentation.review_claim_header_html())
            claim_panels = []
            for claim_id, claim_status, review_details, data in claim_rows:
                with gr.Accordion(
                    presentation.review_claim_row_label(claim_id, data, claim_status),
                    open=False,
                    elem_classes=["task-entry", "claim-review-summary"],
                    key=f"claim-{task_id}-{claim_id}",
                ) as claim_panel:
                    claim_panels.append(claim_panel)
                    gr.HTML(
                        presentation.display_fields(
                            [(column, data.get(column, "")) for column in config.CLAIM_COLUMNS]
                        )
                    )
                    gr.HTML(presentation.claim_attachments_html(data))
                    gr.HTML(presentation.claim_decision_details_html(data))
                    gr.HTML('<div class="claim-detail-heading">QC Review</div>')
                    claim_id_state = gr.State(claim_id)
                    claim_data_state = gr.State(data)
                    decision_choices, saved_decision, review_editable = qc.review_decision_options(
                        claim_status, review_details
                    )
                    with gr.Row(elem_classes="qc-review-areas-row"):
                        points = gr.Textbox(
                            value=review_details.get("points", ""),
                            label="Contract Points",
                            interactive=bindings.can_manage,
                            max_length=10,
                            lines=1,
                            scale=0,
                            min_width=0,
                            elem_classes="qc-review-points",
                        )
                        nurse_points = gr.Textbox(
                            value=review_details.get("nursePoints", ""),
                            label="Nurse Points",
                            interactive=bindings.can_manage,
                            max_length=10,
                            lines=1,
                            scale=0,
                            min_width=0,
                            elem_classes="qc-review-points",
                        )
                        categories = gr.CheckboxGroup(
                            choices=list(qc.QC_REVIEW_CATEGORIES),
                            value=review_details.get("reviewCategories", []),
                            label="Review Areas",
                            interactive=bindings.can_manage,
                            scale=1,
                            min_width=0,
                        )
                    with gr.Row():
                        decision = gr.Dropdown(
                            choices=decision_choices,
                            value=saved_decision if saved_decision in qc.QC_DECISIONS else None,
                            label="QC Review",
                            interactive=bindings.can_manage and review_editable,
                        )
                        review_comment = gr.Dropdown(
                            label="QC Review Comment",
                            **{
                                **claims.qc_comment_options(
                                    saved_decision, review_details.get("qcReviewComment")
                                ),
                                "interactive": bindings.can_manage
                                and review_editable
                                and saved_decision != "Agree",
                            },
                        )
                    if bindings.can_manage:
                        decision.change(
                            claims.update_qc_comment,
                            decision,
                            review_comment,
                            key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-194-change",
                        )
                    save_claim = gr.Button(
                        "Save",
                        variant="primary",
                        interactive=bindings.can_manage and review_editable,
                        visible=bindings.can_manage,
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
                            points,
                            nurse_points,
                            claim_data_state,
                        ],
                        [claim_notice, claim_panel, save_claim],
                        key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-202-click",
                    ).then(
                        tasks.refresh_task_heading,
                        bindings.task_id_state,
                        [bindings.summary, bindings.task_expansion],
                        key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-202-then",
                    ).then(
                        tasks.refresh_task_view,
                        [bindings.user_state, bindings.task_view_revision],
                        [bindings.task_rows, bindings.task_view_revision],
                        key=f"task-{bindings.task_id_state.value}-claim-{claim_id}-event-202-then",
                    )
            for claim_index, panel in enumerate(claim_panels):
                panel.expand(
                    partial(claims.expand_claim_panels, claim_index, len(claim_panels)),
                    outputs=claim_panels,
                    queue=False,
                    key=f"task-{bindings.task_id_state.value}-claim-{claim_index}-event-223-expand",
                )
    close_popup.click(
        lambda: gr.update(visible=False),
        outputs=work_panel,
        key=f"task-{bindings.task_id_state.value}-claim--event-228-click",
    )
    return work_panel
