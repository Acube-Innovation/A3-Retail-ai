import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SVC = "A3 Retail Service"

ISSUE_CATEGORIES = (
    "Display\nBattery\nCharging\nAudio\nCamera\nNetwork\nSoftware\nBoard Level\n"
    "Physical Damage\nLiquid Damage\nPerformance\nOther"
)
REPAIR_CATEGORIES = (
    "Software\nHardware - Component\nHardware - Board Level\nPhysical Damage\n"
    "Liquid Damage\nBattery\nDisplay\nAccessory"
)
PRIORITIES = "Low\nNormal\nHigh\nUrgent (Same Day)"
WARRANTY_TYPES = (
    "Brand Warranty\nExtended Warranty\nScreen Protection Plan\nInsurance Claim\n"
    "Out of Warranty\nGoodwill/Free"
)
TECH_LEVELS = "L1 - Software\nL2 - Hardware\nL3 - Board Level\nL4 - Specialist"

SVC_PERMS = [
    ("System Manager", "CRUD"),
    ("A3 Retail Admin", "CRUD"),
    ("Service Manager", "CRUD"),
    ("Branch Manager", "R"),
    ("Technician", "R"),
    ("Reception Executive", "R"),
]

print("Step 6 — service masters")

DT(
    "Service Issue Type",
    SVC,
    [
        f("issue_name", "Data", "Issue Name", reqd=1, unique=1, in_list_view=1),
        f("category", "Select", "Category", ISSUE_CATEGORIES, reqd=1, in_list_view=1, in_standard_filter=1),
        f("standard_tat_hours", "Int", "Standard TAT (hours)", default="24", in_list_view=1),
        cb(),
        f("default_labour_item", "Link", "Default Labour Item", "Item"),
        f("default_part_item", "Link", "Default Part Item", "Item"),
        f("requires_data_backup", "Check", "Requires Data Backup"),
        f("is_warranty_void_trigger", "Check", "Voids Warranty",
          description="e.g. liquid damage — flags the warranty registration as Void"),
        f("is_active", "Check", "Active", default="1"),
    ],
    autoname="field:issue_name",
    title_field="issue_name",
    sort_field="issue_name",
    sort_order="ASC",
    perms_spec=SVC_PERMS,
).write()

DT(
    "Technician Skill",
    SVC,
    [
        f("brand", "Link", "Brand", "Brand", in_list_view=1),
        f("repair_category", "Select", "Repair Category", REPAIR_CATEGORIES, in_list_view=1),
        f("proficiency", "Select", "Proficiency", "Beginner\nIntermediate\nExpert",
          default="Intermediate", in_list_view=1),
        f("certified_on", "Date", "Certified On"),
    ],
    istable=1,
).write()

TAT_CONTROLLER = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service TAT Policy — how long a repair category is allowed to take (scope 3.7)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceTATPolicy(Document):
	def validate(self):
		if self.tat_hours is not None and self.tat_hours <= 0:
			frappe.throw(_("TAT Hours must be greater than zero."))

		if self.escalate_after_hours and self.escalate_after_hours < self.tat_hours:
			frappe.throw(_("Escalation must happen after the TAT, not before it."))

		if self.warn_at_percent and not (0 < self.warn_at_percent <= 100):
			frappe.throw(_("Warn At % must be between 1 and 100."))
'''

DT(
    "Service TAT Policy",
    SVC,
    [
        f("policy_name", "Data", "Policy Name", reqd=1, unique=1, in_list_view=1),
        f("repair_category", "Select", "Repair Category", REPAIR_CATEGORIES, reqd=1,
          in_list_view=1, in_standard_filter=1),
        f("priority", "Select", "Priority", PRIORITIES, default="Normal", in_list_view=1,
          in_standard_filter=1),
        f("warranty_type", "Select", "Warranty Type", "\n" + WARRANTY_TYPES,
          description="Optional narrowing — blank applies to every warranty type"),
        f("branch", "Link", "Branch", "Branch", description="Blank applies to every branch"),
        cb(),
        f("tat_hours", "Int", "TAT (hours)", reqd=1, default="48", in_list_view=1),
        f("exclude_non_working_hours", "Check", "Count Working Hours Only", default="1",
          description="Uses Branch Profile working hours, weekly off and Holiday List"),
        f("warn_at_percent", "Percent", "Warn At %", default="80"),
        f("is_active", "Check", "Active", default="1"),

        sb("escalation_section", "Escalation"),
        f("escalate_after_hours", "Int", "Escalate After (hours)"),
        f("escalate_to_role", "Link", "Escalate To Role", "Role"),
        cb(),
        f("notify_customer_on_delay", "Check", "Notify Customer on Delay"),
    ],
    autoname="field:policy_name",
    title_field="policy_name",
    perms_spec=SVC_PERMS,
).write(controller=TAT_CONTROLLER)

TECH_CONTROLLER = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
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
'''

DT(
    "Technician Profile",
    SVC,
    [
        f("employee", "Link", "Employee", "Employee", reqd=1, unique=1, in_list_view=1),
        f("employee_name", "Data", "Employee Name", fetch_from="employee.employee_name",
          read_only=1, in_list_view=1),
        f("branch", "Link", "Branch", "Branch", fetch_from="employee.branch", read_only=1,
          in_list_view=1, in_standard_filter=1),
        f("technician_level", "Select", "Technician Level", TECH_LEVELS, reqd=1,
          default="L2 - Hardware", in_list_view=1, in_standard_filter=1),
        cb(),
        f("max_concurrent_jobs", "Int", "Max Concurrent Jobs", default="6"),
        f("current_wip", "Int", "Current WIP", read_only=1, in_list_view=1),
        f("incentive_scheme", "Link", "Incentive Scheme", "Employee Incentive Scheme"),
        f("is_active", "Check", "Active", default="1"),

        sb("skills_section", "Skills & Certifications"),
        f("skills", "Table", "Skills", "Technician Skill"),
        f("certifications", "Attach", "Certifications"),
    ],
    autoname="prompt",
    title_field="employee_name",
    search_fields="employee_name,branch,technician_level",
    track_changes=1,
    perms_spec=SVC_PERMS,
).write(controller=TECH_CONTROLLER)
