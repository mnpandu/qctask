"""Integration checks against Oracle; all test data is rolled back."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qc_app.database import JsonDocument

import claim_workflow as qc
from qc_app import (
    claims,
    config,
    database,
    identity,
    messaging,
    messaging_service,
    notifications,
    presentation,
    repository,
    session,
    task_service,
    tasks,
)


class ClaimWorkflowTests(unittest.TestCase):
    def test_released_unreviewed_claim_keeps_first_review_choices_in_next_task(self):
        with patch.object(config, "CASE_ID", 9876543208), database.connect_db() as conn:
            try:
                claim_id = "TEST-RELEASED-UNREVIEWED"
                conn.execute(
                    "INSERT INTO qc_store.qctask_claim_details (case_id, claim_number, claim_data) VALUES (:p1, :p2, :p3)",
                    (config.CASE_ID, claim_id, JsonDocument({"Claim ID": claim_id})),
                )
                first = task_service.persist_task(conn, config.TASK_TYPES[1], [claim_id], "")
                task_service.task_action(conn, first, "finish", config.USERS["pandu"])
                self.assertEqual(qc.review_view(conn, first)[0][0][1], "Released")
                second = task_service.persist_task(conn, config.TASK_TYPES[1], [claim_id], "")
                row = qc.review_view(conn, second)[0][0]
                self.assertFalse(row[2]["hasPreviousReview"])
                self.assertEqual(qc.review_decision_options(row[1], row[2]),
                                 (["Agree", "Action Required"], None, True))
                with self.assertRaises(ValueError):
                    qc.save_claim_decision(conn, second, config.CASE_ID, claim_id,
                                           "Re-review", "Complete", "pandu")
                qc.save_claim_decision(conn, second, config.CASE_ID, claim_id,
                                       "Agree", "", "pandu")
                saved = qc.review_view(conn, second)[0][0][2]
                self.assertEqual(saved["qcReviewComment"], "Completed")
            finally:
                conn.rollback()


    def test_returned_claim_in_second_task_requires_rereview(self):
        with patch.object(config, "CASE_ID", 9876543209), database.connect_db() as conn:
            try:
                claim_id = "TEST-CROSS-TASK-REVIEW"
                conn.execute(
                    "INSERT INTO qc_store.qctask_claim_details (case_id, claim_number, claim_data) VALUES (:p1, :p2, :p3)",
                    (config.CASE_ID, claim_id, JsonDocument({"Claim ID": claim_id})),
                )
                first = task_service.persist_task(conn, config.TASK_TYPES[1], [claim_id], "")
                row = qc.review_view(conn, first)[0][0]
                self.assertEqual(qc.review_decision_options(row[1], row[2])[0], ["Agree", "Action Required"])
                qc.save_claim_decision(conn, first, config.CASE_ID, claim_id,
                                       "Action Required", "Return for Correction", "pandu")
                second = task_service.persist_task(conn, config.TASK_TYPES[1], [claim_id], "")
                row = qc.review_view(conn, second)[0][0]
                self.assertEqual(row[1], "Created")
                self.assertNotIn("qcReview", row[2])
                self.assertEqual(qc.review_decision_options(row[1], row[2]), (["Re-review"], "Re-review", True))
                with self.assertRaises(ValueError):
                    qc.save_claim_decision(conn, second, config.CASE_ID, claim_id,
                                           "Agree", "Completed", "pandu")
                qc.save_claim_decision(conn, second, config.CASE_ID, claim_id,
                                       "Re-review", "Complete", "pandu")
                self.assertEqual(qc.eligible_claims(conn, config.CASE_ID), [])
            finally:
                conn.rollback()


    def test_review_choices_depend_on_claim_history(self):
        self.assertEqual(
            qc.review_decision_options("Created", {}), (["Agree", "Action Required"], None, True)
        )
        for details in (
            {"qcReview": "Action Required"},
            {"qcReview": "Re-review", "qcReviewComment": "Return of Correction"},
        ):
            self.assertEqual(
                qc.review_decision_options("Returned for Corrections", details),
                (["Re-review"], "Re-review", True),
            )
        self.assertEqual(
            qc.review_decision_options("Agree", {"qcReview": "Agree"}), (["Agree"], "Agree", False)
        )
        self.assertEqual(
            qc.review_decision_options(
                "Completed", {"qcReview": "Re-review", "qcReviewComment": "Complete"}
            ),
            (["Re-review"], "Re-review", False),
        )

    def test_review_comment_choices_and_rereview_outcomes(self):
        self.assertEqual(
            claims.qc_comment_options("Agree"),
            {
                "choices": ["Completed"],
                "value": "Completed",
                "interactive": False,
            },
        )
        self.assertEqual(
            claims.qc_comment_options("Action Required")["choices"],
            ["Return for Correction", "Response Requested"],
        )
        self.assertEqual(
            claims.qc_comment_options("Re-review")["choices"], ["Return of Correction", "Complete"]
        )
        for comment, status in (
            ("Return of Correction", "Returned for Corrections"),
            ("Complete", "Completed"),
        ):
            conn = MagicMock()
            with (
                patch.object(qc, "lock_task"),
                patch.object(
                    qc,
                    "review_view",
                    return_value=(
                        [("C1", "Returned for Corrections", {"qcReview": "Action Required"}, {})],
                        None,
                    ),
                ),
                patch.object(qc, "sync_canonical") as sync,
            ):
                qc.save_claim_decision(conn, 1, 1, "C1", "Re-review", comment, "pandu")
                self.assertEqual(conn.execute.call_args_list[0].args[1], (status, 1, "C1"))
                self.assertEqual(sync.call_args.args[4]["qcReviewComment"], comment)
                with self.assertRaises(ValueError):
                    qc.save_claim_decision(
                        conn, 1, 1, "C1", "Re-review", "Response Requested", "pandu"
                    )

    def test_refresh_task_view_forces_render_when_task_rows_are_unchanged(self):
        rows = [[1, "Task", "In Progress"]]
        user = config.USERS["pandu"]
        with patch.object(tasks, "refresh_tasks", return_value=rows) as refresh:
            result = tasks.refresh_task_view(user, 4)

        refresh.assert_called_once_with(user)
        self.assertEqual(result, (rows, 5))

    def test_task_actions_refresh_the_task_view(self):
        rows = [[1, "Task", "Completed"]]
        user = config.USERS["pandu"]
        with (
            patch.object(
                tasks, "perform_task_action", return_value=(rows, "Task completed.")
            ) as action,
            patch.object(tasks, "refresh_task_heading") as refresh_heading,
        ):
            result = tasks.perform_task_action_and_refresh_view(1, "finish", user, 4)

        action.assert_called_once_with(1, "finish", user)
        refresh_heading.assert_not_called()
        self.assertEqual(result, (rows, "Task completed.", 5))

    def test_login_users_have_separate_roles(self):
        with (
            patch.object(tasks, "refresh_tasks", return_value=[]),
            patch.object(notifications, "notification_badge", return_value="Alerts (0)"),
        ):
            pandu = session.login_user("pandu")
            regine = session.login_user("regine")

        self.assertEqual(pandu[0], {"id": "pandu", "name": "Pandu", "role": "QC Nurse"})
        self.assertEqual(regine[0], {"id": "regine", "name": "Regine", "role": "Nurse"})

    def test_notification_recipients_include_only_target(self):
        self.assertEqual(
            messaging_service.notification_recipients("nurse-two"),
            ["nurse-two"],
        )
        self.assertEqual(
            messaging_service.notification_recipients("nurse-one"),
            ["nurse-one"],
        )

    def test_blank_note_recipient_defaults_to_current_user(self):
        with patch.object(config, "ACTOR_ID", "self-user"):
            self.assertEqual(
                messaging_service.notification_recipients(config.ACTOR_ID),
                ["self-user"],
            )

    def test_note_reply_recipient_defaults_to_last_conversation_participant(self):
        class FakeConnection:
            def __init__(self, last_message):
                self.last_message = last_message

            def execute(self, query, params):
                return type("Result", (), {"fetchone": lambda _: self.last_message})()

        with patch.object(config, "ACTOR_ID", "nurse"):
            self.assertEqual(
                messaging_service.claim_note_reply_recipient(
                    FakeConnection(("demo", "nurse")), 1, "CLM-1"
                ),
                "demo",
            )
            self.assertEqual(
                messaging_service.claim_note_reply_recipient(
                    FakeConnection(("demo", "demo")), 1, "CLM-1"
                ),
                "demo",
            )
            self.assertEqual(
                messaging_service.claim_note_reply_recipient(FakeConnection(None), 1, "CLM-1"),
                "nurse",
            )

    def test_sending_claim_note_alerts_only_recipient(self):
        calls = []

        def execute(query, params=None):
            calls.append((query, params))
            if "SELECT COALESCE(assigned_to" in query:
                return SimpleNamespace(fetchone=lambda: ("pandu",))
            if "INSERT INTO qc_store.qctask_claim_messages" in query:
                return SimpleNamespace(fetchone=lambda: (42,))
            return SimpleNamespace(fetchone=lambda: None)

        conn = SimpleNamespace(execute=execute)
        with (
            patch.object(qc, "lock_task"),
            patch.object(qc, "review_view", return_value=([("CLM-1", "Agree", {}, {})], None)),
            patch.object(config, "CASE_ID", 1),
        ):
            messaging_service.persist_claim_note(
                conn, 7, "CLM-1", "regine", "Please review this claim.", config.USERS["pandu"]
            )

        notification_rows = [
            params for query, params in calls if "INSERT INTO qc_store.qctask_notifications" in query
        ]
        self.assertEqual(
            [params[3] for params in notification_rows],
            ["regine"],
        )

    def test_saving_qc_decision_persists_review_areas_and_points(self):
        statements = []
        conn = SimpleNamespace(
            execute=lambda query, params=None: statements.append((query, params))
        )
        rows = [("CLM-1", "In Progress", {}, {})]
        with (
            patch.object(qc, "lock_task"),
            patch.object(qc, "review_view", return_value=(rows, None)),
            patch.object(qc, "sync_canonical") as sync,
        ):
            qc.save_claim_decision(
                conn,
                12,
                1,
                "CLM-1",
                "Agree",
                "Completed",
                "pandu",
                ["Coding", "Other"],
                "3",
            )

        sync.assert_called_once_with(
            conn,
            12,
            "pandu",
            "CLM-1",
            {
                "qcReview": "Agree",
                "qcReviewComment": "Completed",
                "reviewedBy": "pandu",
                "reviewCategories": ["Coding", "Other"],
                "points": "3",
                "clinicalDetermination": False,
                "genericReasonCode": False,
                "coding": True,
                "decisionRemarks": False,
                "other": True,
            },
        )

    def test_unsaved_review_area_checkboxes_default_false(self):
        for category in qc.QC_REVIEW_CATEGORIES:
            self.assertFalse(presentation.review_area_checked({}, category))

    def test_open_claim_editor_restores_all_five_checkbox_states(self):
        details = {
            "qcReview": "Agree",
            "qcReviewComment": "Completed",
            "clinicalDetermination": True,
            "genericReasonCode": False,
            "coding": True,
            "decisionRemarks": False,
            "other": True,
        }
        metadata = (
            "",
            "",
            "",
            {
                "claimsForReviews": [
                    {
                        "claimNumber": "CLM-1",
                        "qcReviewDetails": details,
                    }
                ],
            },
        )
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = None
        context = MagicMock()
        context.__enter__.return_value = fake_conn
        with (
            patch.object(repository, "task_metadata", return_value=metadata),
            patch.object(database, "connect_db", return_value=context),
            patch.object(messaging, "claim_conversation_html", return_value="conversation"),
        ):
            result = claims.open_claim_editor(12, "CLM-1", config.USERS["pandu"])

        self.assertEqual(
            [entry["value"] for entry in result[3:8]], [True, False, True, False, True]
        )

    def test_edit_save_sends_selected_areas_and_points_to_backend(self):
        conn = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = conn
        with (
            patch.object(identity, "require_user", return_value=config.USERS["pandu"]),
            patch.object(database, "connect_db", return_value=context),
            patch.object(qc, "save_claim_decision") as save_decision,
            patch.object(
                claims, "claim_review_summary_html", return_value="<div>Claim summary</div>"
            ),
        ):
            result = claims.save_claim_edit_form(
                12,
                "CLM-1",
                True,
                True,
                True,
                True,
                True,
                "5",
                "Agree",
                "Completed",
                config.USERS["pandu"],
            )

        save_decision.assert_called_once_with(
            conn,
            12,
            config.CASE_ID,
            "CLM-1",
            "Agree",
            "Completed",
            "pandu",
            [
                "Clinical Determination",
                "Generic Reason Code",
                "Coding",
                "Decision Remarks",
                "Other",
            ],
            "5",
        )
        self.assertEqual(result[0], "QC review updated for CLM-1.")

    def test_saving_qc_decision_rejects_unknown_review_areas(self):
        conn = SimpleNamespace(execute=lambda *args, **kwargs: None)
        with patch.object(qc, "lock_task"), self.assertRaises(ValueError):
            qc.save_claim_decision(
                conn,
                12,
                1,
                "CLM-1",
                "Agree",
                "Completed",
                "pandu",
                ["Unknown category"],
                "",
            )

    def test_regular_qc_save_does_not_overwrite_edit_only_points(self):
        conn = SimpleNamespace(execute=lambda *args, **kwargs: None)
        rows = [("CLM-1", "In Progress", {}, {})]
        with (
            patch.object(qc, "lock_task"),
            patch.object(qc, "review_view", return_value=(rows, None)),
            patch.object(qc, "sync_canonical") as sync,
        ):
            qc.save_claim_decision(
                conn,
                12,
                1,
                "CLM-1",
                "Agree",
                "Completed",
                "pandu",
                ["Coding"],
            )

        self.assertNotIn("points", sync.call_args.args[4])

    def test_claim_review_summary_displays_saved_areas_and_points(self):
        html = presentation.render_claim_review_summary(
            {
                "claimNumber": "CLM-1",
                "qcReviewDetails": {
                    "qcReview": "Agree",
                    "qcReviewComment": "Completed",
                    "reviewCategories": ["Coding", "Other"],
                    "points": "3.5",
                    "reviewedBy": "pandu",
                },
            }
        )

        self.assertIn("Coding, Other", html)
        self.assertIn("3.5", html)

    def test_completed_claims_html_shows_only_completed_qc_reviews(self):
        claims = [
            {
                "claimNumber": "DONE-1",
                "qcReviewStatus": "Agree",
                "qcReviewDetails": {"qcReview": "Agree", "qcReviewComment": "Completed"},
            },
            {
                "claimNumber": "PENDING-1",
                "qcReviewStatus": "In Progress",
                "qcReviewDetails": {"qcReview": "Agree", "qcReviewComment": "Completed"},
            },
            {
                "claimNumber": "CREATED-1",
                "qcReviewStatus": "Created",
                "qcReviewDetails": {},
            },
        ]
        completed = presentation.completed_claims({"claimsForReviews": claims})

        self.assertEqual([claim["claimNumber"] for claim in completed], ["DONE-1"])

    def test_full_and_partial_workflow(self):
        original_case = config.CASE_ID
        config.CASE_ID = 9876543210
        try:
            with database.connect_db() as conn:
                try:
                    self.assertEqual(
                        conn.execute(
                            "SELECT count(*) FROM qc_store.qctask_claim_details WHERE case_id = :p1",
                            (config.CASE_ID,),
                        ).fetchone()[0],
                        0,
                    )
                    claims = [{"Claim ID": f"TEST-CLAIM-{i}"} for i in range(3)]
                    for claim in claims:
                        conn.execute(
                            "INSERT INTO qc_store.qctask_claim_details (case_id, claim_number, claim_data) VALUES (:p1, :p2, :p3)",
                            (config.CASE_ID, claim["Claim ID"], JsonDocument(claim)),
                        )
                    ids = [c["Claim ID"] for c in claims]
                    conn.execute(
                        "UPDATE qc_store.qctask_claim_details SET qc_status = 'Completed' WHERE case_id = :p1 AND claim_number = :p2",
                        (config.CASE_ID, ids[2]),
                    )
                    self.assertEqual(len(qc.eligible_claims(conn, config.CASE_ID)), 2)
                    # Full review always gets all eligible claims, even if a subset is sent.
                    task_id = task_service.persist_task(
                        conn, config.TASK_TYPES[0], ids[:1], "Full review"
                    )
                    self.assertEqual(len(qc.review_view(conn, task_id)[0]), 2)
                    self.assertTrue(
                        all(r[1] == "Created" for r in qc.review_view(conn, task_id)[0])
                    )
                    self.assertEqual(qc.eligible_claims(conn, config.CASE_ID), [])
                    with self.assertRaises(ValueError):
                        task_service.persist_task(conn, config.TASK_TYPES[1], ids[:1], "Duplicate")
                    self.assertEqual(
                        qc.start_next(conn, task_id, config.CASE_ID, config.ACTOR_ID), ids[0]
                    )
                    self.assertEqual(
                        qc.start_next(conn, task_id, config.CASE_ID, config.ACTOR_ID), ids[0]
                    )
                    with self.assertRaises(ValueError):
                        qc.save_review(
                            conn,
                            task_id,
                            config.CASE_ID,
                            ids[1],
                            "Approved",
                            "",
                            True,
                            config.ACTOR_ID,
                        )
                    with self.assertRaises(ValueError):
                        qc.save_review(
                            conn, task_id, config.CASE_ID, ids[0], "", "", True, config.ACTOR_ID
                        )
                    qc.save_review(
                        conn,
                        task_id,
                        config.CASE_ID,
                        ids[0],
                        "Needs Correction",
                        "Check coding",
                        False,
                        config.ACTOR_ID,
                    )
                    self.assertEqual(qc.review_view(conn, task_id)[1][2]["notes"], "Check coding")
                    canonical = conn.execute(
                        "SELECT task_canonical FROM qc_store.qctask_task_details WHERE task_id = :p1",
                        (task_id,),
                    ).fetchone()[0]
                    details = canonical["claimsForReviews"][0]["qcReviewDetails"]
                    self.assertEqual(
                        details,
                        {
                            "outcome": "Needs Correction",
                            "notes": "Check coding",
                            "reviewedBy": config.ACTOR_ID,
                        },
                    )
                    qc.save_review(
                        conn,
                        task_id,
                        config.CASE_ID,
                        ids[0],
                        "Approved",
                        "Checked",
                        True,
                        config.ACTOR_ID,
                    )
                    self.assertEqual(qc.review_view(conn, task_id)[1][0], ids[1])
                    # Repeated submission must not complete the next claim.
                    with self.assertRaises(ValueError):
                        qc.save_review(
                            conn,
                            task_id,
                            config.CASE_ID,
                            ids[0],
                            "Approved",
                            "",
                            True,
                            config.ACTOR_ID,
                        )
                    qc.save_review(
                        conn,
                        task_id,
                        config.CASE_ID,
                        ids[1],
                        "Rejected",
                        "Reviewed",
                        True,
                        config.ACTOR_ID,
                    )
                    self.assertIsNone(qc.review_view(conn, task_id)[1])
                    self.assertEqual(
                        conn.execute(
                            "SELECT task_status FROM qc_store.qctask_task WHERE task_id = :p1", (task_id,)
                        ).fetchone()[0],
                        "Completed",
                    )
                    payload = conn.execute(
                        "SELECT task_canonical FROM qc_store.qctask_task_details WHERE task_id = :p1",
                        (task_id,),
                    ).fetchone()[0]
                    self.assertTrue(
                        all(c["qcReviewStatus"] == "Completed" for c in payload["claimsForReviews"])
                    )
                    self.assertEqual(
                        conn.execute(
                            "SELECT qc_status FROM qc_store.qctask_claim_details WHERE case_id = :p1 AND claim_number = :p2",
                            (config.CASE_ID, ids[0]),
                        ).fetchone()[0],
                        "Completed",
                    )
                    conn.execute(
                        "UPDATE qc_store.qctask_claim_details SET qc_status = NULL WHERE case_id = :p1 AND claim_number = :p2",
                        (config.CASE_ID, ids[2]),
                    )
                    partial = task_service.persist_task(
                        conn, config.TASK_TYPES[1], ids[2:], "Partial"
                    )
                    self.assertEqual(len(qc.review_view(conn, partial)[0]), 1)
                    self.assertEqual(len(tasks.review_outputs(conn, partial)), 11)
                finally:
                    conn.rollback()
        finally:
            config.CASE_ID = original_case


if __name__ == "__main__":
    unittest.main()
