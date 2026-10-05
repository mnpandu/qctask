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


# Claim metadata displayed when opening Review Claims, in reference-screen order.
REVIEW_CLAIM_FIELDS = {
    "Claim #": ("Claim #", "Claim ID", "claimNumber", "claim_number"),
    "No of Lines": ("No of Lines", "numberOfLines", "noOfLines", "lineCount"),
    "DOS From / To": ("DOS From / To", "DOS From/To", "Date of Service", "dateOfService"),
    "MBI": ("MBI", "mbi"),
    "Focus Code": ("Focus Code", "focusCode"),
    "PTAN": ("PTAN", "ptan"),
    "NPI": ("NPI", "npi"),
    "Resp Rcvd": ("Resp Rcvd", "RESP RCVD", "Response Received", "responseReceived", "respRcvd"),
    "Claim Decision": ("Claim Decision", "claimDecision"),
    "QC Review": ("QC Review", "qcReview"),
    "ADR Sent Date": ("ADR Sent Date", "adrSentDate"),
    "TOB": ("TOB", "tob", "Type of Bill", "typeOfBill"),
}
