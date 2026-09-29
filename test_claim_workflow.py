"""Integration checks against PostgreSQL; all test data is rolled back."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app
import claim_workflow as qc


class ClaimWorkflowTests(unittest.TestCase):
    def test_refresh_task_view_forces_render_when_task_rows_are_unchanged(self):
        rows = [[1, 'Task', 'In Progress']]
        user = app.USERS['pandu']
        with patch.object(app, 'refresh_tasks', return_value=rows) as refresh:
            result = app.refresh_task_view(user, 4)

        refresh.assert_called_once_with(user)
        self.assertEqual(result, (rows, 5))

    def test_login_users_have_separate_roles(self):
        with patch.object(app, 'refresh_tasks', return_value=[]), patch.object(
            app, 'notification_badge', return_value='Alerts (0)'
        ):
            pandu = app.login_user('pandu')
            regine = app.login_user('regine')

        self.assertEqual(pandu[0], {'id': 'pandu', 'name': 'Pandu', 'role': 'QC Nurse'})
        self.assertEqual(regine[0], {'id': 'regine', 'name': 'Regine', 'role': 'Nurse'})

    def test_notification_recipients_include_target_and_assigned_nurse_once(self):
        self.assertEqual(
            app.notification_recipients('nurse-two', 'nurse-one'),
            ['nurse-two', 'nurse-one'],
        )
        self.assertEqual(
            app.notification_recipients('nurse-one', 'nurse-one'),
            ['nurse-one'],
        )

    def test_blank_note_recipient_defaults_to_current_user(self):
        with patch.object(app, 'ACTOR_ID', 'self-user'):
            self.assertEqual(app.notification_recipients(app.ACTOR_ID, 'assigned-nurse'),
                             ['self-user', 'assigned-nurse'])

    def test_note_reply_recipient_defaults_to_last_conversation_participant(self):
        class FakeConnection:
            def __init__(self, last_message):
                self.last_message = last_message

            def execute(self, query, params):
                return type('Result', (), {'fetchone': lambda _: self.last_message})()

        with patch.object(app, 'ACTOR_ID', 'nurse'):
            self.assertEqual(
                app.claim_note_reply_recipient(FakeConnection(('demo', 'nurse')), 1, 'CLM-1'),
                'demo',
            )
            self.assertEqual(
                app.claim_note_reply_recipient(FakeConnection(('demo', 'demo')), 1, 'CLM-1'),
                'demo',
            )
            self.assertEqual(
                app.claim_note_reply_recipient(FakeConnection(None), 1, 'CLM-1'),
                'nurse',
            )

    def test_sending_claim_note_alerts_recipient_and_assigned_nurse(self):
        calls = []

        def execute(query, params=None):
            calls.append((query, params))
            if 'SELECT COALESCE(assigned_to' in query:
                return SimpleNamespace(fetchone=lambda: ('nurse-one',))
            if 'INSERT INTO pic_master.qc_claim_messages' in query:
                return SimpleNamespace(fetchone=lambda: (42,))
            return SimpleNamespace(fetchone=lambda: None)

        conn = SimpleNamespace(execute=execute)
        with patch.object(qc, 'lock_task'), patch.object(
            qc, 'review_view', return_value=([('CLM-1', 'Agree', {}, {})], None)
        ), patch.object(app, 'CASE_ID', 1):
            app.persist_claim_note(conn, 7, 'CLM-1', 'nurse-two', 'Please review this claim.')

        notification_rows = [
            params for query, params in calls
            if 'INSERT INTO pic_master.qc_notifications' in query
        ]
        self.assertEqual(
            [params[3] for params in notification_rows],
            ['nurse-two', 'nurse-one'],
        )

    def test_saving_qc_decision_persists_review_areas_and_points(self):
        statements = []
        conn = SimpleNamespace(
            execute=lambda query, params=None: statements.append((query, params))
        )
        rows = [('CLM-1', 'In Progress', {}, {})]
        with patch.object(qc, 'lock_task'), patch.object(
            qc, 'review_view', return_value=(rows, None)
        ), patch.object(qc, 'sync_canonical') as sync:
            qc.save_claim_decision(
                conn, 12, 1, 'CLM-1', 'Agree', 'Completed', 'pandu',
                ['Coding', 'Other'], '3',
            )

        sync.assert_called_once_with(conn, 12, 'pandu', 'CLM-1', {
            'qcReview': 'Agree',
            'qcReviewComment': 'Completed',
            'reviewedBy': 'pandu',
            'reviewCategories': ['Coding', 'Other'],
            'points': '3',
            'clinicalDetermination': False,
            'genericReasonCode': False,
            'coding': True,
            'decisionRemarks': False,
            'other': True,
        })

    def test_unsaved_review_area_checkboxes_default_false(self):
        for category in qc.QC_REVIEW_CATEGORIES:
            self.assertFalse(app.review_area_checked({}, category))

    def test_open_claim_editor_restores_all_five_checkbox_states(self):
        details = {
            'qcReview': 'Agree',
            'qcReviewComment': 'Completed',
            'clinicalDetermination': True,
            'genericReasonCode': False,
            'coding': True,
            'decisionRemarks': False,
            'other': True,
        }
        metadata = ('', '', '', {
            'claimsForReviews': [{
                'claimNumber': 'CLM-1',
                'qcReviewDetails': details,
            }],
        })
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = None
        context = MagicMock()
        context.__enter__.return_value = fake_conn
        with patch.object(app, 'task_metadata', return_value=metadata), patch.object(
            app, 'connect_db', return_value=context
        ), patch.object(app, 'claim_conversation_html', return_value='conversation'):
            result = app.open_claim_editor(12, 'CLM-1', app.USERS['pandu'])

        self.assertEqual([entry['value'] for entry in result[3:8]], [True, False, True, False, True])

    def test_edit_save_sends_selected_areas_and_points_to_backend(self):
        conn = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(app, 'require_user', return_value=app.USERS['pandu']), patch.object(
            app, 'connect_db', return_value=context
        ), patch.object(qc, 'save_claim_decision') as save_decision, patch.object(
            app, 'claim_review_summary_html', return_value='<div>Claim summary</div>'
        ):
            result = app.save_claim_edit_form(
                12, 'CLM-1', True, True, True, True, True, '5',
                'Agree', 'Completed', app.USERS['pandu'],
            )

        save_decision.assert_called_once_with(
            conn, 12, app.CASE_ID, 'CLM-1', 'Agree', 'Completed', 'pandu',
            [
                'Clinical Determination', 'Generic Reason Code', 'Coding',
                'Decision Remarks', 'Other',
            ],
            '5',
        )
        self.assertEqual(result[0], 'QC review updated for CLM-1.')

    def test_saving_qc_decision_rejects_unknown_review_areas(self):
        conn = SimpleNamespace(execute=lambda *args, **kwargs: None)
        with patch.object(qc, 'lock_task'), self.assertRaises(ValueError):
            qc.save_claim_decision(
                conn, 12, 1, 'CLM-1', 'Agree', 'Completed', 'pandu',
                ['Unknown category'], '',
            )

    def test_regular_qc_save_does_not_overwrite_edit_only_points(self):
        conn = SimpleNamespace(execute=lambda *args, **kwargs: None)
        rows = [('CLM-1', 'In Progress', {}, {})]
        with patch.object(qc, 'lock_task'), patch.object(
            qc, 'review_view', return_value=(rows, None)
        ), patch.object(qc, 'sync_canonical') as sync:
            qc.save_claim_decision(
                conn, 12, 1, 'CLM-1', 'Agree', 'Completed', 'pandu', ['Coding'],
            )

        self.assertNotIn('points', sync.call_args.args[4])

    def test_claim_review_summary_displays_saved_areas_and_points(self):
        html = app._claim_review_summary_html({
            'claimNumber': 'CLM-1',
            'qcReviewDetails': {
                'qcReview': 'Agree',
                'qcReviewComment': 'Completed',
                'reviewCategories': ['Coding', 'Other'],
                'points': '3.5',
                'reviewedBy': 'pandu',
            },
        })

        self.assertIn('Coding, Other', html)
        self.assertIn('3.5', html)

    def test_completed_claims_html_shows_only_completed_qc_reviews(self):
        claims = [
            {
                'claimNumber': 'DONE-1',
                'qcReviewStatus': 'Agree',
                'qcReviewDetails': {'qcReview': 'Agree', 'qcReviewComment': 'Completed'},
            },
            {
                'claimNumber': 'PENDING-1',
                'qcReviewStatus': 'In Progress',
                'qcReviewDetails': {'qcReview': 'Agree', 'qcReviewComment': 'Completed'},
            },
            {
                'claimNumber': 'CREATED-1',
                'qcReviewStatus': 'Created',
                'qcReviewDetails': {},
            },
        ]
        completed = app.completed_claims({'claimsForReviews': claims})

        self.assertEqual([claim['claimNumber'] for claim in completed], ['DONE-1'])

    def test_full_and_partial_workflow(self):
        original_case = app.CASE_ID
        app.CASE_ID = 9876543210
        try:
            with app.connect_db() as conn:
                try:
                    self.assertEqual(conn.execute(
                        'SELECT count(*) FROM pic_master.claim_details WHERE case_id = %s',
                        (app.CASE_ID,),
                    ).fetchone()[0], 0)
                    claims = [{'Claim ID': f'TEST-CLAIM-{i}'} for i in range(3)]
                    for claim in claims:
                        conn.execute(
                            'INSERT INTO pic_master.claim_details (case_id, claim_number, claim_data) VALUES (%s, %s, %s)',
                            (app.CASE_ID, claim['Claim ID'], app.Jsonb(claim)),
                        )
                    ids = [c['Claim ID'] for c in claims]
                    conn.execute("UPDATE pic_master.claim_details SET qc_status = 'Completed' WHERE case_id = %s AND claim_number = %s", (app.CASE_ID, ids[2]))
                    self.assertEqual(len(qc.eligible_claims(conn, app.CASE_ID)), 2)
                    # Full review always gets all eligible claims, even if a subset is sent.
                    task_id = app.persist_task(conn, app.TASK_TYPES[0], ids[:1], 'Full review')
                    self.assertEqual(len(qc.review_view(conn, task_id)[0]), 2)
                    self.assertTrue(all(r[1] == 'Created' for r in qc.review_view(conn, task_id)[0]))
                    self.assertEqual(qc.eligible_claims(conn, app.CASE_ID), [])
                    with self.assertRaises(ValueError):
                        app.persist_task(conn, app.TASK_TYPES[1], ids[:1], 'Duplicate')
                    self.assertEqual(qc.start_next(conn, task_id, app.CASE_ID, app.ACTOR_ID), ids[0])
                    self.assertEqual(qc.start_next(conn, task_id, app.CASE_ID, app.ACTOR_ID), ids[0])
                    with self.assertRaises(ValueError):
                        qc.save_review(conn, task_id, app.CASE_ID, ids[1], 'Approved', '', True, app.ACTOR_ID)
                    with self.assertRaises(ValueError):
                        qc.save_review(conn, task_id, app.CASE_ID, ids[0], '', '', True, app.ACTOR_ID)
                    qc.save_review(conn, task_id, app.CASE_ID, ids[0], 'Needs Correction', 'Check coding', False, app.ACTOR_ID)
                    self.assertEqual(qc.review_view(conn, task_id)[1][2]['notes'], 'Check coding')
                    canonical = conn.execute(
                        'SELECT task_canonical FROM pic_master.task_details WHERE task_id = %s',
                        (task_id,),
                    ).fetchone()[0]
                    details = canonical['claimsForReviews'][0]['qcReviewDetails']
                    self.assertEqual(details, {'outcome': 'Needs Correction', 'notes': 'Check coding', 'reviewedBy': app.ACTOR_ID})
                    qc.save_review(conn, task_id, app.CASE_ID, ids[0], 'Approved', 'Checked', True, app.ACTOR_ID)
                    self.assertEqual(qc.review_view(conn, task_id)[1][0], ids[1])
                    # Repeated submission must not complete the next claim.
                    with self.assertRaises(ValueError):
                        qc.save_review(conn, task_id, app.CASE_ID, ids[0], 'Approved', '', True, app.ACTOR_ID)
                    qc.save_review(conn, task_id, app.CASE_ID, ids[1], 'Rejected', 'Reviewed', True, app.ACTOR_ID)
                    self.assertIsNone(qc.review_view(conn, task_id)[1])
                    self.assertEqual(conn.execute('SELECT task_status FROM pic_master.task WHERE task_id = %s', (task_id,)).fetchone()[0], 'Completed')
                    payload = conn.execute('SELECT task_canonical FROM pic_master.task_details WHERE task_id = %s', (task_id,)).fetchone()[0]
                    self.assertTrue(all(c['qcReviewStatus'] == 'Completed' for c in payload['claimsForReviews']))
                    self.assertEqual(conn.execute('SELECT qc_status FROM pic_master.claim_details WHERE case_id = %s AND claim_number = %s', (app.CASE_ID, ids[0])).fetchone()[0], 'Completed')
                    conn.execute("UPDATE pic_master.claim_details SET qc_status = NULL WHERE case_id = %s AND claim_number = %s", (app.CASE_ID, ids[2]))
                    partial = app.persist_task(conn, app.TASK_TYPES[1], ids[2:], 'Partial')
                    self.assertEqual(len(qc.review_view(conn, partial)[0]), 1)
                    self.assertEqual(len(app.review_outputs(conn, partial)), 11)
                finally:
                    conn.rollback()
        finally:
            app.CASE_ID = original_case


if __name__ == '__main__':
    unittest.main()
