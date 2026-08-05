# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Shared test fixtures.

`before_tests` sets `frappe.flags.skip_test_records`, so the suite builds exactly
the records it needs here instead of pulling in ERPNext's `_Test *` records
(which predate india_compliance and fail its GST validation).
"""

import frappe

from a3_retail.setup.accounts import ensure_branch_cost_centers
from a3_retail.setup.company import COMPANY_NAME
from a3_retail.setup.company import run as setup_company

BRANCHES = {
	"Kochi": {"code": "KCH", "type": "Sales & Service", "hq": 1, "gstin": "32AABCM1234K1Z5"},
	"Thiruvananthapuram": {"code": "TVM", "type": "Sales & Service", "hq": 0, "gstin": "32AABCM1234K1Z5"},
	"Kozhikode": {"code": "CLT", "type": "Sales Only", "hq": 0, "gstin": "32AABCM1234K1Z5"},
}


def ensure_company() -> str:
	setup_company()
	return COMPANY_NAME


def ensure_branch_record(branch_name: str) -> str:
	"""The HRMS `Branch` master — Branch Profile links to it."""
	if not frappe.db.exists("Branch", branch_name):
		doc = frappe.new_doc("Branch")
		doc.branch = branch_name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	return branch_name


def ensure_employee(employee_name: str, branch: str, designation: str = "Branch Manager") -> str:
	"""A minimal Active employee, used where Branch Profile needs a manager."""
	existing = frappe.db.get_value("Employee", {"employee_name": employee_name}, "name")
	if existing:
		return existing

	ensure_designation(designation)
	doc = frappe.new_doc("Employee")
	doc.first_name = employee_name
	doc.employee_name = employee_name
	doc.company = ensure_company()
	doc.date_of_joining = "2024-01-01"
	doc.date_of_birth = "1990-01-01"
	doc.gender = "Male"
	doc.status = "Active"
	doc.branch = ensure_branch_record(branch)
	doc.designation = designation
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_designation(designation: str) -> str:
	if not frappe.db.exists("Designation", designation):
		doc = frappe.new_doc("Designation")
		doc.designation_name = designation
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	return designation


def ensure_branch(branch_name: str = "Kochi", code: str | None = None):
	"""Create (or fetch) a Branch Profile with its warehouses and cost centers."""
	company = ensure_company()
	spec = BRANCHES.get(branch_name, {})
	code = code or spec.get("code") or branch_name[:3].upper()

	ensure_branch_record(branch_name)

	existing = frappe.db.get_value("Branch Profile", {"branch": branch_name}, "name")
	if existing:
		profile = frappe.get_doc("Branch Profile", existing)
		# Demo seed 02 inserts profiles before Employees exist (seed 03), so a
		# profile may be missing its mandatory manager. Back-fill it so tests can
		# save the document.
		if not profile.branch_manager:
			profile.branch_manager = ensure_employee(f"{branch_name} Manager", branch_name)
			profile.flags.ignore_permissions = True
			profile.save(ignore_permissions=True)
		return profile

	cost_centers = ensure_branch_cost_centers(branch_name, company)
	manager = ensure_employee(f"{branch_name} Manager", branch_name)

	profile = frappe.new_doc("Branch Profile")
	profile.branch = branch_name
	profile.branch_code = code
	profile.branch_type = spec.get("type", "Sales & Service")
	profile.is_head_office = spec.get("hq", 0)
	profile.company = company
	profile.cost_center = cost_centers["sales"]
	profile.sales_cost_center = cost_centers["sales"]
	profile.service_cost_center = cost_centers["service"]
	profile.branch_manager = manager
	profile.gstin = spec.get("gstin")
	profile.default_tat_hours = 48
	profile.weekly_off = "Sunday"
	profile.flags.ignore_permissions = True
	profile.insert(ignore_permissions=True)
	profile.reload()
	return profile


def ensure_all_branches() -> list:
	return [ensure_branch(name, spec["code"]) for name, spec in BRANCHES.items()]
