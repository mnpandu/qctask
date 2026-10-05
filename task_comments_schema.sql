
CREATE TABLE IF NOT EXISTS pic_master.task_comments (
    comment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id BIGINT NOT NULL,
    case_id NUMERIC(10,0) NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('Created', 'Completed')),
    comment_text TEXT NOT NULL DEFAULT '',
    claim_reviews JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by VARCHAR(100) NOT NULL,
    created_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (task_id, event_type)
);

ALTER TABLE pic_master.task_comments
    ADD COLUMN IF NOT EXISTS task_name VARCHAR(100) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(200) NOT NULL DEFAULT '';
UPDATE pic_master.task_comments c SET task_name = t.task_name
FROM pic_master.task t WHERE c.task_id = t.task_id AND c.task_name = '';
