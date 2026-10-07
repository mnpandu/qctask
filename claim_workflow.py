"""Database-backed claim eligibility and sequential QC reviews."""

from psycopg.types.json import Jsonb

import task_comments


def eligible_claims(conn, case_id):
    return conn.execute(
        """
        SELECT c.claim_number, c.claim_data FROM pic_master.claim_details c
        WHERE c.case_id = %s AND (c.qc_status IS NULL OR c.qc_status ~ '^[[:space:]]*$' OR c.qc_status IN ('Released', 'Returned for Corrections'))
        ORDER BY c.claim_number
    """,
        (case_id,),
    ).fetchall()


def add_reviews(conn, task_id, case_id, ids):
    for claim_id in ids:
        row = conn.execute(
            """
            UPDATE pic_master.claim_details SET qc_status = 'Created',
                updated_dts = CURRENT_TIMESTAMP
            WHERE case_id = %s AND claim_number = %s
                AND (qc_status IS NULL OR qc_status ~ '^[[:space:]]*$' OR qc_status IN ('Released', 'Returned for Corrections'))
            RETURNING claim_number
        """,
            (case_id, claim_id),
        ).fetchone()
        if row is None:
            raise ValueError("A claim is no longer eligible. Refresh the claim list.")


def review_view(conn, task_id):
    rows = conn.execute(
        """
        SELECT c.claim_number, c.qc_status,
               COALESCE(j.item->'qcReviewDetails', '{}'::jsonb)
               || jsonb_build_object('hasPreviousReview', EXISTS (
                   SELECT 1 FROM pic_master.task previous
                   JOIN pic_master.task_details previous_details USING (task_id)
                   CROSS JOIN LATERAL jsonb_array_elements(
                       previous_details.task_canonical->'claimsForReviews'
                   ) AS previous_claim(item)
                   WHERE previous.case_id = t.case_id AND previous.task_id < t.task_id
                     AND previous_claim.item->>'claimNumber' = c.claim_number
                     AND NULLIF(BTRIM(previous_claim.item->'qcReviewDetails'->>'qcReview'), '') IS NOT NULL
               )), c.claim_data
        FROM pic_master.task t JOIN pic_master.task_details d ON d.task_id = t.task_id
        CROSS JOIN LATERAL jsonb_array_elements(d.task_canonical->'claimsForReviews')
            WITH ORDINALITY AS j(item, position)
        JOIN pic_master.claim_details c
            ON c.case_id = t.case_id AND c.claim_number = j.item->>'claimNumber'
        WHERE t.task_id = %s ORDER BY j.position
    """,
        (task_id,),
    ).fetchall()
    current = next((r for r in rows if r[1] == "In Progress"), None)
    return rows, current


def lock_task(conn, task_id, case_id):
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (case_id,))
    row = conn.execute(
        """
        SELECT task_status FROM pic_master.task
        WHERE task_id = %s AND case_id = %s AND status = 'Active' FOR UPDATE
    """,
        (task_id, case_id),
    ).fetchone()
    if row is None:
        raise ValueError("Select an active task first.")
    return row[0]


def sync_canonical(conn, task_id, actor, claim_id=None, review_details=None):
    canonical = conn.execute(
        "SELECT task_canonical FROM pic_master.task_details WHERE task_id = %s FOR UPDATE",
        (task_id,),
    ).fetchone()[0]
    rows, _ = review_view(conn, task_id)
    statuses = {row[0]: row[1] for row in rows}
    for item in canonical["claimsForReviews"]:
        number = item["claimNumber"]
        if number in statuses:
            item["qcReviewStatus"] = statuses[number]
        item.setdefault("qcReviewDetails", {})
        if number == claim_id and review_details is not None:
            item["qcReviewDetails"].update(review_details)
    conn.execute(
        """
        UPDATE pic_master.task_details SET task_canonical = %s,
        updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
    """,
        (Jsonb(canonical), actor, task_id),
    )


def start_next(conn, task_id, case_id, actor):
    status = lock_task(conn, task_id, case_id)
    rows, current = review_view(conn, task_id)
    if current:
        return current[0]
    pending = next((r for r in rows if r[1] == "Created"), None)
    if pending is None:
        return None
    if status == "Completed":
        raise ValueError("This task is already completed.")
    claim_id = pending[0]
    conn.execute(
        """
        UPDATE pic_master.claim_details SET qc_status = 'In Progress',
        updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = %s AND claim_number = %s
    """,
        (case_id, claim_id),
    )
    conn.execute(
        """
        UPDATE pic_master.task SET task_status = 'In Progress', updated_by = %s,
        updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
    """,
        (actor, task_id),
    )
    sync_canonical(conn, task_id, actor)
    return claim_id


def save_review(conn, task_id, case_id, claim_id, outcome, notes, complete, actor):
    lock_task(conn, task_id, case_id)
    rows, current = review_view(conn, task_id)
    if not current or current[0] != claim_id:
        raise ValueError("The current claim has changed. Reopen the task to continue.")
    if outcome not in ("", "Approved", "Needs Correction", "Rejected"):
        raise ValueError("Select a valid review outcome.")
    if complete and not outcome:
        raise ValueError("Select a review outcome before completing the claim.")
    details = {"outcome": outcome, "notes": notes or "", "reviewedBy": actor}
    status = "Completed" if complete else "In Progress"
    conn.execute(
        """
        UPDATE pic_master.claim_details SET qc_status = %s,
        updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = %s AND claim_number = %s
    """,
        (status, case_id, claim_id),
    )
    sync_canonical(conn, task_id, actor, claim_id, details)
    task_comments.refresh_existing(conn, task_id, actor)
    if complete:
        next_id = start_next(conn, task_id, case_id, actor)
        if next_id is None:
            conn.execute(
                """
                UPDATE pic_master.task SET task_status = 'Completed',
                task_cmpled_dts = CURRENT_TIMESTAMP, updated_dts = CURRENT_TIMESTAMP,
                updated_by = %s WHERE task_id = %s
            """,
                (actor, task_id),
            )
    sync_canonical(conn, task_id, actor)
    if complete and next_id is None:
        task_comments.record_completion(conn, task_id, actor)


QC_COMMENT_OPTIONS = {
    "Agree": ("Completed",),
    "Action Required": ("Return for Correction", "Response Requested"),
    "Re-review": ("Return of Correction", "Complete"),
}
QC_DECISIONS = tuple(QC_COMMENT_OPTIONS)
QC_COMMENTS = tuple(comment for choices in QC_COMMENT_OPTIONS.values() for comment in choices)
LEGACY_QC_COMMENTS = {
    "Response Required": "Response Requested",
    "Correction required": "Return for Correction",
    "Correction Required": "Return for Correction",
}
REVIEWED_STATUSES = ("Agree", "Returned for Corrections", "Completed")
QC_REVIEW_CATEGORIES = (
    "Clinical Determination",
    "Generic Reason Code",
    "Coding",
    "Decision Remarks",
    "Other",
)
QC_REVIEW_CATEGORY_FIELDS = {
    "Clinical Determination": "clinicalDetermination",
    "Generic Reason Code": "genericReasonCode",
    "Coding": "coding",
    "Decision Remarks": "decisionRemarks",
    "Other": "other",
}


def review_decision_options(status, details):
    decision = details.get("qcReview")
    if details.get("hasPreviousReview"):
        editable = not (decision == "Re-review" and details.get("qcReviewComment") == "Complete")
        return ["Re-review"], "Re-review", editable
    choices = ["Agree", "Action Required"]
    saved = decision if decision in choices else "Agree" if status == "Agree" else None
    return choices, saved, True


def save_claim_decision(
    conn,
    task_id,
    case_id,
    claim_id,
    decision,
    comment,
    actor,
    categories=None,
    points=None,
    nurse_points=None,
    report_exclusive=None,
):
    if report_exclusive is not None and not isinstance(report_exclusive, bool):
        raise ValueError("Report Exclusive must be checked or unchecked.")
    lock_task(conn, task_id, case_id)
    if decision == "Agree":
        comment = "Completed"
    comment = LEGACY_QC_COMMENTS.get(comment, comment)
    if comment not in QC_COMMENT_OPTIONS.get(decision, ()):
        raise ValueError("Select QC Review and QC Review Comment before saving.")
    categories = list(dict.fromkeys(categories or []))
    if not set(categories).issubset(QC_REVIEW_CATEGORIES):
        raise ValueError("Select valid QC review categories.")
    if points is not None and len(points) > 100:
        raise ValueError("Contract Points must be 100 characters or fewer.")
    if nurse_points is not None and len(nurse_points) > 100:
        raise ValueError("Nurse Points must be 100 characters or fewer.")
    rows, _ = review_view(conn, task_id)
    if claim_id not in {r[0] for r in rows}:
        raise ValueError("This claim does not belong to the selected task.")
    current = next(row for row in rows if row[0] == claim_id)
    choices, _, editable = review_decision_options(current[1], current[2])
    if decision not in choices or (
        not editable and decision == "Re-review" and comment != "Complete"
    ):
        raise ValueError(
            "This claim cannot use that review decision. Reconsideration requires Re-review."
        )
    conn.execute(
        """
        UPDATE pic_master.claim_details SET qc_status = %s, updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = %s AND claim_number = %s
    """,
        (
            "Agree"
            if decision == "Agree"
            else "Completed"
            if decision == "Re-review" and comment == "Complete"
            else "Returned for Corrections",
            case_id,
            claim_id,
        ),
    )
    details = {
        "qcReview": decision,
        "qcReviewComment": comment,
        "reviewedBy": actor,
        "reviewCategories": categories,
        "points": points,
    }
    details.update(
        {field: category in categories for category, field in QC_REVIEW_CATEGORY_FIELDS.items()}
    )
    if points is None:
        details.pop("points")
    if nurse_points is not None:
        details["nursePoints"] = nurse_points
    if report_exclusive is not None:
        details["reportExclusive"] = report_exclusive
    sync_canonical(conn, task_id, actor, claim_id, details)
    task_comments.refresh_existing(conn, task_id, actor)
    rows, _ = review_view(conn, task_id)
    finished = all(r[1] in REVIEWED_STATUSES for r in rows)
    conn.execute(
        """
        UPDATE pic_master.task SET task_status = %s,
        task_cmpled_dts = CASE WHEN %s THEN COALESCE(task_cmpled_dts, CURRENT_TIMESTAMP) ELSE NULL END,
        updated_by = %s, updated_dts = CURRENT_TIMESTAMP WHERE task_id = %s
    """,
        ("Completed" if finished else "In Progress", finished, actor, task_id),
    )

    if finished:
        task_comments.record_completion(conn, task_id, actor)
