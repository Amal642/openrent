import csv
import io
import os

from flask import Flask, Response, render_template, request

from app.db.repository import get_dashboard_leads

BASE_DIR = os.path.dirname(__file__)
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATE_DIR)

STATUSES = [
    "ALL",
    "NEW_REPLY",
    "AI_REPLIED",
    "PHONE_ACQUIRED",
    "REPLY_DISABLED",
    "AI_FAILED",
    "DUPLICATE_LEAD",
    "DEAD_THREAD",
]


@app.route("/leads")
def leads_page():
    status = request.args.get("status", "ALL")
    leads = get_dashboard_leads(status=status)
    return render_template(
        "leads.html",
        leads=leads,
        statuses=STATUSES,
        current_status=status,
    )


@app.route("/leads/export.csv")
def export_leads_csv():
    status = request.args.get("status", "ALL")
    leads = get_dashboard_leads(status=status)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "thread_id",
        "listing_id",
        "property_url",
        "status",
        "phone",
        "last_processed_message",
        "last_ai_reply",
        "created_at",
        "last_message_at",
    ])

    for lead in leads:
        writer.writerow([
            lead["thread_id"],
            lead["listing_id"],
            lead["property_url"],
            lead["status"],
            lead["phone"],
            lead["last_processed_message"],
            lead["last_ai_reply"],
            lead["created_at"],
            lead["last_message_at"],
        ])

    filename = f"leads_{status.lower()}.csv" if status != "ALL" else "leads.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )