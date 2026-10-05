"""Reporting data and access regression checks."""

import unittest
from unittest.mock import patch

from qc_app import config, database, reporting, repository


class ReportingTests(unittest.TestCase):
    def test_report_renders_separate_task_tables_and_escapes_notes(self):
        first = [7, "Partial", "Completed", "Pandu", "today", "today", 2, "Comment"]
        second = [6, "Full", "Not Started", "", "today", "", 1, ""]
        html = reporting.render_report([
            first + ["C1", "Agree", "Agree", "Completed", "Coding", "2", "pandu", "<script>note</script>"],
            first + ["C2", "", "", "", "", "", "", "", ""],
            second + ["C3", "", "", "", "", "", "", ""],
        ])
        self.assertEqual(html.count('<section class="report-task">'), 2)
        self.assertEqual(html.count('<table '), 2)
        self.assertLess(html.index("C2"), html.index("Task 6"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;note&lt;/script&gt;", html)

    def test_signed_out_report_is_empty_without_database_access(self):
        with patch.object(database, "connect_db") as connect:
            self.assertEqual(reporting.load_report(None), [])
        connect.assert_not_called()

    def test_both_roles_receive_one_table_grouped_by_task(self):
        canonical = {"claimsForReviews": [
            {"claimNumber": "C1", "qcReviewStatus": "Agree", "qcReviewDetails": {
                "qcReview": "Agree", "qcReviewComment": "Completed",
                "reviewCategories": ["Coding"], "points": "2", "nursePoints": "3", "reviewedBy": "pandu"}},
            {"claimNumber": "C2"},
        ]}
        for user in config.USERS.values():
            with self.subTest(user=user["id"]), patch.object(database, "connect_db") as connect, patch.object(repository, "list_tasks", return_value=[[7, "Partial", "Completed", "Pandu", "today", "today", 2, "Task comment"], [6, "Full", "Not Started", "", "today", "", 0, ""]]):
                conn = connect.return_value.__enter__.return_value
                conn.execute.return_value.fetchall.side_effect = [
                    [(7, canonical)], [(7, "C1", "pandu", "regine", "Please review", "today")],
                ]
                rows = reporting.load_report(user)
                self.assertEqual([row[0] for row in rows], [7, 7, 6])
                self.assertEqual(rows[0][8:16], ["C1", "Agree", "Agree", "Completed", "Coding", "2", "3", "pandu"])
                self.assertEqual(rows[0][-1], "today | pandu to regine: Please review")
                self.assertEqual(rows[1][8:], ["C2", "", "", "", "", "", "", "", ""])
                self.assertEqual(rows[2][8:], [""] * 9)
                self.assertTrue(all(len(row) == len(reporting.REPORT_HEADERS) for row in rows))
                for call in conn.execute.call_args_list:
                    self.assertEqual(call.args[1], (config.CASE_ID,))
