"""Display task creation comments and completion snapshots."""

from html import escape

import psycopg

from . import config, database, errors, identity


HEADERS = ["Claim #", "Contract Points", "Nurse Points", "Review Areas", "Final Status", "QC Review", "QC Comment"]


def load_comments_html(user):
    if not user:
        return ""
    identity.require_user(user)
    try:
        with database.connect_db() as conn:
            rows = conn.execute(
                "SELECT task_id, event_type, comment_text, claim_reviews, created_by, "
                "to_char(created_dts, 'YYYY-MM-DD HH24:MI:SS'), task_name, created_by_name "
                "FROM pic_master.task_comments WHERE case_id = %s ORDER BY created_dts DESC, comment_id DESC",
                (config.CASE_ID,),
            ).fetchall()
    except psycopg.Error:
        raise errors.database_error() from None
    return render_comments(rows)


def render_comments(rows):
    if not rows:
        return '<p class="qc-empty">No task comments yet.</p>'
    sections = []
    for task_id, event, comment, reviews, actor, date, task_name, actor_name in rows:
        actor_name = actor_name or config.USERS.get(actor, {}).get("name", actor)
        actor_label = f"{actor} - {actor_name}"
        table = ""
        if event == "Completed":
            header = "".join('<th scope="col">' + escape(label) + '</th>' for label in HEADERS)
            body = ""
            for review in reviews:
                values = [review.get("claimNumber"), review.get("contractPoints"), review.get("nursePoints"),
                          ", ".join(review.get("reviewAreas") or []), review.get("finalStatus"),
                          review.get("qcReview"), review.get("qcComment")]
                body += '<tr>' + "".join('<td>' + escape(str(value if value is not None else "")) + '</td>'
                                         for value in values) + '</tr>'
            if not body:
                body = '<tr><td colspan="7">No reviewed claims.</td></tr>'
            table = '<table><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table>'
        metadata = [("Date", date), ("Task ID", task_id), ("Task Name", task_name),
                    ("RACF - Name", actor_label)]
        fields = '<span class="task-comment-metadata">' + "".join(
            '<span><strong>' + escape(label) + '</strong><span>' + escape(str(value)) + '</span></span>'
            for label, value in metadata
        ) + '</span>'
        sections.append('<details class="claim-detail-section task-comment-entry">'
                        + '<summary>' + fields + '</summary>'
                        + '<h4>Task ' + escape(str(task_id)) + ' - ' + escape(event) + '</h4>'
                        + '<div class="task-comment-text"><strong>Comments</strong>'
                        + '<p style="white-space: pre-wrap">' + escape(comment) + '</p></div>'
                        + '<div class="claim-attachment-scroll">' + table + '</div></details>')
    return "".join(sections)
