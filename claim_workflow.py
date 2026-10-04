"""Database-backed claim eligibility and sequential QC reviews."""

from qc_app.database import JsonDocument


def eligible_claims(conn, case_id):
    return conn.execute(
        """
        SELECT c.claim_number, c.claim_data FROM qc_store.qctask_claim_details c
        WHERE c.case_id = :p1 AND (c.qc_status IS NULL OR REGEXP_LIKE(c.qc_status, '^[[:space:]]*$') OR c.qc_status IN ('Released', 'Returned for Corrections'))
        ORDER BY c.claim_number
    """,
        (case_id,),
    ).fetchall()


def add_reviews(conn, task_id, case_id, ids):
    for claim_id in ids:
        row = conn.execute(
            """
            UPDATE qc_store.qctask_claim_details SET qc_status = 'Created',
                updated_dts = CURRENT_TIMESTAMP
            WHERE case_id = :p1 AND claim_number = :p2
                AND (qc_status IS NULL OR REGEXP_LIKE(qc_status, '^[[:space:]]*$') OR qc_status IN ('Released', 'Returned for Corrections'))
            RETURNING claim_number
        """,
            (case_id, claim_id),
        ).fetchone()
        if row is None:
            raise ValueError("A claim is no longer eligible. Refresh the claim list.")


def review_view(conn, task_id):
    task = conn.execute("SELECT t.case_id, d.task_canonical FROM qc_store.qctask_task t JOIN qc_store.qctask_task_details d ON d.task_id = t.task_id WHERE t.task_id = :p1", (task_id,)).fetchone()
    if task is None:
        return [], None
    case_id, canonical = task
    previous = conn.execute("SELECT d.task_canonical FROM qc_store.qctask_task t JOIN qc_store.qctask_task_details d ON d.task_id = t.task_id WHERE t.case_id = :p1 AND t.task_id < :p2", (case_id, task_id)).fetchall()
    reviewed = {item.get("claimNumber") for (document,) in previous
                for item in document.get("claimsForReviews", [])
                if str(item.get("qcReviewDetails", {}).get("qcReview") or "").strip()}
    claims = {number: (status, data) for number, status, data in conn.execute(
        "SELECT claim_number, qc_status, claim_data FROM qc_store.qctask_claim_details WHERE case_id = :p1", (case_id,)).fetchall()}
    rows = []
    for item in canonical["claimsForReviews"]:
        number = item["claimNumber"]
        if number in claims:
            status, data = claims[number]
            details = dict(item.get("qcReviewDetails") or {})
            details["hasPreviousReview"] = number in reviewed
            rows.append((number, status, details, data))
    current = next((r for r in rows if r[1] == "In Progress"), None)
    return rows, current


def lock_task(conn, task_id, case_id):
    conn.lock_case(case_id)
    row = conn.execute(
        """
        SELECT task_status FROM qc_store.qctask_task
        WHERE task_id = :p1 AND case_id = :p2 AND status = 'Active' FOR UPDATE
    """,
        (task_id, case_id),
    ).fetchone()
    if row is None:
        raise ValueError("Select an active task first.")
    return row[0]


def sync_canonical(conn, task_id, actor, claim_id=None, review_details=None):
    canonical = conn.execute(
        "SELECT task_canonical FROM qc_store.qctask_task_details WHERE task_id = :p1 FOR UPDATE",
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
        UPDATE qc_store.qctask_task_details SET task_canonical = :p1,
        updated_by = :p2, updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p3
    """,
        (JsonDocument(canonical), actor, task_id),
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
        UPDATE qc_store.qctask_claim_details SET qc_status = 'In Progress',
        updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = :p1 AND claim_number = :p2
    """,
        (case_id, claim_id),
    )
    conn.execute(
        """
        UPDATE qc_store.qctask_task SET task_status = 'In Progress', updated_by = :p1,
        updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p2
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
        UPDATE qc_store.qctask_claim_details SET qc_status = :p1,
        updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = :p2 AND claim_number = :p3
    """,
        (status, case_id, claim_id),
    )
    sync_canonical(conn, task_id, actor, claim_id, details)
    if complete:
        next_id = start_next(conn, task_id, case_id, actor)
        if next_id is None:
            conn.execute(
                """
                UPDATE qc_store.qctask_task SET task_status = 'Completed',
                task_cmpled_dts = CURRENT_TIMESTAMP, updated_dts = CURRENT_TIMESTAMP,
                updated_by = :p1 WHERE task_id = :p2
            """,
                (actor, task_id),
            )
    sync_canonical(conn, task_id, actor)


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
    if decision == "Agree" or status == "Agree":
        return ["Agree"], "Agree", False
    if decision == "Re-review" and details.get("qcReviewComment") == "Complete":
        return ["Re-review"], "Re-review", False
    if decision or details.get("hasPreviousReview") or status == "Returned for Corrections":
        return ["Re-review"], "Re-review", True
    return ["Agree", "Action Required"], None, True


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
):
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
        raise ValueError("Points must be 100 characters or fewer.")
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
        UPDATE qc_store.qctask_claim_details SET qc_status = :p1, updated_dts = CURRENT_TIMESTAMP
        WHERE case_id = :p2 AND claim_number = :p3
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
    sync_canonical(conn, task_id, actor, claim_id, details)
    rows, _ = review_view(conn, task_id)
    finished = all(r[1] in REVIEWED_STATUSES for r in rows)
    conn.execute(
        """
        UPDATE qc_store.qctask_task SET task_status = :p1,
        task_cmpled_dts = CASE WHEN :p2 = 1 THEN COALESCE(task_cmpled_dts, CURRENT_TIMESTAMP) ELSE NULL END,
        updated_by = :p3, updated_dts = CURRENT_TIMESTAMP WHERE task_id = :p4
    """,
        ("Completed" if finished else "In Progress", finished, actor, task_id),
    )
