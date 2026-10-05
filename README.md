# QC task workspace

This Gradio application manages task creation, claim QC reviews, task completion,
claim conversations, alerts, and task lifecycle comments for one configured case.
The visible tabs are **Tasks**, followed by **Comments**. Reporting has been removed
from the interface.

## Setup and launch

Run these commands from `qctask`:

```powershell
python -m pip install -r requirements.txt
python app.py
```

PostgreSQL must be running and accessible. Startup applies `schema.sql`, creates
missing tables, and performs the included schema upgrades before opening Gradio.
Startup reads existing claims; it does not generate or import claim data.
`app.py` currently launches with `share=True`, which creates a public share link.
The username selector has no password authentication; it does not verify identity.

| Setting | Default | Purpose |
| --- | --- | --- |
| `PGHOST` | `localhost` | Database host |
| `PGPORT` | `5432` | Database port |
| `PGDATABASE` | `postgres` | Database name |
| `PGUSER` | `postgres` | Database user |
| `PGPASSWORD` | `postgres` | Database password |
| `QC_CASE_ID` | `1` | Numeric case used for task and claim operations |
| `QC_USER_ID` | `demo` | Legacy/noninteractive audit ID fallback |
| `QC_USER_NAME` | `Demo User` | Legacy/noninteractive audit name fallback |

## Sign in and permissions

Choose `pandu` (Pandu, QC Nurse) or `regine` (Regine, Nurse), then click **Sign in**.
Each browser session keeps its selected user independently. Use **Sign out** to
switch users in the same browser.

Both roles can create tasks, self-assign, complete and delete tasks, change Mentor,
review and edit claims, send notes, read alerts, and view Comments. Assignment does
not restrict editing to the assigned user. Interactive mutations validate the
registered session user and use that user's RACF/name for audit fields.

## End-to-end task flow

1. Sign in and open **Tasks**.
2. Select **QC Nurse Full Review** or **QC Nurse Partial Review** in **Create Task**.
3. Inspect eligible claims. Full review includes every eligible claim; partial
   review lets you select a subset. Enter an optional task comment and click **Create**.
4. The task starts at **Not Started**, linked claims become **Created**, and a
   creation entry is saved to Comments, even if the task comment is blank.
5. Expand the task. Use **SELF ASSIGN** if needed; this sets the task to
   **In Progress**, records your RACF/name, and creates an assignment alert.
6. Set the task's **Mentor** checkbox if applicable. Checking or unchecking saves
   immediately; there is no separate save button for Mentor.
7. Click **Review Claims**, then click a claim row to expand its review controls.
8. Save a valid QC decision/comment, review areas, Contract Points, and Nurse Points.
   Saving a claim alone does not create a task lifecycle comment while work remains.
9. Saving the last reviewed claim completes the task automatically. Alternatively,
   use **Complete Task** to finish manually with only some claims reviewed.
10. Open **Comments** to see creation comments and the completion summary of reviewed
    claims. Later edits refresh the existing entry instead of creating duplicates.

**Refresh Tasks** reloads task rows and their claim panels. **Cancel** during task
creation discards the creation form without creating a task.

## Task eligibility and lifecycle rules

### Creating tasks

Claims come exclusively from `pic_master.claim_details` for the configured case.

| Current claim QC status | Eligible for task creation? |
| --- | --- |
| NULL, empty, or whitespace | Yes |
| Released | Yes |
| Returned for Corrections | Yes |
| Created or In Progress | No |
| Agree or Completed | No |

Full review includes all currently eligible claims, even if a caller supplies a
subset. Partial review requires at least one selected eligible claim. Repeated
claim IDs are removed. Eligibility is rechecked during save under a per-case
transaction lock, preventing simultaneous creation from reserving the same claims.
Task comments have a maximum length of 4,000 characters.

### Assignment, Mentor, completion, and deletion

- **SELF ASSIGN** assigns to the current user, sets In Progress, and clears the
  task completion date. An alert is created only when the assigned RACF changes.
- **Mentor** is a per-task Boolean, defaulting to unchecked. Both roles can change
  it on active tasks, including completed tasks. Saving updates task audit fields.
- Automatic completion occurs when every linked claim has a reviewed status:
  Agree, Returned for Corrections, or Completed. Returned for Corrections counts
  as reviewed; task completion does not mean every claim was agreed.
- **Complete Task** releases linked claims whose current status is Created,
  preserves reviewed claims, and completes the task. Only actually reviewed claims
  are included in its completion comment. The legacy In Progress claim status is
  not released by this operation.
- Self-assign and Complete Task are disabled for completed tasks. A stale or
  repeated request refreshes the task view without rewriting it.
- **DELETE TASK** removes task and task-details rows and sets every linked claim
  to Released, including previously reviewed claims. Its claim conversations and
  alerts are removed through database foreign-key cascades. The task's lifecycle Comments
  are also deleted in the same transaction.
- Task, claim-status, canonical JSON, alerts, and lifecycle-comment changes commit
  together in their owning transaction; errors roll back that operation.

## Review Claims layout

The popup has a light column banner. Each clickable claim row displays these
columns before expansion, in this order:

| Column | Value source |
| --- | --- |
| Claim # | Linked claim number |
| No of Lines | Claim metadata |
| DOS From / To | Combined service dates or Date of Service |
| MBI | Claim metadata |
| Focus Code | Claim metadata |
| PTAN | Claim metadata |
| NPI | Claim metadata |
| Resp Rcvd | Claim metadata |
| Claim Decision | Claim metadata |
| QC Review | Current claim QC status |
| ADR Sent Date | Claim metadata |
| TOB | Claim metadata |

There is no separate duplicate claims table. Clicking a row opens its content;
expanding another claim closes the other claim panels. Missing displayed metadata
uses `?`; zero values remain visible.

Each expanded claim contains existing claim details, **Attachments**, **Decision
Details**, and **QC Review** controls. Source attachments and decision details are
read-only and are distinct from the editable QC decision.

### Attachments

The table has **File Name**, **Doc Type**, **Work Type**, and **Receipt Date**.
It reads `attachments` or `claimAttachments` from claim JSON. Records use
`fileName`/`name`, `docType`/`documentType`, `workType`, and
`receiptDate`/`receivedDate`. Empty lists show **No records to display**.
The table displays attachment metadata; it does not upload files or provide a
file-download implementation.

### Decision Details

Displays **Decision**, **Decision Date**, **Associated DCN**, **Demand Bill**,
**Denial Reason**, **Generic Reason Code**, **Pre MR Original Reimbursement**,
**Post MR Original Reimbursement**, **Total Reimbursement Savings**, and
**Decision Remarks**. Values come from `decisionDetails` or `claimDecisionDetails`,
with top-level claim fields as fallbacks. Metadata lookup accepts equivalent
capitalization, spaces, and underscores.

## QC decisions and business rules

| Review context | Available QC decision | QC Review Comment | Saved claim QC status |
| --- | --- | --- | --- |
| No prior reviewed task | Agree | Completed, automatically selected | Agree |
| No prior reviewed task | Action Required | Return for Correction or Response Requested | Returned for Corrections |
| Reviewed in an earlier task | Re-review | Return of Correction | Returned for Corrections |
| Reviewed in an earlier task | Re-review | Complete | Completed |

A prior review means the same claim appears in a task with a lower task ID and a
nonblank saved `qcReview` in its canonical review details. Saving Action Required
in the **same task** does not trigger Re-review. The user can continue editing that
review with Agree or Action Required. When that reviewed claim is selected into a
later task, the new task offers Re-review instead.

Released claims with no prior saved QC review retain Agree/Action Required in a
later task. Deleting an earlier task removes its canonical review history, so that
deleted history no longer participates in Re-review detection. Legacy outcome-only
reviews do not satisfy the `qcReview` history check.

Agreed claims remain editable: both roles can change review areas and points or
switch to Action Required within the same first-review task. A Re-review saved with
Complete locks its QC decision/comment in the interface; its edit popup still
allows points and review-area updates while keeping Re-review/Complete.

Available review areas are **Clinical Determination**, **Generic Reason Code**,
**Coding**, **Decision Remarks**, and **Other**. Multiple areas may be selected;
duplicate areas are removed and unknown areas are rejected.

**Contract Points** and **Nurse Points** are independent optional text fields with
the same UI behavior: one line and a 10-character entry limit. Backend validation
allows up to 100 characters per field. Existing `points` values remain Contract
Points; Nurse Points uses `nursePoints`. Neither field requires numeric input.
Omitted points in backend helper calls preserve the existing value; saving an empty
textbox explicitly clears that field.

Review saves validate claim membership and permitted decision/comment combinations,
lock the task, update claim QC status, update canonical review details and audit ID,
and recalculate task completion. Reviewed claim rows appear in **QC Review
Information** with an **Edit** button. The editor's **Save Points and QC Review**
updates the summary and stays open. Use **Close** at the top to leave the editor.

## Claim conversations and alerts

Open **Edit** on a reviewed claim to access **Conversation and notes**.
The recipient RACF/user name is optional: blank sends to yourself. When reopened,
the editor defaults to the previous conversation participant, or yourself when
there is no previous message. The recipient can be changed before sending.

Notes must contain 1-4,000 characters after trimming. Recipient names are limited
to 100 characters. Notes are associated with the selected task and claim and use
the selected user's RACF as sender. Sending a note saves the message and creates an
unread alert for the named recipient only; the task assignee does not receive an
additional alert unless named as recipient. Arbitrary recipient RACFs can be stored;
the current login selector offers only Pandu and Regine.

**Send Note** refreshes the conversation, clears the note textbox, and keeps the
claim editor open. Sending notes does not create task lifecycle Comments.
The **Alerts** badge refreshes every 15 seconds. Open Alerts to see unread items,
use **Mark Read** to mark your alerts read, and **Close** to dismiss the alert panel.

## Comments tab

Comments follows Tasks. Each entry starts collapsed and shows only **Date**,
**Task ID**, **Task Name**, and **RACF - Name**. Click the row to expand or collapse
it. Expanded entries show a heading such as **Task 238 - Created** and **Comments**.
Completed entries additionally show Claim #, Contract Points, Nurse Points, Review
Areas, Final Status, QC Review, and QC Comment for each reviewed claim.

Business rules:

- Creating a task creates one Created entry containing its task comment.
- Individual claim saves while a task is in progress add no lifecycle entry.
- Automatic or manual completion creates one Completed entry for the task.
- The completion entry includes only claims with a reviewed status and a saved QC
  decision or legacy review outcome. Released/unreviewed claims are excluded.
- If no claims were reviewed, manual completion displays **No reviewed claims**.
- The database enforces one entry per task/event type. Repeat completion adds no
  duplicate. Later claim edits refresh the existing completion details, including
  both points fields, review areas, decision/comment, and final status.
- Task comment edits refresh the existing Created entry. Task-name metadata is
  refreshed on existing entries. Refreshes retain the original comment date/author.
- Existing completion entries can be refreshed during subsequent edits; a claim
  edit does not create an entry for an unfinished task that has never completed.
- Select Comments or click **Refresh Comments** to load current data. Entries are
  ordered newest first. Historic tasks are not automatically given new lifecycle
  comments; existing comment rows have task-name metadata backfilled when available.
- Deleting a task deletes its corresponding Created and Completed Comments entries.
  Conversation messages remain a separate feature.

## Data model and example payload

| Table | Responsibility |
| --- | --- |
| `pic_master.task` | Task metadata, workflow status, assignment, comment, Mentor, audit fields |
| `pic_master.task_details` | Task claim membership/order and canonical JSON review details |
| `pic_master.claim_details` | Source claim JSON and current claim QC status, keyed by case/claim |
| `pic_master.qc_claim_messages` | Per-task, per-claim conversations |
| `pic_master.qc_notifications` | Unread/read alerts for named recipients and assignment alerts |
| `pic_master.task_comments` | Creation comment and refreshable completion summary per task |

Claim membership/order lives only in `task_details.task_canonical`; source claims
have no `task_id` or `qc_review_order`. Source decision metadata is not overwritten
by a QC decision. Task canonical JSON uses string claim numbers:

```json
{
  "claimsForReviews": [
    {
      "claimNumber": "DEMO-CLM-0001",
      "qcReviewStatus": "Agree",
      "qcReviewDetails": {
        "qcReview": "Agree",
        "qcReviewComment": "Completed",
        "reviewedBy": "regine",
        "reviewCategories": ["Coding"],
        "coding": true,
        "points": "2",
        "nursePoints": "3"
      }
    }
  ]
}
```

Example source `claim_data` fields:

```json
{
  "noOfLines": 3,
  "dosFrom": "04/20/2023",
  "dosTo": "04/21/2023",
  "mbi": "EXAMPLE-MBI",
  "focusCode": "EXAMPLE",
  "ptan": "396053",
  "npi": "1265432165",
  "responseReceived": "Yes",
  "claimDecision": "Y",
  "adrSentDate": "07/12/2023",
  "typeOfBill": "111",
  "attachments": [
    {"fileName": "review.pdf", "documentType": "Medical", "workType": "Review", "receiptDate": "07/12/2023"}
  ],
  "decisionDetails": {
    "decision": "Full Denial",
    "decisionDate": "07/21/2023",
    "associatedDCN": "",
    "demandBill": "",
    "denialReason": "59CON",
    "genericReasonCode": "GAI02",
    "preMROriginalReimbursement": "",
    "postMROriginalReimbursement": "",
    "totalReimbursementSavings": "",
    "decisionRemarks": "Full denial"
  }
}
```

`schema.sql` includes upgrades for Mentor and task-comments metadata and removes
obsolete duplicate claim-review columns after migrating their data into canonical
JSON. On initial schema creation, legacy `public.task`/`public.task_details` records
are copied with task IDs preserved; legacy tables remain intact.
`task_comments_schema.sql` applies the comments table and its metadata upgrade alone.

## Development and verification

`app.py` initializes the database, builds the UI, then launches. Importing it does
not create components or connect to PostgreSQL. `qc_app.ui.create_app()` builds an
independent interface; callers still own initialization and launch.

| Module | Responsibility |
| --- | --- |
| `qc_app/config.py`, `identity.py`, `session.py` | Settings, session validation, sign-in/out |
| `qc_app/database.py`, `repository.py` | Schema/connection setup and task queries |
| `qc_app/task_service.py`, `messaging_service.py` | Mutations inside caller-owned transactions |
| `claim_workflow.py` | Eligibility, locking, decisions, legacy sequential review, canonical synchronization |
| `task_comments.py`, `qc_app/comments.py` | Lifecycle-comment persistence and display |
| `qc_app/tasks.py`, `claims.py`, `messaging.py`, `notifications.py` | UI callbacks and error translation |
| `qc_app/ui.py`, `panels.py`, `presentation.py`, `assets/` | Interface, rendering, styles, row alignment |

The legacy sequential backend supports start-next, draft, and complete operations;
the current interface uses direct per-claim QC review controls. Reporting modules
remain in the codebase but are not exposed as a tab or link.

Run from `qctask` after schema initialization:

```powershell
python -m unittest discover -v
```

The suite includes UI construction checks, PostgreSQL workflow integration,
permissions, reviewed-claim editing, Comments creation/completion/refresh, and
presentation escaping. Database integration tests roll back their test changes.
UI construction tests use mocks and do not launch a server. With Ruff installed,
repository style checks are available through:

```powershell
python -m ruff check .
python -m ruff format --check .
```
