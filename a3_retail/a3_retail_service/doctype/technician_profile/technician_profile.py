# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Technician Profile — skills, capacity and live work-in-progress (scope 3.8)."""

import frappe
from frappe import _
from frappe.model.document import Document


class TechnicianProfile(Document):
	def autoname(self):
		self.name = self.employee_name or self.employee

	def validate(self):
		self.validate_unique_employee()
		if self.max_concurrent_jobs is not None and self.max_concurrent_jobs < 1:
			frappe.throw(_("Max Concurrent Jobs must be at least 1."))

	def validate_unique_employee(self):
		duplicate = frappe.db.exists(
			"Technician Profile", {"employee": self.employee, "name": ["!=", self.name]}
		)
		if duplicate:
			frappe.throw(_("Technician Profile {0} already exists for this employee.").format(duplicate))

	def onload(self):
		self.set_onload("live_wip", count_wip(self.employee))


def count_wip(employee: str) -> int:
	"""Open job cards currently assigned to a technician."""
	if not employee or not frappe.db.exists("DocType", "Service Job Card"):
		return 0

	from a3_retail.a3_retail_service.doctype.service_job_card.state import OPEN_STATUSES

	return frappe.db.count(
		"Service Job Card",
		{"assigned_technician": employee, "status": ["in", list(OPEN_STATUSES)], "docstatus": 1},
	)


def recompute_wip(employee: str | None = None):
	"""Refresh `current_wip`. Called from Job Card status changes and hourly."""
	filters = {"employee": employee} if employee else {}
	for profile in frappe.get_all("Technician Profile", filters=filters, fields=["name", "employee"]):
		frappe.db.set_value(
			"Technician Profile", profile.name, "current_wip", count_wip(profile.employee), update_modified=False
		)


@frappe.whitelist()
def available_technicians(branch: str, repair_category: str | None = None) -> list[dict]:
	"""Technicians at a branch with spare capacity, best fit first."""
	from a3_retail.api import require_permission

	require_permission("Technician Profile", "read")

	profiles = frappe.get_all(
		"Technician Profile",
		filters={"branch": branch, "is_active": 1},
		fields=["name", "employee", "employee_name", "technician_level", "max_concurrent_jobs", "current_wip"],
	)

	for profile in profiles:
		profile["live_wip"] = count_wip(profile["employee"])
		profile["free_slots"] = (profile["max_concurrent_jobs"] or 0) - profile["live_wip"]
		profile["skilled"] = _has_skill(profile["name"], repair_category) if repair_category else True

	# Skilled and least loaded first.
	profiles.sort(key=lambda p: (not p["skilled"], -p["free_slots"]))
	return profiles


def _has_skill(profile_name: str, repair_category: str) -> bool:
	return bool(
		frappe.db.exists(
			"Technician Skill", {"parent": profile_name, "repair_category": repair_category}
		)
	)
