"""Build the Gradio interface explicitly, without import-time side effects."""

from pathlib import Path

import gradio as gr

import claim_workflow as qc

from . import (
    config,
    notifications,
    panels,
    presentation,
    repository,
    session,
    tasks,
)


def read_asset(name: str) -> str:
    return (Path(__file__).with_name("assets") / name).read_text(encoding="utf-8")


def create_app() -> gr.Blocks:
    """Create an independent interface; callers own initialization and launch."""
    with gr.Blocks(
        title="Tasks",
        theme=gr.themes.Soft(primary_hue="blue"),
        css=read_asset("styles.css"),
        js=read_asset("task_rows.js"),
        analytics_enabled=False,
    ) as demo:
        # Load this component's frontend before it is used inside dynamic task popups.
        gr.CheckboxGroup(choices=list(qc.QC_REVIEW_CATEGORIES), elem_classes="qc-component-loader")
        task_rows = gr.State([])
        user_state = gr.State(None)
        with gr.Column(elem_classes="qc-login-overlay") as login_panel:
            with gr.Column(elem_classes="qc-login-card"):
                gr.Markdown("## Sign in")
                gr.Markdown("Choose your user name to open the QC workspace.")
                login_choice = gr.Dropdown(
                    choices=[("Pandu (QC Nurse)", "pandu"), ("Regine (Nurse)", "regine")],
                    label="User name",
                    value=None,
                    filterable=False,
                )
                login_button = gr.Button("Sign in", variant="primary")
        user_banner = gr.Markdown("", elem_classes="qc-user-name")
        with gr.Row(elem_classes="qc-user-bar"):
            alert_button = gr.Button("Alerts (0)", size="sm")
            logout_button = gr.Button("Sign out", size="sm")
        with gr.Column(visible=False, elem_classes="qc-alert-popup") as alert_popup:
            notifications_panel = gr.HTML('<p class="qc-empty">No unread alerts.</p>')
            with gr.Row():
                mark_alerts_read = gr.Button("Mark Read", size="sm")
                close_alert_button = gr.Button("Close", size="sm")
        alert_timer = gr.Timer(15)
        task_view_revision = gr.State(0)
        with gr.Tab("Tasks"):
            with gr.Row():
                gr.Markdown("## Tasks")
                task_dropdown = gr.Dropdown(
                    choices=config.TASK_TYPES, value=None, label="Create Task", filterable=False
                )
            notice = gr.Markdown("")
            with gr.Column(visible=False) as review_panel:
                claims_table = gr.Dataframe(
                    value=[], headers=config.CLAIM_COLUMNS, interactive=False, type="array"
                )
                selected_claims = gr.Dropdown(
                    choices=[], value=[], multiselect=True, label="Claims to include"
                )
                comments = gr.Textbox(label="Comments", lines=3)
                with gr.Row():
                    cancel_button = gr.Button("Cancel")
                    create_button = gr.Button("Create", variant="primary", interactive=False)
            selected_claims.change(
                lambda ids: gr.update(interactive=bool(ids)),
                selected_claims,
                create_button,
                queue=False,
            )
            task_dropdown.input(
                tasks.prepare_review,
                task_dropdown,
                [review_panel, claims_table, selected_claims, comments],
            )
            create_button.click(
                tasks.create_task,
                [task_dropdown, selected_claims, comments, user_state],
                [task_rows, review_panel, task_dropdown, notice],
            )
            cancel_button.click(tasks.cancel_review, outputs=[review_panel, task_dropdown, notice])
            gr.HTML(
                '<div class="task-header"><span>TASK ID</span><span>TASK NAME</span><span>CASE NUMBER</span><span>STATUS</span><span>ASSIGNED TO</span><span>CREATED ON</span><span>COMPLETED ON</span></div>'
            )

            @gr.render(inputs=[task_rows, user_state, task_view_revision])
            def render_tasks(rows, user, _revision):
                if not user:
                    gr.Markdown("Sign in to view tasks.")
                    return
                if not rows:
                    gr.Markdown("No tasks to display.")
                for index, row in enumerate(rows):
                    task_id = row[0]
                    metadata = repository.task_metadata(task_id)
                    if metadata is None:
                        continue
                    assigned_id, creator_id, creator_name, canonical = metadata
                    label = presentation.task_row_label(row)
                    with gr.Accordion(
                        label,
                        open=index == 0,
                        elem_classes=["task-entry", "task-summary"],
                        key=f"task-{task_id}",
                    ) as task_expansion:
                        task_id_state = gr.State(task_id)
                        with gr.Row():
                            with gr.Column(scale=4):
                                summary = gr.HTML(
                                    presentation.display_fields(
                                        [
                                            ("Task ID", task_id),
                                            ("Task Name", row[1]),
                                            ("Task Status", row[2]),
                                            ("Created Date", row[4]),
                                            ("Assigned to RACF", assigned_id),
                                            ("Assigned to Name", row[3]),
                                            ("Created by RACF", creator_id),
                                            ("Created by Name", creator_name),
                                        ]
                                    )
                                )
                            with gr.Column(scale=1, elem_classes="task-actions"):
                                assign = gr.Button("SELF ASSIGN", size="sm")
                                delete = gr.Button("DELETE TASK", size="sm")
                        comment = gr.Textbox(value=row[7], label="Comments", lines=2)
                        save = gr.Button("Save Comments", size="sm")
                        with gr.Row():
                            gr.Markdown("")
                            finish = gr.Button("Complete Task", scale=0, size="sm")
                        gr.HTML(presentation.claims_for_review_html(canonical))
                        review = gr.Button("+ Review Claims", size="sm")
                        gr.HTML('<div class="qc-bar">QC Review Information</div>')
                        gr.HTML(
                            '<div class="qc-review-header"><span>Claim</span><span>QC Review</span><span>QC Review Comment</span><span>Review Areas</span><span>Points</span><span>Reviewed By</span></div>'
                        )
                        bindings = panels.TaskViewBindings(
                            task_id_state=task_id_state,
                            user_state=user_state,
                            task_rows=task_rows,
                            task_view_revision=task_view_revision,
                            summary=summary,
                            task_expansion=task_expansion,
                            notifications_panel=notifications_panel,
                            alert_button=alert_button,
                        )
                        panels.build_completed_claims(canonical, bindings)
                        work_panel = panels.build_review_panel(task_id, bindings)
                        assign.click(
                            lambda tid, user: tasks.perform_task_action(tid, "assign", user),
                            [task_id_state, user_state],
                            [task_rows, notice],
                        ).then(
                            notifications.notification_badge,
                            user_state,
                            alert_button,
                        )
                        delete.click(
                            lambda tid, user: tasks.perform_task_action(tid, "delete", user),
                            [task_id_state, user_state],
                            [task_rows, notice],
                        )
                        finish.click(
                            lambda tid, user: tasks.perform_task_action(tid, "finish", user),
                            [task_id_state, user_state],
                            [task_rows, notice],
                        )
                        save.click(
                            tasks.save_task_comments,
                            [task_id_state, comment, user_state],
                            [task_rows, notice],
                        )
                        review.click(lambda: gr.update(visible=True), outputs=work_panel)

            refresh = gr.Button("Refresh Tasks", size="sm")
            refresh.click(
                tasks.refresh_task_view,
                [user_state, task_view_revision],
                [task_rows, task_view_revision],
            )
        login_button.click(
            session.login_user,
            login_choice,
            [user_state, login_panel, user_banner, task_rows, alert_button],
        )
        logout_button.click(
            session.logout_user,
            outputs=[user_state, login_panel, user_banner, task_rows, alert_button],
        )
        alert_button.click(
            notifications.open_alerts, user_state, [alert_popup, notifications_panel, alert_button]
        )
        close_alert_button.click(notifications.close_alerts, outputs=alert_popup)
        mark_alerts_read.click(
            notifications.mark_notifications_read, user_state, [notifications_panel, alert_button]
        )
        alert_timer.tick(notifications.notification_badge, user_state, alert_button)
    return demo
