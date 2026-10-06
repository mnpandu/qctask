# Claim QC Review - Business Flows and Rules

## Business purpose

The workspace allows Nurses and QC Nurses to organize claims into review tasks,
record review decisions, identify corrections, record points and review areas,
communicate about claims, and view task comments from creation through completion.

This document describes the current business behavior and provides a basis for a
Business Requirements Document (BRD).

## Business users and responsibilities

| Role | Permitted activities |
| --- | --- |
| Nurse | Create, assign, review, edit, complete, and delete tasks; update Mentor; send notes; manage alerts; view Comments |
| QC Nurse | The same activities as Nurse |

Both roles have equal access to these activities. A task's assigned user does not
have exclusive editing rights. A user must sign in before performing an activity.
The currently available users are Pandu (QC Nurse) and Regine (Nurse).
Users sign out before changing their selected identity.

RACF means the user's identifying name used for assignment, communication, and
recording who performed an activity.

## Workspace navigation

The workspace contains two tabs, in order:

1. **Tasks** - Create and manage tasks, review claims, edit reviews, and send notes.
2. **Comments** - View task creation comments and completed-task claim summaries.

The user's name and unread Alerts count are displayed. Reporting is not available
as a separate tab or link.

## Complete business journey

1. The user signs in and opens Tasks for the current case.
2. The user chooses Full Review or Partial Review.
3. Eligible claims are displayed. Full Review includes all eligible claims; Partial
   Review allows the user to choose a subset.
4. The user optionally enters a task comment and creates the task.
5. The task appears as Not Started. Selected claims are reserved for that task and
   marked Created. A task creation comment is recorded.
6. The user can self-assign the task and select Mentor if applicable.
7. The user opens Review Claims, inspects a claim's attachments and decision
   details, and records a QC decision, comment, review areas, and points.
8. The user repeats the review for the remaining claims. Individual reviews do not
   add separate task Comments while the task remains unfinished.
9. The task completes automatically when all claims have been reviewed, or the user
   selects Complete Task to finish with only some claims reviewed.
10. A completion comment summarizes only the reviewed claims.
11. The user may edit a reviewed claim or send a note. Existing task Comments are
    refreshed when their related saved details change.
12. The user opens Comments to see the latest task comments and claim summaries.

## Task creation

### Review types

| Review type | Claim selection rule |
| --- | --- |
| QC Nurse Full Review | Includes every eligible claim for the case |
| QC Nurse Partial Review | Includes only the eligible claims selected by the user |

At least one eligible claim is required. The task comment is optional and can
contain up to 4,000 characters. Cancel closes the creation form without creating
a task.

### Claim eligibility

| Claim QC status | Available for a new task? |
| --- | --- |
| No status recorded | Yes |
| Released | Yes |
| Returned for Corrections | Yes |
| Created | No |
| In Progress | No |
| Agree | No |
| Completed | No |

Eligibility is checked again when the task is created. A claim that is no longer
eligible cannot be included. Simultaneous task creation must not reserve the same
eligible claim twice. Selecting a claim repeatedly does not create duplicate claim
entries in the task.

A claim returned for corrections may be included in a later review task. Its prior
review determines whether the later task requires Re-review.

### Creation outcome

The task receives a Task ID and the selected task name. Its initial status is
Not Started. Included claims become Created. The creation comment records the task
comment, including a blank comment when no text was entered.

## Task information and actions

The task list shows Task ID, Task Name, Case Number, Status, Assigned To, Created
On, and Completed On. Expanding a task shows assignment and creator details, task
comments, its claims, Mentor, QC Review Information, and task actions.

### Self-assignment

SELF ASSIGN assigns the task to the current user and sets it to In Progress.
An assignment alert is generated when the assigned user changes. Self-assignment
is unavailable after the task is completed. Repeating a completed-task assignment
request does not change the task.

### Mentor

Mentor is an optional checkbox for each task. New and existing tasks start
unchecked unless a user has selected it. Checking or unchecking saves immediately.
Both roles can change Mentor, including on completed tasks. Mentor does not change
claim decisions or task completion rules.

### Refresh

Refresh Tasks displays the latest task and review information. Users should refresh
when another user's work may have changed the task.

## Review Claims - claim list

When the user selects Review Claims, each clickable claim row shows these fields
without needing to expand the claim:

| Order | Field |
| --- | --- |
| 1 | Claim # |
| 2 | No of Lines |
| 3 | DOS From / To |
| 4 | MBI |
| 5 | Focus Code |
| 6 | PTAN |
| 7 | NPI |
| 8 | Resp Rcvd |
| 9 | Claim Decision |
| 10 | QC Review |
| 11 | ADR Sent Date |
| 12 | TOB |

QC Review in the claim row shows the claim's current QC status. The column banner
has a light background. Unavailable claim information displays as `?`.
Clicking a claim row expands its details and review controls. Expanding another
claim closes the other expanded claim sections.

## Expanded claim information

An expanded claim includes existing claim information, Attachments, Decision
Details, and QC Review. Attachments and Decision Details show the source claim
information; changing the QC review does not change that source decision.

### Attachments

The Attachments section displays:

- File Name
- Doc Type
- Work Type
- Receipt Date

When no attachments are available, it displays **No records to display**.
This section displays attachment information; file upload and download are not
part of the current business flow.

### Decision Details

The Decision Details section displays:

- Decision
- Decision Date
- Associated DCN
- Demand Bill
- Denial Reason
- Generic Reason Code
- Pre MR Original Reimbursement
- Post MR Original Reimbursement
- Total Reimbursement Savings
- Decision Remarks

Unavailable values display as `?`. These fields provide context for the QC review
and are not edited through the QC Review controls.

## QC review decisions

### First review and changes within the same task

When a claim has not been reviewed in an earlier task, the available decisions are
Agree and Action Required.

| QC decision | Allowed QC comment | Resulting claim status |
| --- | --- | --- |
| Agree | Completed, selected automatically | Agree |
| Action Required | Return for Correction | Returned for Corrections |
| Action Required | Response Requested | Returned for Corrections |

Saving Action Required does not turn the current task's review into Re-review.
Users can continue editing that claim in the same task and select Agree or Action
Required. Agreed claims remain editable in that same first-review task.

### Re-review in a later task

Re-review is offered when the same claim has a saved QC decision in an earlier
task and is included in a later task. Reviewing a claim repeatedly within its
original task does not count as review in another task.

| QC decision | Allowed QC comment | Resulting claim status |
| --- | --- | --- |
| Re-review | Return of Correction | Returned for Corrections |
| Re-review | Complete | Completed |

For a later task requiring Re-review, Agree and Action Required are not offered.
A claim released without a prior saved QC decision retains first-review choices
when included in another task. A deleted task's review history is no longer used
to determine Re-review. Earlier records containing only an old review outcome,
without a QC decision, do not trigger Re-review.

After Re-review is saved with Complete, its decision and comment cannot be changed
through the review controls. Points and review areas can still be updated through
Edit while retaining Re-review and Complete.

### Review areas

Users may select any applicable combination of:

- Clinical Determination
- Generic Reason Code
- Coding
- Decision Remarks
- Other

Review areas are optional. Only these areas are allowed, and each selected area
appears once.

### Points

Contract Points and Nurse Points are separate optional text fields. Each accepts
up to 10 characters through the screen. They may contain text and do not require
numeric values. Changing one field does not replace the other. Existing Points
values are shown as Contract Points. Saving a blank field clears that field.

### Saving a review

A valid QC decision and its permitted comment are required. Agree automatically
uses Completed. The user can only save a review for a claim belonging to the task.
A successful save records the selected review details and who reviewed the claim,
updates the claim's QC status, and reevaluates whether the task is complete.

Reviewed claims appear in QC Review Information with an Edit action.

## Task completion

### Automatic completion

A task completes when all its linked claims have one of these reviewed statuses:
Agree, Returned for Corrections, or Completed.

Returned for Corrections counts as a reviewed result. Task completion therefore
means the review work was recorded; it does not mean every claim was agreed or
that every correction has been resolved.

If any linked claim remains unreviewed, the task remains In Progress after a review
save. Completing the task records a completion date and a completion comment.

### Manual completion

Complete Task allows a user to complete a task before all its claims are reviewed.
Claims still marked Created are released for future task selection. Reviewed claim
results are retained. Claims already marked In Progress are not released by this
action.

The completion comment includes reviewed claims only. When no claims were
reviewed, the summary displays **No reviewed claims**.

After completion, SELF ASSIGN and Complete Task are unavailable. Repeated completion
does not produce duplicate Comments or change a completed task.

## Editing reviewed claims

The user selects Edit beside a reviewed claim to change allowed review details
or continue the claim conversation. Both roles can edit.

Save Points and QC Review saves the changes, refreshes the claim summary and its
existing completion comment when present, and keeps the editor open. Send Note also
keeps the editor open. Users select Close at the top when ready to leave.

Editing an agreed first-review claim can change its decision to Action Required.
This remains a change within the same task and does not introduce Re-review.
Changes are checked against the same decision and completion rules as the original
review.

## Claim conversations

Conversation and notes are available in the reviewed claim's Edit screen.
A note belongs to the selected task and claim.

- The user may enter a recipient RACF/user name.
- Leaving the recipient blank sends the note to the current user.
- A new conversation initially defaults to the current user.
- Reopening a conversation defaults to the previous participant. The user can
  change that recipient before sending.
- A note must contain between 1 and 4,000 characters, excluding leading and trailing
  spaces. A recipient name can contain up to 100 characters.
- Sending saves the note, displays it in the conversation, clears the note entry
  field, and keeps the editor open.
- Notes do not create task creation or completion Comments.

The user can enter another recipient name; the current sign-in choices remain
Pandu and Regine.

## Alerts

New assignments and received notes produce alerts.

- Assignment alerts are sent to the newly assigned user.
- Note alerts are sent only to the named recipient. Assignment alone does not give
  the task assignee a copy of every note alert.
- Each user sees their own unread alert count.
- The count refreshes every 15 seconds.
- Opening Alerts shows up to 50 of the most recent unread alerts with related task,
  claim, sender, date, and message information.
- Mark Read marks all of the current user's unread alerts as read.
- Close dismisses the alerts panel without marking alerts as read.

## Comments tab

Comments appears immediately after Tasks. Each task comment is a separate
expandable row and starts collapsed.

### Collapsed row

Only these fields are displayed:

- Date
- Task ID
- Task Name
- RACF - Name

### Expanded row

Expanding displays the comment heading, such as **Task 238 - Created**, and its
Comments. Completed entries additionally display reviewed claims with:

- Claim #
- Contract Points
- Nurse Points
- Review Areas
- Final Status
- QC Review
- QC Comment

Clicking the row again collapses it.

### Comment creation and refresh rules

1. Creating a task records one Created comment containing the user's task comment.
2. Saving individual claims does not add task Comments while review work is in
   progress and the task has never completed.
3. Automatic or manual task completion records one Completed comment.
4. The completion summary includes only reviewed claims with a saved review result.
   Released and unreviewed claims are excluded.
5. Repeated completion does not add another Completed comment.
6. Later edits to points, review areas, QC decision/comment, or final status refresh
   the corresponding existing completion summary without adding another entry.
7. Editing the task comment refreshes its existing Created comment. Existing comment
   entries also show the current task name when related details are refreshed.
8. Refreshing a comment retains its original date and author information.
9. A claim edit can refresh an existing completion comment even if the task's work
   subsequently changes. It does not create a completion comment for a task that
   has never completed.
10. Selecting Comments or Refresh Comments displays the latest entries, newest first.
11. Older tasks are not automatically given creation or completion comments that
    were never recorded.
12. Deleting a task deletes its corresponding Created and Completed Comments.

## Task deletion

Either role can delete a task, including a completed task. Deletion removes the
task and its review records, claim conversations, related alerts, and task Comments.
All linked claims become Released, including claims that had been reviewed, so they
can be selected for future tasks.

Deleting a task does not delete the source claim information. Because the deleted
task's review history is removed, that history does not establish a later Re-review.

## Business scenarios and expected outcomes

| Scenario | Expected outcome |
| --- | --- |
| User creates a Full Review task | Every currently eligible case claim is included |
| User creates a Partial Review task | Only selected eligible claims are included |
| Selected claim becomes unavailable before creation | Task creation is rejected and the user must refresh selection |
| Claim 1 in Task 1 is saved as Action Required, then edited in Task 1 | Agree and Action Required remain available; Re-review is not shown |
| A previously reviewed, eligible Claim 1 is included in Task 2 | Re-review is offered in Task 2 |
| An unreviewed claim is released and included in another task | Agree and Action Required remain available |
| Last unreviewed claim is saved with a valid reviewed result | Task completes and one completion comment is recorded |
| User completes a task with reviewed and unreviewed claims | Created claims are released; summary includes reviewed claims only |
| User completes a task without reviewing any claims | Completion comment displays No reviewed claims |
| User edits points after task completion | Existing completion summary is refreshed; no duplicate entry |
| User saves a reviewed claim or sends a note from Edit | Editor stays open until Close is selected |
| User clears the note recipient and sends | Note and alert go to the current user |
| User selects or clears Mentor | Choice is immediately saved for that task |
| User opens Comments | Rows start collapsed with date, task ID, task name, and RACF - name |
| User deletes a task | Task, associated comments, conversations, and alerts are removed; claims are released |

## Business boundaries

This document covers the current task and claim QC review workspace. Source claim
information, attachments, and source decisions are provided to the workspace;
creating or changing those source records is outside this flow. File upload,
file download, additional user administration, and a separate Reporting view are
not part of the current business activities.
