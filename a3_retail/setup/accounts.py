# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Cost-center tree and chart-of-accounts additions (scope 11.1).

Sub-cost-centers per branch (Sales / Service) are what make
"is my service centre profitable?" answerable, which is the client's
requirement 13.
"""

import frappe

COST_CENTER_ROOT = "Head Office"


def get_company() -> str | None:
	return frappe.db.get_single_value("Global Defaults", "default_company")


def get_abbr(company: str) -> str:
	return frappe.get_cached_value("Company", company, "abbr")


def company_root_cost_center(company: str) -> str:
	"""The company's root (group) cost center."""
	root = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ""}, "name"
	)
	return root or f"{company} - {get_abbr(company)}"


def ensure_cost_center(name: str, company: str, parent: str, is_group: int = 0) -> str:
	"""Create a Cost Center if missing and return its full name."""
	abbr = get_abbr(company)
	full_name = f"{name} - {abbr}"
	if frappe.db.exists("Cost Center", full_name):
		return full_name

	cc = frappe.new_doc("Cost Center")
	cc.cost_center_name = name
	cc.company = company
	cc.parent_cost_center = parent
	cc.is_group = is_group
	cc.flags.ignore_permissions = True
	cc.insert(ignore_permissions=True)
	return cc.name


def ensure_branch_cost_centers(branch_name: str, company: str | None = None) -> dict:
	"""`<Branch>` group with `<Branch> Sales` and `<Branch> Service` leaves."""
	company = company or get_company()
	root = company_root_cost_center(company)

	group = ensure_cost_center(branch_name, company, root, is_group=1)
	return {
		"group": group,
		"sales": ensure_cost_center(f"{branch_name} Sales", company, group),
		"service": ensure_cost_center(f"{branch_name} Service", company, group),
	}


def ensure_head_office_cost_center(company: str | None = None) -> str:
	company = company or get_company()
	return ensure_cost_center(COST_CENTER_ROOT, company, company_root_cost_center(company), is_group=0)


def run():
	"""Create the tenant-level cost centers. Branch ones follow from Branch Profile."""
	company = get_company()
	if not company:
		return
	ensure_head_office_cost_center(company)


def set_branch_dimension_mandatory(mandatory: bool = True):
	"""Flip the Branch dimension to mandatory for P&L accounts (scope 11.7).

	Deferred until branches exist and branch stamping is live, otherwise every
	posting on a fresh site would be blocked.
	"""
	name = frappe.db.get_value("Accounting Dimension", {"document_type": "Branch"}, "name")
	if not name:
		return

	dimension = frappe.get_doc("Accounting Dimension", name)
	changed = False
	for row in dimension.get("dimension_defaults", []):
		if bool(row.mandatory_for_pl) != bool(mandatory):
			row.mandatory_for_pl = 1 if mandatory else 0
			changed = True

	if changed:
		dimension.flags.ignore_permissions = True
		dimension.save(ignore_permissions=True)
