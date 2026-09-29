"""Regression checks for application startup and extracted UI components."""

import importlib
import unittest
from unittest.mock import MagicMock, patch

import gradio as gr

import app
from qc_app import database, panels, presentation, ui


class ApplicationStructureTests(unittest.TestCase):
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

    def test_presentation_escapes_claim_content(self):
        rendered = presentation.claims_for_review_html(
            {"claimsForReviews": [{"claimNumber": "<script>alert(1)</script>"}]}
        )
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
