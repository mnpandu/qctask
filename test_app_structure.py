"""Regression checks for application startup and extracted UI components."""

import asyncio
import importlib
import unittest
from unittest.mock import MagicMock, patch

import gradio as gr
from gradio.context import LocalContext
from gradio.state_holder import SessionState

import app
from qc_app import claims, database, panels, presentation, ui


class ApplicationStructureTests(unittest.TestCase):
    def test_task_refresh_preserves_dynamic_event_ids(self):
        demo = ui.create_app()
        state = SessionState(demo)
        renderer = demo.renderables[0]
        rows = [[1, "Partial", "In Progress", "Pandu", "today", "", 1, ""]]
        canonical = {"claimsForReviews": [{"claimNumber": "C1", "qcReviewStatus": "Agree", "qcReviewDetails": {"qcReview": "Agree"}}]}
        token = LocalContext.blocks_config.set(state.blocks_config)
        try:
            with patch.object(ui.repository, "task_metadata", return_value=("pandu", "pandu", "Pandu", canonical)), patch.object(database, "connect_db"), patch.object(panels.qc, "review_view", return_value=([("C1", "Agree", {}, {})], None)):
                renderer.apply(rows, ui.config.USERS["pandu"], 0)
                before = {fn.key: fn._id for fn in state.blocks_config.fns.values() if fn.rendered_in is renderer}
                self.assertNotIn(None, before)
                rows[0][2] = "Completed"
                renderer.apply(rows, ui.config.USERS["pandu"], 1)
                after = {fn.key: fn._id for fn in state.blocks_config.fns.values() if fn.rendered_in is renderer}
                self.assertEqual(before, after)
        finally:
            LocalContext.blocks_config.reset(token)


    def test_claim_expansion_updates_single_and_multiple_accordions(self):
        for count in (1, 3):
            with self.subTest(claim_count=count):
                with gr.Blocks() as demo:
                    accordions = [gr.Accordion(open=False) for _ in range(count)]
                    event = accordions[0].expand(
                        lambda: None, outputs=accordions, queue=False
                    )
                result = asyncio.run(
                    demo.postprocess_data(
                        demo.fns[event["id"]],
                        claims.expand_claim_panels(0, count),
                        None,
                    )
                )
                self.assertEqual(len(result), count)
                self.assertEqual([update["open"] for update in result], [True] + [False] * (count - 1))

    def test_import_does_not_build_ui_or_connect_to_database(self):
        with patch.object(gr, "Blocks") as blocks, patch.object(database, "connect_db") as connect:
            importlib.reload(ui)
            importlib.reload(app)
        blocks.assert_not_called()
        connect.assert_not_called()

    def test_factory_builds_independent_interfaces_without_database_access(self):
        with patch.object(database, "connect_db") as connect:
            first = ui.create_app()
            second = ui.create_app()
        self.assertIsInstance(first, gr.Blocks)
        self.assertIsNot(first, second)
        self.assertTrue(first.config["dependencies"])
        self.assertIn(".task-fields", first.css)
        self.assertIn("MutationObserver", first.js)
        connect.assert_not_called()

    def test_schema_is_loaded_relative_to_module(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = (False,)
        with patch.object(database, "connect_db") as connect:
            connect.return_value.__enter__.return_value = connection
            database.initialize_db()
        schema = connection.execute.call_args_list[1].args[0]
        self.assertIn("CREATE TABLE", schema)
        self.assertIn("pic_master", schema)

    def test_extracted_panels_register_event_chains(self):
        canonical = {
            "claimsForReviews": [
                {
                    "claimNumber": "CLM-1",
                    "qcReviewStatus": "Agree",
                    "qcReviewDetails": {"qcReview": "Agree", "qcReviewComment": "Completed"},
                }
            ],
        }
        with gr.Blocks() as demo:
            bindings = panels.TaskViewBindings(
                task_id_state=gr.State(1),
                user_state=gr.State(None),
                task_rows=gr.State([]),
                task_view_revision=gr.State(0),
                summary=gr.HTML(),
                task_expansion=gr.Accordion(),
                notifications_panel=gr.HTML(),
                alert_button=gr.Button(),
            )
            panels.build_completed_claims(canonical, bindings)
            with (
                patch.object(database, "connect_db"),
                patch.object(
                    panels.qc, "review_view", return_value=([("CLM-2", "Created", {}, {})], None)
                ),
            ):
                review_panel = panels.build_review_panel(1, bindings)
        self.assertIsInstance(review_panel, gr.Column)
        self.assertFalse(review_panel.visible)
        self.assertGreater(len(demo.config["dependencies"]), 10)
        labels = {
            component["id"]: component.get("props", {}).get("label")
            for component in demo.config["components"]
        }
        decision_changes = [
            dependency
            for dependency in demo.config["dependencies"]
            if any(
                trigger == "change" and labels.get(component_id) == "QC Review"
                for component_id, trigger in dependency["targets"]
            )
        ]
        self.assertTrue(decision_changes)
        self.assertTrue(all(dependency["queue"] for dependency in decision_changes))

    def test_presentation_escapes_claim_content(self):
        rendered = presentation.claims_for_review_html(
            {"claimsForReviews": [{"claimNumber": "<script>alert(1)</script>"}]}
        )
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
