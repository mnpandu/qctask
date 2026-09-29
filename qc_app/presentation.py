"""Pure HTML and label formatting; no database access."""

from html import escape

import claim_workflow as qc

from . import config


def task_row_label(row):
    return "\t".join(
        str(value or "?").replace("\t", " ")
        for value in (row[0], row[1], config.CASE_ID, row[2], row[3], row[4], row[5])
    )


def claims_for_review_html(canonical):
    numbers = [str(claim["claimNumber"]) for claim in canonical.get("claimsForReviews", [])]
    items = "".join("<li>" + escape(number) + "</li>" for number in numbers)
    return (
        '<section class="claim-list-section" aria-label="Claims for review">'
        '<div class="claim-list-heading"><strong>Claims For Review</strong>'
        f"<span>{len(numbers)} claims</span></div>"
        '<div class="claim-list-scroll" tabindex="0" role="region" aria-label="Claim numbers">'
        + ('<ul class="claim-number-list">' + items + "</ul>" if numbers else "<p>No claims.</p>")
        + "</div></section>"
    )


def display_fields(fields):
    return (
        '<div class="task-fields">'
        + "".join(
            "<div><strong>"
            + escape(label)
            + "</strong><span>"
            + escape(str(value or "?"))
            + "</span></div>"
            for label, value in fields
        )
        + "</div>"
    )


def review_area_checked(details, category):
    field = qc.QC_REVIEW_CATEGORY_FIELDS[category]
    if field in details:
        return bool(details[field])
    return category in details.get("reviewCategories", [])


def render_claim_review_summary(item):
    claim_id = item["claimNumber"]
    details = item.get("qcReviewDetails", {})
    decision = details.get("qcReview", "")
    comment = details.get("qcReviewComment", "")
    reviewer = details.get("reviewedBy", "")
    categories = ", ".join(
        category for category in qc.QC_REVIEW_CATEGORIES if review_area_checked(details, category)
    )
    points = details.get("points", "")
    return (
        '<div class="qc-review-row"><strong>'
        + escape(str(claim_id))
        + "</strong><span>"
        + escape(str(decision))
        + "</span><span>"
        + escape(str(comment))
        + "</span><span>"
        + escape(categories)
        + "</span><span>"
        + escape(str(points))
        + "</span><small>Reviewed by "
        + escape(str(reviewer))
        + "</small></div>"
    )


def completed_claims(canonical):
    return [
        item
        for item in canonical.get("claimsForReviews", [])
        if item.get("qcReviewStatus") in qc.REVIEWED_STATUSES
        and item.get("qcReviewDetails", {}).get("qcReview")
        in (*qc.QC_DECISIONS, "Returned for Corrections")
    ]
