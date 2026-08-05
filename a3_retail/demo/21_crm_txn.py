"""Seed 21 — footfall, leads, tickets and feedback (scope 14.2, 14.3).

120 visits over the last five days on a 10:00–20:00 curve that peaks at 17:00–19:00,
because the footfall heatmap is only interesting if the shape is real.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate

VISITS = 120
HOUR_WEIGHTS = [(10, 1), (11, 2), (12, 2), (13, 1), (14, 2), (15, 3), (16, 3),
                (17, 5), (18, 5), (19, 4), (20, 2)]

PURPOSES = ["New Device Enquiry", "Service / Repair", "Accessory Purchase", "EMI Enquiry",
            "Warranty Enquiry", "Exchange Enquiry"]
OUTCOMES = ["Converted - Sale", "Converted - Job Card", "Lost - Price", "Lost - Stock Unavailable",
            "Lead Created (Follow-up)", "Pending", "Information Only"]
BRANCHES = ["Kochi", "Kochi", "Kochi", "Thiruvananthapuram", "Kozhikode"]

COMPLAINTS = [
	("Repair took longer than promised", "Service Delay", "High"),
	("Handset returned with a scratch", "Repair Quality", "Critical (Escalated / Social Media / Consumer Court)"),
	("Invoice shows the wrong amount", "Billing / Invoice", "Medium"),
	("EMI was not approved but the phone was booked", "EMI / Finance", "High"),
	("Screen guard peeled off in two days", "Product Defect", "Low"),
]


def run():
	_visits()
	_issues()
	_feedback()


def _hour_sequence() -> list[int]:
	hours = []
	for hour, weight in HOUR_WEIGHTS:
		hours.extend([hour] * weight)
	return hours


def _visits():
	if frappe.db.count("Branch Visit Log", {"remarks": "A3 demo footfall"}) >= VISITS:
		return

	hours = _hour_sequence()
	employees = {}
	for index in range(VISITS):
		branch = BRANCHES[index % len(BRANCHES)]
		day = add_days(getdate(nowdate()), -(index % 5))
		hour = hours[index % len(hours)]

		if branch not in employees:
			employees[branch] = frappe.db.get_value(
				"Employee", {"branch": branch, "status": "Active"}, "name"
			)

		doc = frappe.new_doc("Branch Visit Log")
		doc.branch = branch
		doc.visit_datetime = f"{day} {hour:02d}:{(index * 7) % 60:02d}:00"
		doc.visitor_name = f"Walk-in {index + 1}"
		doc.mobile_no = f"98461{index:05d}"
		doc.purpose = PURPOSES[index % len(PURPOSES)]
		doc.budget_range = ["< 10K", "10K - 20K", "20K - 35K", "35K - 60K"][index % 4]
		doc.attended_by = employees[branch]
		doc.time_spent_minutes = 8 + (index % 5) * 6
		doc.outcome = OUTCOMES[index % len(OUTCOMES)]
		doc.remarks = "A3 demo footfall"
		if doc.outcome.startswith("Lost"):
			doc.follow_up_required = 1
			doc.follow_up_date = add_days(getdate(nowdate()), 2)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: visit {index}")


def _issues():
	if frappe.db.count("Issue", {"subject": ["in", [row[0] for row in COMPLAINTS]]}) >= len(COMPLAINTS):
		return

	customers = frappe.get_all("Customer", pluck="name", limit=8)
	for index, (subject, category, severity) in enumerate(COMPLAINTS):
		doc = frappe.new_doc("Issue")
		doc.subject = subject
		doc.description = subject
		doc.customer = customers[index % len(customers)] if customers else None
		doc.status = "Open" if index < 3 else "Resolved"
		doc.opening_date = add_days(nowdate(), -(index + 1))
		if doc.meta.has_field("a3_branch"):
			doc.a3_branch = BRANCHES[index % len(BRANCHES)]
			doc.a3_complaint_category = category
			doc.a3_severity = severity
			doc.a3_channel = "Walk-in"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: issue {index}")


def _feedback():
	if frappe.db.count("Customer Feedback", {"channel": "In-store Tablet"}) >= 5:
		return

	jobs = frappe.get_all(
		"Service Job Card", filters={"docstatus": 1, "status": ["in", ["Delivered", "Closed"]]},
		fields=["name", "customer", "customer_mobile", "branch", "assigned_technician"], limit=5,
	)
	ratings = [1.0, 1.0, 0.8, 0.6, 0.4]
	for index, job in enumerate(jobs):
		doc = frappe.new_doc("Customer Feedback")
		doc.feedback_date = add_days(nowdate(), -index)
		doc.customer = job.customer
		doc.mobile_no = job.customer_mobile
		doc.branch = job.branch
		doc.channel = "In-store Tablet"
		doc.reference_type = "Service Job Card"
		doc.reference_name = job.name
		doc.attended_employee = job.assigned_technician
		doc.overall_rating = ratings[index % len(ratings)]
		doc.comments = ["Very quick service", "Polite staff", "Took a day longer",
		                "Costly but fixed", "Had to visit twice"][index % 5]
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: feedback {index}")
