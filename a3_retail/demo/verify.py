# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Post-seed verification (scope 14.6).

Prints a table of checks and returns a non-zero-ish result when any fails, so it
can gate a UAT hand-over:

    bench --site <site> execute a3_retail.demo.install.verify
"""

import frappe

# (label, callable -> actual, expectation callable, description of expectation)
CHECKS: list = []


def check(label: str, expected_desc: str):
	def decorator(fn):
		CHECKS.append((label, fn, expected_desc))
		return fn

	return decorator


# ---------------------------------------------------------------- step 2 checks
@check("Branch Profiles", "3")
def _branch_profiles():
	count = frappe.db.count("Branch Profile")
	return count, count == 3


@check("Branch warehouses (leaf)", ">= 10")
def _branch_warehouses():
	count = frappe.db.count("Warehouse", {"custom_branch": ["is", "set"], "is_group": 0})
	return count, count >= 10


@check("Branch accounting dimension", "present")
def _branch_dimension():
	exists = bool(frappe.db.exists("Accounting Dimension", {"document_type": "Branch"}))
	return "yes" if exists else "no", exists


@check("Branch cost centers", ">= 6")
def _branch_cost_centers():
	count = frappe.db.count("Cost Center", {"custom_branch": ["is", "set"]})
	return count, count >= 6


@check("Branch Profiles with all warehouses", "3")
def _profiles_complete():
	rows = frappe.get_all(
		"Branch Profile",
		fields=["name", "branch_type", "default_warehouse", "service_warehouse", "damaged_warehouse"],
	)
	complete = 0
	for row in rows:
		needs_service = row.branch_type in ("Service Only", "Sales & Service")
		if row.default_warehouse and row.damaged_warehouse and (row.service_warehouse or not needs_service):
			complete += 1
	return complete, complete == len(rows) and complete > 0


# ---------------------------------------------------------------- step 3 checks
@check("Demo users", ">= 13")
def _users():
	count = frappe.db.count("User", {"email": ["like", "%@mobileworld.in"]})
	return count, count >= 13


@check("Employees", "17")
def _employees():
	count = frappe.db.count("Employee", {"status": "Active"})
	return count, count >= 17


@check("Users without branch permission", "0")
def _users_without_branch_permission():
	"""Scope 13.5: every branch system user must be scoped to a Branch."""
	exempt = ("System Manager", "A3 Retail Admin", "Accounts Manager", "HR Manager", "Auditor")
	rows = frappe.db.sql(
		"""
		select u.name from `tabUser` u
		where u.enabled = 1 and u.user_type = 'System User'
		  and u.name like '%%@mobileworld.in'
		  and not exists (
			select 1 from `tabUser Permission` p
			where p.user = u.name and p.allow = 'Branch')
		  and not exists (
			select 1 from `tabHas Role` r
			where r.parent = u.name and r.role in %(exempt)s)
		""",
		{"exempt": exempt},
	)
	return len(rows), len(rows) == 0


@check("Custom DocPerm rows", ">= 100")
def _custom_docperms():
	count = frappe.db.count("Custom DocPerm")
	return count, count >= 100


@check("Branch managers linked", "3")
def _branch_managers():
	count = frappe.db.count("Branch Profile", {"branch_manager": ["is", "set"]})
	return count, count == 3


def run(verbose: bool = True):
	"""Execute every registered check; returns (passed, failed, rows)."""
	rows = []
	failed = 0
	for label, fn, expected in CHECKS:
		try:
			actual, ok = fn()
		except Exception as exc:  # a missing doctype means the step is not built yet
			actual, ok = f"error: {exc}", False
		rows.append((label, actual, expected, "PASS" if ok else "FAIL"))
		if not ok:
			failed += 1

	if verbose:
		width = max(len(r[0]) for r in rows) + 2
		print(f"\n{'Check'.ljust(width)}{'Actual'.ljust(14)}{'Expected'.ljust(14)}Result")
		print("-" * (width + 36))
		for label, actual, expected, result in rows:
			print(f"{label.ljust(width)}{str(actual).ljust(14)}{str(expected).ljust(14)}{result}")
		print(f"\n{len(rows) - failed}/{len(rows)} checks passed")

	return {"passed": len(rows) - failed, "failed": failed, "rows": rows}
