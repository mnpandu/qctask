"""Task lifecycle comment persistence and display checks."""

import unittest
import re
from unittest.mock import patch

from psycopg.types.json import Jsonb

import claim_workflow as qc
from qc_app import comments, config, database, task_service


class TaskCommentsTests(unittest.TestCase):
    def test_creation_and_completion_snapshots(self):
        for manual in (False, True):
            with self.subTest(manual=manual), patch.object(config, "CASE_ID", 9876543211), database.connect_db() as conn:
                try:
                    ids = ["TEST-COMMENT-1", "TEST-COMMENT-2"]
                    for claim_id in ids:
                        conn.execute(
                            "INSERT INTO pic_master.claim_details (case_id, claim_number, claim_data) VALUES (%s, %s, %s)",
                            (config.CASE_ID, claim_id, Jsonb({})),
                        )
                    task_id = task_service.persist_task(conn, config.TASK_TYPES[1], ids, "Creation comment", config.USERS["regine"])

                    def entries():
                        return conn.execute(
                            "SELECT event_type, comment_text, claim_reviews FROM pic_master.task_comments WHERE task_id = %s ORDER BY comment_id",
                            (task_id,),
                        ).fetchall()

                    self.assertEqual(entries(), [("Created", "Creation comment", [])])
                    qc.save_claim_decision(conn, task_id, config.CASE_ID, ids[0], "Agree", "Completed", "regine", ["Coding"], "2", "3")
                    self.assertEqual(len(entries()), 1)
                    if manual:
                        task_service.task_action(conn, task_id, "finish", config.USERS["regine"])
                    else:
                        qc.save_claim_decision(conn, task_id, config.CASE_ID, ids[1], "Action Required", "Return for Correction", "pandu", ["Other"], "4", "5")
                    saved = entries()
                    self.assertEqual([entry[0] for entry in saved], ["Created", "Completed"])
                    reviews = saved[1][2]
                    self.assertEqual(len(reviews), 1 if manual else 2)
                    self.assertEqual(reviews[0]["claimNumber"], ids[0])
                    self.assertEqual(set(reviews[0]), {"claimNumber", "qcReview", "qcComment"})
                    self.assertEqual(reviews[0]["qcReview"], "Agree")
                    qc.save_claim_decision(conn, task_id, config.CASE_ID, ids[0], "Agree", "Completed", "pandu", [], "9", "9")
                    refreshed = entries()
                    self.assertEqual(len(refreshed), 2)
                    self.assertEqual(set(refreshed[1][2][0]), {"claimNumber", "qcReview", "qcComment"})
                    task_service.persist_update(conn, task_id, "", "", "Updated creation comment", user=config.USERS["regine"])
                    self.assertEqual(entries()[0][1], "Updated creation comment")
                    refreshed = entries()
                    task_service.task_action(conn, task_id, "finish", config.USERS["pandu"])
                    self.assertEqual(entries(), refreshed)
                    task_service.task_action(conn, task_id, "delete", config.USERS["pandu"])
                    self.assertEqual(entries(), [])
                    statuses = conn.execute(
                        "SELECT qc_status FROM pic_master.claim_details WHERE case_id = %s",
                        (config.CASE_ID,),
                    ).fetchall()
                    self.assertEqual(statuses, [("Released",), ("Released",)])
                finally:
                    conn.rollback()

    def test_comments_render_escapes_content_and_shows_review_fields(self):
        html = comments.render_comments([
            (1, "Created", "<script>comment</script>", [], "regine", "today", "Full Review", "Regine"),
            (1, "Completed", "Task completed.", [{"claimNumber": "C1", "contractPoints": "2",
              "nursePoints": "3", "reviewAreas": ["Coding"], "finalStatus": "Agree",
              "qcReview": "Agree", "qcComment": "Completed"}], "pandu", "today", "Full Review", "Pandu"),
        ])
        self.assertEqual(html.count('<details class="claim-detail-section task-comment-entry">'), 2)
        self.assertNotIn('<details open', html)
        summaries = re.findall(r'<summary>(.*?)</summary>', html, re.S)
        self.assertEqual(len(summaries), 2)
        for summary in summaries:
            for label in ("Date", "Task ID", "Task Name", "RACF - Name"):
                self.assertIn(label, summary)
            self.assertNotIn("Comments", summary)
            self.assertNotIn("Final Status", summary)
            self.assertNotIn("Created", summary)
        self.assertIn("Task 1 - Created", html)
        self.assertIn("Full Review", html)
        self.assertIn("regine - Regine", html)
        self.assertIn("pandu - Pandu", html)
        for label in ("Date", "Task ID", "Task Name", "RACF - Name", "Comments"):
            self.assertIn(label, html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;comment", html)
        for value in ("C1", "QC Review", "QC Comment", "Agree"):
            self.assertIn(value, html)
        for removed in ("Contract Points", "Nurse Points", "Review Areas", "Final Status", "Coding"):
            self.assertNotIn(removed, html)

    def test_signed_out_comments_skip_database(self):
        with patch.object(database, "connect_db") as connect:
            self.assertEqual(comments.load_comments_html(None), "")
        connect.assert_not_called()
