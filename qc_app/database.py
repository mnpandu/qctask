"""PostgreSQL connections and schema initialization."""

import os
from pathlib import Path

import psycopg

from . import config


def connect_db():
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        connect_timeout=5,
    )


def initialize_db():
    with connect_db() as conn:
        is_new = conn.execute("SELECT to_regclass('pic_master.task') IS NULL").fetchone()[0]
        conn.execute(
            (Path(__file__).resolve().parent.parent / "schema.sql").read_text(encoding="utf-8-sig")
        )
        # Carry forward tasks saved by the earlier version on the first upgrade.
        if is_new and conn.execute("SELECT to_regclass('public.task') IS NOT NULL").fetchone()[0]:
            conn.execute(
                """
                INSERT INTO pic_master.task
                    (task_id, task_name, task_status, assigned_to_name, created_dts,
                     task_cmpled_dts, case_id, task_comment, created_by, created_by_name)
                SELECT t.id, t.task_name, t.status, t.assigned_to, t.created_on,
                       t.completed_on, %s, d.details->>'comments', %s, %s
                FROM public.task t LEFT JOIN public.task_details d ON d.task_id = t.id
            """,
                (config.CASE_ID, config.ACTOR_ID, config.ACTOR_NAME),
            )
            conn.execute(
                """
                INSERT INTO pic_master.task_details (task_id, task_canonical, created_by, updated_dts)
                SELECT t.id,
                       jsonb_build_object('claimsForReviews', COALESCE(
                           (SELECT jsonb_agg(jsonb_build_object('claimNumber', c->>'Claim ID'))
                            FROM jsonb_array_elements(COALESCE(d.details->'claims', '[]'::jsonb)) AS c),
                           '[]'::jsonb)),
                       %s, d.updated_on
                FROM public.task t LEFT JOIN public.task_details d ON d.task_id = t.id
            """,
                (config.ACTOR_ID,),
            )
            conn.execute("""
                SELECT setval(pg_get_serial_sequence('pic_master.task', 'task_id'),
                              COALESCE(max(task_id), 1), count(*) > 0)
                FROM pic_master.task
            """)
