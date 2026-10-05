# QC tasks

Run `python app.py` to start Gradio with a public share link. Install dependencies
with `python -m pip install -r requirements.txt` if needed.

## Code structure

`app.py` is the entry point: initialize the database, create the interface, then
launch it. Importing it does not create Gradio components or connect to PostgreSQL.
Use `from qc_app.ui import create_app` to build an independent interface in another
runner or test. Database initialization remains an explicit startup step.

The application is organized by responsibility:

- `qc_app/config.py` and `identity.py`: environment settings, choices, and session identity.
- `qc_app/database.py` and `repository.py`: connection/schema setup and task read queries.
- `qc_app/task_service.py` and `messaging_service.py`: mutations using caller-owned transactions.
- `claim_workflow.py`: claim eligibility, locking, review decisions, and canonical JSON synchronization.
- `qc_app/tasks.py`, `claims.py`, `messaging.py`, `notifications.py`, and `session.py`:
  Gradio callbacks, including transaction boundaries and user-facing results.
- `qc_app/presentation.py`: pure HTML and label formatting with escaped content.
- `qc_app/ui.py` and `panels.py`: interface composition and claim panel event wiring.
- `qc_app/assets/`: CSS and JavaScript, loaded relative to the module location.

Services do not import Gradio. They accept an existing connection so related writes
commit or roll back together. UI callbacks translate workflow errors into Gradio
messages. Shared configuration is accessed through the config module, so test
overrides apply consistently across modules.

Run `python -m unittest discover -v` for UI construction checks and the workflow
suite. The workflow integration test requires the configured PostgreSQL database
with `schema.sql` already applied; its data changes are rolled back. UI construction
tests use mocked database access and do not launch a server.

Formatting and import checks are configured in `pyproject.toml`. With Ruff installed,
run `python -m ruff check .` and `python -m ruff format --check .`.

Sign in as `pandu` (Pandu, QC Nurse) or `regine` (Regine, Nurse). Each browser
session keeps its own selected user. This is a simple username selector, not
password-protected authentication; do not expose it publicly for sensitive data.
Use Sign out before selecting a different user in the same browser.
Both Nurse and QC Nurse roles can perform all task and claim review operations,
including creating, editing, assigning, completing, and deleting tasks, saving QC
reviews, and sharing conversation notes.

Claims are read exclusively from `pic_master.claim_details` in PostgreSQL.
Startup does not import or generate claims. Task creation queries this table for
the current case's eligible claims: QC status NULL, empty/whitespace, Released, or Returned for Corrections. Creating a task changes
its claims to Created.

Choose a review type, review claims, enter comments, and click Create. Full review
includes every eligible claim; partial review lets you choose a subset. Eligibility
is checked again when saving, with a per-case database lock to prevent duplicate
reservations from simultaneous task creation.

Click a saved task, then Review Claims. Each clickable claim row in the popup displays Claim #,
No of Lines, DOS From / To, MBI, Focus Code, PTAN, NPI, Resp Rcvd, Claim Decision,
QC Review, ADR Sent Date, and TOB from its existing claim JSON. Missing metadata
is displayed as ?. Click a claim row to expand its existing details and review controls. Expand a claim and select QC Review
(Agree or Returned for Corrections) and QC Review Comment (Completed or Correction Required).
Choose any applicable Review Areas (Clinical Determination, Generic Reason Code,
Coding, Decision Remarks, or Other) and enter Contract Points and Nurse Points as needed. Save writes the
decision, comment, selected areas, and both points fields to the task's canonical JSON. The
last saved review completes the task automatically.

Completed claims appear as rows in QC Review Information with an Edit button on
each row. Agreed claims remain editable: both roles can update review areas and
points or change Agree to Action Required. Edit opens a popup to change that claim's QC decision/comment or continue
its conversation. The RACF/user recipient is optional; leaving it blank sends the
note to the current user. When reopening a conversation, the recipient defaults
to the previous participant; you can change it before sending. Sending a note stores
it with the claim and creates an unread in-app alert for that user and the task's
assigned user. New assignments also create an alert. Alerts appear in the top-right
button and refresh every 15 seconds. The user name shown in the conversation is the
selected login name; because login has no password, the app does not verify identity.

## PostgreSQL

Connection defaults: localhost:5432, database postgres, user postgres, password postgres.
Override using PGHOST, PGPORT, PGDATABASE, PGUSER, and PGPASSWORD.

`schema.sql` defines the PostgreSQL equivalents of the reference tables:

- `pic_master.task`: task metadata, task_status, Active record status, case ID,
  comments, assignment, and creation/update audit fields.
- `pic_master.task_details`: a generated task_details_id, task_id foreign key,
  task_canonical JSONB, Active record status, and audit fields.
- `pic_master.claim_details`: claim JSON, qc_status, and updated_dts, keyed by case ID and
  claim number. Review outcomes and notes live only in task_details.task_canonical.
- `pic_master.qc_claim_messages` and `pic_master.qc_notifications`: per-claim
  conversation notes and unread in-app alerts only for the note's named recipient.

The claim payload uses this structure (claim numbers remain strings):

```json
{"claimsForReviews": [{"claimNumber": "DEMO-CLM-0001"}]}
```

Comments and workflow status are columns on task. As claims are reviewed,
each canonical claim object also receives qcReviewStatus and qcReviewDetails.
Task, claim, and canonical writes commit in one transaction.
PostgreSQL JSONB replaces the Oracle CLOB shown in the reference.

QC_CASE_ID defaults to numeric demo case 1. QC_USER_ID and QC_USER_NAME are
legacy audit-label fallbacks used for old task migration and non-interactive
helper calls. Interactive users are identified by the selected Pandu/Regine
session name; the username-only selector does not authenticate identity.

On the first schema creation, tasks from the earlier app's public.task and
public.task_details tables are copied into pic_master with their IDs preserved.
The earlier tables are left intact. Later launches use pic_master only.

Run `python -m unittest test_claim_workflow -v` for PostgreSQL integration checks.
Test records are rolled back.

Claim membership and review order live in task_details.task_canonical only.
claim_details has no task_id or qc_review_order columns. QC status progresses
from NULL (initial) to Created (task created), then Agree or Returned for Corrections.
NULL, empty/whitespace, Released, and Returned for Corrections are eligible; Agree is not.
Delete Task removes both task and task_details rows and sets every linked claim
to Released, including previously reviewed claims. The deletion and release commit
in one transaction.
Task workflow status still starts at Not Started. The schema upgrade removes the
two obsolete claim columns and preserves claim review details.

Expanded claims include an Attachments table (File Name, Doc Type, Work Type,
Receipt Date) from `claim_data.attachments`, and Decision Details from
`claim_data.decisionDetails` or matching top-level fields. These sections display
source claim metadata above the QC Review controls. Empty attachment lists show
?No records to display?; missing decision values show ?. Attachment metadata uses
`fileName`, `docType`/`documentType`, `workType`, and `receiptDate` keys.

Each task has a Mentor checkbox. Checking or unchecking it immediately saves
`pic_master.task.mentor` and updates the task audit fields. Both Nurse and QC Nurse
can change it, including on completed tasks. Existing and new tasks default to unchecked.

Saving points and QC Review or sending a conversation note keeps the claim editor
open. Use Close at the top of the editor to leave it.

The Comments tab shows `pic_master.task_comments`: one creation entry containing
its task comment, and one completion entry containing a snapshot of reviewed
claims only (claim number, Contract Points, Nurse Points, review areas, final
status, QC decision and comment). Claim saves add no entry while work is in
progress. Automatic completion on the last reviewed claim and Complete Task both
record the snapshot in the same transaction. Later edits refresh the existing completion summary without adding another entry. Comments retain their task ID even if the task is deleted. The tab
loads when selected and has Refresh Comments. Existing tasks are not backfilled. Task comment edits also refresh their existing creation entry.
