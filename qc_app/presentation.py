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
            + escape(str(value if value is not None and value != "" else "?"))
            + "</span></div>"
            for label, value in fields
        )
        + "</div>"
    )


def review_claim_fields(claim_id, data):
    """Resolve metadata from existing claim JSON without inventing missing values."""
    normalized = {
        "".join(char.lower() for char in str(key) if char.isalnum()): value
        for key, value in data.items()
    }

    def find(aliases):
        for alias in aliases:
            key = "".join(char.lower() for char in alias if char.isalnum())
            value = normalized.get(key)
            if value is not None and value != "":
                return value
        return ""

    fields = []
    for label, aliases in config.REVIEW_CLAIM_FIELDS.items():
        value = claim_id if label == "Claim #" else find(aliases)
        if label == "DOS From / To" and not value:
            start = find(("dosFrom", "serviceFromDate", "dateOfServiceFrom"))
            end = find(("dosTo", "serviceToDate", "dateOfServiceTo"))
            value = " - ".join(str(part) for part in (start, end) if part != "")
        fields.append((label, value))
    fields.extend((label, data.get(label, "")) for label in config.CLAIM_COLUMNS
                  if label not in ("Claim ID", "Date of Service"))
    return fields


def review_claim_row_label(claim_id, data, status):
    fields = review_claim_fields(claim_id, data)[:len(config.REVIEW_CLAIM_FIELDS)]
    return "\t".join(
        str(status if label == "QC Review" else value if value != "" and value is not None else "?")
        .replace("\t", " ").replace("\n", " ").replace("\r", " ")
        for label, value in fields
    )


def review_claim_header_html():
    return '<div class="claim-review-header">' + "".join(
        '<span>' + escape(label) + '</span>' for label in config.REVIEW_CLAIM_FIELDS
    ) + '</div>'


def claim_metadata_value(data, *aliases):
    normalized = {
        "".join(char.lower() for char in str(key) if char.isalnum()): value
        for key, value in data.items()
    }
    for alias in aliases:
        key = "".join(char.lower() for char in alias if char.isalnum())
        value = normalized.get(key)
        if value is not None and value != "":
            return value
    return ""


def claim_attachments_html(data):
    attachments = claim_metadata_value(data, "attachments", "claimAttachments")
    if isinstance(attachments, dict):
        attachments = claim_metadata_value(attachments, "items", "records")
    records = attachments if isinstance(attachments, list) else []
    columns = {
        "File Name": ("fileName", "name"),
        "Doc Type": ("docType", "documentType"),
        "Work Type": ("workType",),
        "Receipt Date": ("receiptDate", "receivedDate"),
    }
    header = "".join('<th scope="col">' + escape(label) + '</th>' for label in columns)
    rows = "".join(
        '<tr>' + "".join('<td>' + escape(str(claim_metadata_value(record, *aliases))) + '</td>'
                           for aliases in columns.values()) + '</tr>'
        for record in records if isinstance(record, dict)
    )
    if not rows:
        rows = '<tr><td colspan="4" class="qc-empty">No records to display</td></tr>'
    return ('<section class="claim-detail-section"><h4>Attachments</h4>'
            '<div class="claim-attachment-scroll"><table><thead><tr>' + header
            + '</tr></thead><tbody>' + rows + '</tbody></table></div></section>')


def claim_decision_details_html(data):
    nested = claim_metadata_value(data, "decisionDetails", "claimDecisionDetails")
    details = {**data, **nested} if isinstance(nested, dict) else data
    columns = {
        "Decision": ("decision", "claimDecision"),
        "Decision Date": ("decisionDate",),
        "Associated DCN": ("associatedDCN", "dcn"),
        "Demand Bill": ("demandBill",),
        "Denial Reason": ("denialReason",),
        "Generic Reason Code": ("genericReasonCode",),
        "Pre MR Original Reimbursement": ("preMROriginalReimbursement",),
        "Post MR Original Reimbursement": ("postMROriginalReimbursement",),
        "Total Reimbursement Savings": ("totalReimbursementSavings",),
        "Decision Remarks": ("decisionRemarks",),
    }
    fields = [(label, claim_metadata_value(details, *aliases)) for label, aliases in columns.items()]
    return ('<section class="claim-detail-section claim-decision-details"><h4>Decision Details</h4>'
            + display_fields(fields) + '</section>')


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
        + "</span><span>"
        + escape(str(details.get("nursePoints", "")))
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
