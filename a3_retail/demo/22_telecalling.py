"""Seed 22 — 9 call dispositions and 4 telecalling campaigns (scope 8.4)."""

import frappe
from frappe.utils import add_days, nowdate

# name, category, next call?, days, whatsapp?, dnc?
DISPOSITIONS = [
	("Interested - Will Visit", "Positive", 1, 2, 0, 0),
	("Interested - Send Details", "Positive", 0, 0, 1, 0),
	("Price Too High", "Negative", 0, 0, 0, 0),
	("Already Renewed Elsewhere", "Negative", 0, 0, 0, 0),
	("Device Sold / Not Owned", "Invalid", 0, 0, 0, 0),
	("Call Back Tomorrow", "Neutral", 1, 1, 0, 0),
	("Not Reachable", "Neutral", 1, 1, 0, 0),
	("Do Not Call", "Invalid", 0, 0, 0, 1),
	("Converted", "Positive", 0, 0, 0, 0),
]

# name, objective, branch, source, doctype, from, to
CAMPAIGNS = [
	("Warranty Renewal Aug", "Warranty Renewal", None, "DocType Filter",
	 "Warranty Registration", -5, 25),
	("Onam Offer Blast", "Offer Promotion", None, "DocType Filter", "Customer", 0, 30),
	("Lost Lead Recovery", "Lost Lead Follow-up", "Kochi", "Branch Visit Log", None, -5, 10),
	("Device Pickup Reminder", "Device Pickup Reminder", None, "DocType Filter",
	 "Service Job Card", -10, 60),
]

TELECALLERS = ["Sneha M", "Arjun V"]


def run():
	_dispositions()
	_campaigns()


def _dispositions():
	for name, category, next_call, days, whatsapp, dnc in DISPOSITIONS:
		if frappe.db.exists("Call Disposition", name):
			continue
		doc = frappe.new_doc("Call Disposition")
		doc.disposition_name = name
		doc.category = category
		doc.requires_next_call = next_call
		doc.default_next_call_days = days
		doc.triggers_whatsapp = whatsapp
		doc.is_dnc = dnc
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _campaigns():
	team = [
		frappe.db.get_value("Employee", {"employee_name": name}, "name") for name in TELECALLERS
	]
	team = [t for t in team if t]

	for name, objective, branch, source, doctype, start_offset, end_offset in CAMPAIGNS:
		if frappe.db.exists("Telecalling Campaign", {"campaign_name": name}):
			continue

		doc = frappe.new_doc("Telecalling Campaign")
		doc.campaign_name = name
		doc.objective = objective
		doc.branch = branch
		doc.target_source = source
		doc.source_doctype = doctype
		doc.start_date = add_days(nowdate(), start_offset)
		doc.end_date = add_days(nowdate(), end_offset)
		doc.status = "Active" if start_offset <= 0 else "Draft"
		doc.exclude_contacted_days = 30
		doc.script = f"Namaskaram, calling from Mobile World about {objective.lower()}."

		for index, employee in enumerate(team):
			doc.append("assigned_team", {"employee": employee, "target_calls": 60 if index == 0 else 40})

		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
