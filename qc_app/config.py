"""Environment settings and shared UI choices."""

import os

TASK_TYPES = ["QC Nurse Full Review", "QC Nurse Partial Review"]


TASK_COLUMNS = [
    "Task ID",
    "Task Name",
    "Status",
    "Assigned To",
    "Created On",
    "Completed On",
    "Claims",
    "Comments",
]


CLAIM_COLUMNS = [
    "Claim ID",
    "Provider ID",
    "Date of Service",
    "Procedure Code",
    "Billed Amount",
    "Allowed Amount",
    "Paid Amount",
    "Claim Status",
]


CASE_ID = int(os.getenv("QC_CASE_ID", "1"))


ACTOR_ID = os.getenv("QC_USER_ID", "demo")


ACTOR_NAME = os.getenv("QC_USER_NAME", "Demo User")


USERS = {
    "pandu": {"id": "pandu", "name": "Pandu", "role": "QC Nurse"},
    "regine": {"id": "regine", "name": "Regine", "role": "Nurse"},
}


STATUSES = ["Not Started", "In Progress", "Completed"]
