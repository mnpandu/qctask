"""Role authorization at mutation entry points."""

import unittest
from unittest.mock import MagicMock, patch

import gradio as gr

from qc_app import (
    claims,
    config,
    database,
    identity,
    messaging,
    messaging_service,
    repository,
    session,
    task_service,
    tasks,
)


class RolePermissionTests(unittest.TestCase):
    def test_completed_task_rejects_assign_and_finish_without_writes(self):
        for action in ("assign", "finish"):
            with self.subTest(action=action):
                conn = MagicMock()
                with patch.object(task_service.qc, "lock_task", return_value="Completed") as lock:
                    with self.assertRaisesRegex(ValueError, "already completed"):
                        task_service.task_action(conn, 1, action, config.USERS["pandu"])
                lock.assert_called_once_with(conn, 1, config.CASE_ID)
                conn.execute.assert_not_called()

    def test_both_roles_can_log_in_and_refresh_tasks(self):
        rows = [[1, "QC Nurse Full Review"]]
        with (
            patch.object(database, "connect_db") as connect,
            patch.object(repository, "list_tasks", return_value=rows),
        ):
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (0,)
            for username, user in config.USERS.items():
                with self.subTest(username=username):
                    result = session.login_user(username)
                    self.assertEqual(result[0], user)
                    self.assertFalse(result[1]["visible"])
                    self.assertEqual(result[3], rows)
                    self.assertEqual(tasks.refresh_task_view(user, 0), (rows, 1))

    def test_only_registered_qc_nurse_can_manage(self):
        self.assertTrue(identity.can_manage(config.USERS["pandu"]))
        for user in (None, config.USERS["regine"], {**config.USERS["regine"], "role": "QC Nurse"}):
            self.assertFalse(identity.can_manage(user))

    def test_nurse_mutations_rejected_before_database_access(self):
        nurse = config.USERS["regine"]
        operations = [
            lambda: tasks.create_task(config.TASK_TYPES[0], [], "", nurse),
            lambda: tasks.save_details(1, "", "", "", [], nurse),
            lambda: tasks.run_review("start", 1, user=nurse),
            lambda: tasks.run_review("draft", 1, user=nurse),
            lambda: tasks.run_review("complete", 1, user=nurse),
            lambda: claims.save_claim_form(1, "C1", [], "Agree", "Completed", nurse),
            lambda: claims.save_claim_edit_group(1, "C1", [], "", "Agree", "Completed", nurse),
        ]
        operations.extend(
            lambda action=action: tasks.perform_task_action(1, action, nurse)
            for action in ("assign", "finish", "delete")
        )
        with patch.object(database, "connect_db") as connect:
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises(gr.Error):
                    operation()
            connect.assert_not_called()

    def test_nurse_can_share_conversation_notes(self):
        nurse = config.USERS["regine"]
        with (
            patch.object(database, "connect_db"),
            patch.object(messaging_service, "persist_claim_note") as persist,
            patch.object(messaging, "claim_conversation_html", return_value="notes"),
        ):
            result = messaging.send_claim_note_form(1, "C1", "pandu", "Please review", nurse)
        self.assertEqual(persist.call_args.args[1:], (1, "C1", "pandu", "Please review", nurse))
        self.assertEqual(result[1], "notes")
