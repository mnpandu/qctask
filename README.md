# QC tasks ? Oracle

Run from qctask:

```powershell
python -m pip install -r requirements.txt
python app.py
```

The app loads connection settings from `qctask/.env`; process environment variables
can override them. Required keys: ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN,
ORACLE_SCHEMA. `.env` is excluded from version control. See `.env.example`.

At startup, `initialize_db()` creates missing tables and indexes in ORACLE_SCHEMA.
It checks the Oracle catalog first, so later launches preserve existing objects and
rows. It does not alter an existing table to match a new schema definition.
Oracle DDL auto-commits, so initialization runs before workflow transactions.
`qc_store` in schema.sql and application SQL is a logical qualifier replaced by the
configured schema by the connection wrapper; run initialization through Python:

```powershell
python -c "from qc_app.database import initialize_db; initialize_db()"
```

Tables use a QCTASK_ prefix to coexist with the separate advanced-search tables:

- QCTASK_TASK: task metadata, assignment, status and audit timestamps.
- QCTASK_TASK_DETAILS: task membership and review details as JSON in a CLOB.
- QCTASK_CLAIM_DETAILS: claim payload JSON, eligibility/QC status, case and claim key.
- QCTASK_CLAIM_MESSAGES: per-claim conversations.
- QCTASK_NOTIFICATIONS: recipient alerts.
- QCTASK_CASE_LOCKS: one persistent row per case for transaction locking.

Claims are read from QCTASK_CLAIM_DETAILS for QC_CASE_ID (default 1).
Startup does not generate claims or copy data from another database or app.
Load your claim records into this table before creating tasks.
The claim_data document uses the UI keys listed in qc_app/config.py, such as
"Claim ID", "Provider ID", "Claim Status", and "Billed Amount".

Full reviews reserve all eligible claims; partial reviews reserve selected claims.
A per-case SELECT FOR UPDATE lock serializes creation and review mutations.
Changes commit together on success and roll back on exceptions. JSON review
processing is performed in Python; CLOBs are materialized before connections close.
Identity IDs are retrieved with Oracle RETURNING INTO output binds.

The existing UI, role permissions, review decisions, reporting and notifications
remain available. Select Pandu (QC Nurse) or Regine (Nurse) to sign in. This is a
username selector, not password authentication. The current launcher uses a public
Gradio share link.

Run tests after initialization:

```powershell
python -m unittest discover -v
```

Workflow integration tests use the configured Oracle database and roll back their
test records. Unit tests cover permissions, reporting and UI construction.

Code: qc_app/database.py handles connections and schema initialization;
qc_app/task_service.py and messaging_service.py handle transactions supplied by
callers; claim_workflow.py implements claim decisions; qc_app/ui.py builds Gradio.
