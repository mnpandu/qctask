"""Task read queries; no Gradio dependency."""

from . import config, database


def list_tasks(conn):
    rows = conn.execute(
        """
        SELECT t.task_id, t.task_name, t.task_status,
               COALESCE(t.assigned_to_name, t.assigned_to, 'Unassigned'),
               to_char(t.created_dts, 'YYYY-MM-DD HH24:MI:SS'),
               COALESCE(to_char(t.task_cmpled_dts, 'YYYY-MM-DD HH24:MI:SS'), ''),
               COALESCE(jsonb_array_length(d.task_canonical->'claimsForReviews'), 0),
               COALESCE(t.task_comment, '')
        FROM pic_master.task t LEFT JOIN pic_master.task_details d ON d.task_id = t.task_id
        WHERE t.case_id = %s AND t.status = 'Active'
        ORDER BY t.task_id DESC
    """,
        (config.CASE_ID,),
    ).fetchall()
    return [list(row) for row in rows]


def task_metadata(task_id):
    with database.connect_db() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(t.assigned_to, ''), COALESCE(t.created_by, ''),
                   COALESCE(created_by_name, ''), d.task_canonical
            FROM pic_master.task t JOIN pic_master.task_details d USING (task_id)
            WHERE t.task_id = %s AND t.case_id = %s AND t.status = 'Active'
        """,
            (task_id, config.CASE_ID),
        ).fetchone()
    return row


def task_mentor(task_id):
    with database.connect_db() as conn:
        row = conn.execute(
            "SELECT mentor FROM pic_master.task WHERE task_id = %s AND case_id = %s AND status = 'Active'",
            (task_id, config.CASE_ID),
        ).fetchone()
    return bool(row and row[0] is True)
