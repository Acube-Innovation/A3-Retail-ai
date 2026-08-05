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


# ---------------------------------------------------------------- step 4 checks
@check("Items", ">= 19")
def _items():
	count = frappe.db.count("Item")
	return count, count >= 19


@check("Device items serialized", "0 problems")
def _device_items_serialized():
	rows = frappe.get_all("Item", filters={"a3_is_device": 1, "has_serial_no": 0}, pluck="name")
	return len(rows), not rows


@check("Duplicate IMEIs", "0")
def _duplicate_imei():
	rows = frappe.db.sql(
		"""select a3_imei_1, count(*) c from `tabSerial No`
		   where ifnull(a3_imei_1,'') != '' group by a3_imei_1 having c > 1"""
	)
	return len(rows), not rows


@check("Duplicate customer mobiles", "0")
def _duplicate_mobile():
	rows = frappe.db.sql(
		"""select a3_mobile_no, count(*) c from `tabCustomer`
		   where ifnull(a3_mobile_no,'') != '' group by a3_mobile_no having c > 1"""
	)
	return len(rows), not rows


@check("Customers", ">= 8")
def _customers():
	count = frappe.db.count("Customer")
	return count, count >= 8


@check("Suppliers", ">= 8")
def _suppliers():
	count = frappe.db.count("Supplier")
	return count, count >= 8


@check("Device Models", ">= 6")
def _device_models():
	count = frappe.db.count("Device Model")
	return count, count >= 6


# --------------------------------------------------------------- step 23 checks
# The four validation queries in scope 10.5, plus the July incentive table.
@check("Incentive schemes", "6")
def _incentive_schemes():
	count = frappe.db.count("Employee Incentive Scheme")
	return count, count >= 6


@check("Active staff without payroll CC", "0")
def _payroll_cost_centers():
	rows = frappe.db.sql(
		"""select name from `tabEmployee`
		   where status = 'Active' and branch != 'Head Office'
		     and ifnull(payroll_cost_center, '') = ''"""
	)
	return len(rows), not rows


@check("Submitted assets without custodian", "0")
def _assets_without_custodian():
	rows = frappe.db.sql(
		"""select name from `tabAsset`
		   where docstatus = 1 and status = 'Submitted'
		     and ifnull(a3_assigned_employee, '') = ''"""
	)
	return len(rows), not rows


@check("Left employees holding assets", "0")
def _left_employees_with_assets():
	rows = frappe.db.sql(
		"""select a.name from `tabAsset` a
		   join `tabEmployee` e on e.name = a.a3_assigned_employee
		   where e.status = 'Left' and a.docstatus = 1"""
	)
	return len(rows), not rows


@check("Incentive posted vs payroll", "matched")
def _incentive_posted():
	rows = frappe.db.sql(
		"""select r.name, r.total_incentive, ifnull(sum(a.amount), 0) as posted
		   from `tabIncentive Calculation Run` r
		   join `tabIncentive Calculation Item` i on i.parent = r.name
		   left join `tabAdditional Salary` a on a.name = i.additional_salary
		   where r.status = 'Posted to Payroll' and r.docstatus = 1
		   group by r.name""",
		as_dict=True,
	)
	mismatched = [r.name for r in rows if abs(r.total_incentive - r.posted) > 1]
	return f"{len(rows)} runs", not mismatched


@check("July incentive table", "7 rows match")
def _july_incentive_table():
	"""The scope 10.2 demo table, recomputed from the seeded transactions."""
	expected = {
		"Vipin S": 8028,
		"Rafeeq M": 450,
		"Manoj Kumar": 2400,
		"Vishnu P": 6390,
		"Sajeer K": 0,
		"Rijo Thomas": 5670,
		"Sneha M": 1640,
	}
	rows = frappe.db.sql(
		"""select i.employee_name, sum(i.final_incentive) as payout
		   from `tabIncentive Calculation Item` i
		   join `tabIncentive Calculation Run` r on r.name = i.parent
		   where r.docstatus = 1 and r.from_date = '2026-07-01'
		   group by i.employee_name""",
		as_dict=True,
	)
	actual = {row.employee_name: row.payout for row in rows}
	matched = sum(1 for name, value in expected.items() if abs(actual.get(name, -1) - value) < 1)
	return f"{matched} rows", matched == len(expected)


# --------------------------------------------------------------- step 24 checks
@check("Print formats", "24")
def _print_formats():
	count = frappe.db.count("Print Format", {"module": ["like", "A3 Retail%"]})
	return count, count >= 24


@check("Branch letter heads", "3")
def _letter_heads():
	count = frappe.db.count("Letter Head", {"name": ["like", "% Letter Head"]})
	return count, count >= 3


@check("Print formats render", "24 of 24")
def _print_render():
	from a3_retail.setup.print_formats import smoke_test

	result = smoke_test(as_pdf=False, verbose=False)
	rendered = result["total"] - len(result["failed"])
	return f"{rendered} of {result['total']}", not result["failed"]


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
