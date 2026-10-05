"""Task lifecycle comments, written in the task transaction."""


def record_creation(conn, task_id, actor, actor_name=""):
    conn.execute(
        """
        INSERT INTO pic_master.task_comments
            (task_id, case_id, event_type, comment_text, created_by, task_name, created_by_name)
        SELECT task_id, case_id, 'Created', COALESCE(task_comment, ''), %s, task_name, %s
        FROM pic_master.task WHERE task_id = %s
        ON CONFLICT (task_id, event_type) DO NOTHING
        """, (actor, actor_name, task_id),
    )


def record_completion(conn, task_id, actor, actor_name="", existing_only=False):
    condition = (
        "EXISTS (SELECT 1 FROM pic_master.task_comments c WHERE c.task_id = t.task_id AND c.event_type = 'Completed')"
        if existing_only else "t.task_status = 'Completed'"
    )
    conn.execute(
        f"""
        INSERT INTO pic_master.task_comments
            (task_id, case_id, event_type, comment_text, claim_reviews, created_by, task_name, created_by_name)
        SELECT t.task_id, t.case_id, 'Completed', 'Task completed.',
            COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'claimNumber', item->>'claimNumber',
                    'contractPoints', item->'qcReviewDetails'->>'points',
                    'nursePoints', item->'qcReviewDetails'->>'nursePoints',
                    'reviewAreas', COALESCE(item->'qcReviewDetails'->'reviewCategories', '[]'::jsonb),
                    'finalStatus', item->>'qcReviewStatus',
                    'qcReview', COALESCE(item->'qcReviewDetails'->>'qcReview', item->'qcReviewDetails'->>'outcome'),
                    'qcComment', COALESCE(item->'qcReviewDetails'->>'qcReviewComment', item->'qcReviewDetails'->>'notes')
                ) ORDER BY position)
                FROM jsonb_array_elements(d.task_canonical->'claimsForReviews')
                    WITH ORDINALITY AS claims(item, position)
                WHERE item->>'qcReviewStatus' IN ('Agree', 'Returned for Corrections', 'Completed')
                  AND (NULLIF(item->'qcReviewDetails'->>'qcReview', '') IS NOT NULL
                    OR NULLIF(item->'qcReviewDetails'->>'outcome', '') IS NOT NULL)
            ), '[]'::jsonb), %s, t.task_name, %s
        FROM pic_master.task t JOIN pic_master.task_details d USING (task_id)
        WHERE t.task_id = %s AND {condition}
        ON CONFLICT (task_id, event_type) DO UPDATE
        SET claim_reviews = EXCLUDED.claim_reviews, task_name = EXCLUDED.task_name
        """, (actor, actor_name, task_id),
    )


def refresh_existing(conn, task_id, actor):
    conn.execute(
        """
        UPDATE pic_master.task_comments c
        SET task_name = t.task_name,
            comment_text = CASE WHEN c.event_type = 'Created' THEN COALESCE(t.task_comment, '') ELSE c.comment_text END
        FROM pic_master.task t WHERE c.task_id = t.task_id AND t.task_id = %s
        """, (task_id,),
    )
    record_completion(conn, task_id, actor, existing_only=True)
