# QC tasks

Run `python app.py` to start Gradio with a public share link. Install dependencies
with `python -m pip install -r requirements.txt` if needed.

Sign in as `pandu` (Pandu, QC Nurse) or `regine` (Regine, Nurse). Each browser
session keeps its own selected user. This is a simple username selector, not
password-protected authentication; do not expose it publicly for sensitive data.
Use Sign out before selecting a different user in the same browser.

Claims are read exclusively from `pic_master.claim_details` in PostgreSQL.
Startup does not import or generate claims. Task creation queries this table for
the current case's eligible claims: QC status NULL, empty/whitespace, Released, or Returned for Corrections. Creating a task changes
its claims to Created.

Choose a review type, review claims, enter comments, and click Create. Full review
includes every eligible claim; partial review lets you choose a subset. Eligibility
is checked again when saving, with a per-case database lock to prevent duplicate
reservations from simultaneous task creation.

Click a saved task, then Review Claims. Expand a claim and select QC Review
(Agree or Returned for Corrections) and QC Review Comment (Completed or Correction Required).
Choose any applicable Review Areas (Clinical Determination, Generic Reason Code,
Coding, Decision Remarks, or Other) and enter Points as needed. Save writes the
decision, comment, selected areas, and points to the task's canonical JSON. The
last saved review completes the task automatically.

Completed claims appear as rows in QC Review Information with an Edit button on
each row. Edit opens a popup to change that claim's QC decision/comment or continue
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
  conversation notes and unread in-app alerts for the named recipient and
  assigned RACF.

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
