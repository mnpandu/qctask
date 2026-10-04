"""Task read queries; no Gradio dependency."""

from . import config, database


def list_tasks(conn):
    rows = conn.execute(
        """
        SELECT t.task_id, t.task_name, t.task_status,
               COALESCE(t.assigned_to_name, t.assigned_to, 'Unassigned'),
               to_char(t.created_dts, 'YYYY-MM-DD HH24:MI:SS'),
               COALESCE(to_char(t.task_cmpled_dts, 'YYYY-MM-DD HH24:MI:SS'), ''),
               d.task_canonical,
               COALESCE(t.task_comment, '')
        FROM qc_store.qctask_task t LEFT JOIN qc_store.qctask_task_details d ON d.task_id = t.task_id
        WHERE t.case_id = :p1 AND t.status = 'Active'
        ORDER BY t.task_id DESC
    """,
        (config.CASE_ID,),
    ).fetchall()
    result = []
    for row in rows:
        row = list(row)
        row[6] = len((row[6] or {}).get("claimsForReviews", []))
        row[5] = row[5] or ""
        row[7] = row[7] or ""
        result.append(row)
    return result


def task_metadata(task_id):
    with database.connect_db() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(t.assigned_to, ''), COALESCE(t.created_by, ''),
                   COALESCE(created_by_name, ''), d.task_canonical
            FROM qc_store.qctask_task t JOIN qc_store.qctask_task_details d ON d.task_id = t.task_id
            WHERE t.task_id = :p1 AND t.case_id = :p2 AND t.status = 'Active'
        """,
            (task_id, config.CASE_ID),
        ).fetchone()
    return row
