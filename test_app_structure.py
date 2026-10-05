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


    def test_review_claim_metadata_matches_reference_and_preserves_values(self):
        data = {
            "no_of_lines": 0, "dosFrom": "04/20/2023", "dosTo": "04/21/2023",
            "MBI": "MBI123", "focusCode": "FC", "PTAN": "396053",
            "NPI": "1265432165", "responseReceived": "Yes", "claimDecision": "Y",
            "qcReview": "N", "adrSentDate": "07/12/2023", "typeOfBill": "111",
        }
        fields = presentation.review_claim_fields("C1", data)
        self.assertEqual([label for label, _ in fields[:12]], list(ui.config.REVIEW_CLAIM_FIELDS))
        self.assertEqual([value for _, value in fields[:12]], [
            "C1", 0, "04/20/2023 - 04/21/2023", "MBI123", "FC", "396053",
            "1265432165", "Yes", "Y", "N", "07/12/2023", "111",
        ])
        self.assertIn("<span>0</span>", presentation.display_fields(fields))
        self.assertEqual(dict(presentation.review_claim_fields("C2", {}))["NPI"], "")

    def test_expanded_claim_attachments_and_decision_details(self):
        data = {"attachments": [{"fileName": "<script>file</script>", "documentType": "Medical",
                                 "workType": "Review", "receiptDate": "07/12/2023"}],
                "decisionDetails": {"decision": "Full Denial", "decisionDate": "07/21/2023",
                                    "genericReasonCode": "GAI02", "denialReason": "59CON",
                                    "preMROriginalReimbursement": 0, "decisionRemarks": "Full denial"}}
        attachments = presentation.claim_attachments_html(data)
        for label in ("File Name", "Doc Type", "Work Type", "Receipt Date"):
            self.assertIn(label, attachments)
        self.assertIn("Medical", attachments)
        self.assertNotIn("<script>", attachments)
        self.assertIn("&lt;script&gt;file", attachments)
        self.assertIn("No records to display", presentation.claim_attachments_html({}))
        details = presentation.claim_decision_details_html(data)
        for label in ("Decision", "Decision Date", "Associated DCN", "Demand Bill", "Denial Reason",
                      "Generic Reason Code", "Pre MR Original Reimbursement", "Post MR Original Reimbursement",
                      "Total Reimbursement Savings", "Decision Remarks"):
            self.assertIn(label, details)
        self.assertIn("Full Denial", details)
        self.assertIn("<span>0</span>", details)

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
        self.assertFalse(any(isinstance(block, gr.Dataframe) and block.label == "Claims for Review"
                             for block in demo.blocks.values()))
        claim_row = next(block for block in demo.blocks.values()
                         if isinstance(block, gr.Accordion) and "claim-review-summary" in (block.elem_classes or []))
        self.assertEqual(len(claim_row.label.split("\t")), 12)
        self.assertEqual(claim_row.label.split("\t")[0], "CLM-2")
        self.assertEqual(claim_row.label.split("\t")[9], "Created")
        self.assertFalse(claim_row.open)
        claim_html = [block.value for block in claim_row.children if isinstance(block, gr.HTML)]
        self.assertTrue(any("Attachments" in value for value in claim_html))
        self.assertTrue(any("Decision Details" in value for value in claim_html))
        self.assertTrue(any(isinstance(block, gr.HTML) and "claim-review-header" in str(block.value)
                            for block in demo.blocks.values()))
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


