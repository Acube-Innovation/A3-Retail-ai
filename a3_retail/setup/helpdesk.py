# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Help desk configuration: issue types and SLA tiers (scope 8.3)."""

import frappe

ISSUE_TYPES = [
	"Service Complaint", "Product Complaint", "Billing Query", "Refund Request",
	"EMI Query", "Delivery Complaint", "Warranty Query", "Feedback / Suggestion",
	"General Enquiry",
]

# priority, first response (h), resolution (h)
SLA_TIERS = [
	("Critical", 0.5, 4),
	("High", 2, 24),
	("Medium", 4, 48),
	("Low", 8, 72),
]

SLA_NAME = "A3 Retail Support SLA"


def run():
	_issue_types()
	_priorities()
	_service_level_agreement()


def _issue_types():
	for name in ISSUE_TYPES:
		if frappe.db.exists("Issue Type", name):
			continue
		doc = frappe.new_doc("Issue Type")
		doc.name = name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _priorities():
	for name, _first, _resolution in SLA_TIERS:
		if frappe.db.exists("Issue Priority", name):
			continue
		doc = frappe.new_doc("Issue Priority")
		doc.name = name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _service_level_agreement():
	"""Support hours 09:30–20:00, Mon–Sat, per the branch profile (scope 8.3)."""
	if not frappe.db.exists("DocType", "Service Level Agreement"):
		return
	if frappe.db.exists("Service Level Agreement", SLA_NAME):
		return

	doc = frappe.new_doc("Service Level Agreement")
	doc.service_level = SLA_NAME
	doc.document_type = "Issue"
	doc.enabled = 1
	doc.default_service_level_agreement = 1
	doc.start_date = "2026-04-01"
	doc.end_date = "2030-03-31"
	doc.apply_sla_for_resolution = 1

	for priority, first_response, resolution in SLA_TIERS:
		doc.append(
			"priorities",
			{
				"priority": priority,
				"default_priority": 1 if priority == "Medium" else 0,
				"first_response_time": int(first_response * 3600),
				"resolution_time": int(resolution * 3600),
			},
		)

	for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"):
		doc.append("support_and_resolution",
		           {"workday": day, "start_time": "09:30:00", "end_time": "20:00:00"})

	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: support SLA")


def escalate_breached_issues():
	"""Hourly — walk breached tickets up the escalation ladder (scope 8.3)."""
	from a3_retail.utils import commit_if_not_testing

	ladder = {
		"L0 - Agent": "L1 - Service Manager",
		"L1 - Service Manager": "L2 - Branch Manager",
		"L2 - Branch Manager": "L3 - Head Office",
		"L3 - Head Office": "L4 - Director",
	}

	# `resolution_by` only exists once ERPNext's SLA feature is present.
	if not frappe.db.has_column("Issue", "resolution_by"):
		return 0

	rows = frappe.get_all(
		"Issue",
		filters={"status": ["not in", ["Resolved", "Closed"]], "resolution_by": ["<", frappe.utils.now()]},
		fields=["name", "a3_escalation_level", "a3_branch", "subject"],
	)

	escalated = 0
	for row in rows:
		current = row.a3_escalation_level or "L0 - Agent"
		nxt = ladder.get(current)
		if not nxt:
			continue
		frappe.db.set_value("Issue", row.name, "a3_escalation_level", nxt, update_modified=False)
		escalated += 1

	commit_if_not_testing()
	return escalated
