# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Shared test fixtures.

`before_tests` sets `frappe.flags.skip_test_records`, so the suite builds exactly
the records it needs here instead of pulling in ERPNext's `_Test *` records
(which predate india_compliance and fail its GST validation).
"""

import frappe
from frappe.utils import flt, getdate

from a3_retail.setup.accounts import ensure_branch_cost_centers
from a3_retail.setup.company import COMPANY_NAME
from a3_retail.setup.company import run as setup_company
from a3_retail.utils.gst import normalize_gstin

GSTIN = normalize_gstin("32AABCM1234K1Z5")

BRANCHES = {
	"Kochi": {"code": "KCH", "type": "Sales & Service", "hq": 1, "gstin": GSTIN},
	"Thiruvananthapuram": {"code": "TVM", "type": "Sales & Service", "hq": 0, "gstin": GSTIN},
	"Kozhikode": {"code": "CLT", "type": "Sales Only", "hq": 0, "gstin": GSTIN},
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


def ensure_customer(mobile: str = "9847012345", name: str = "Rahul Krishnan") -> str:
	"""A customer to hang test transactions off."""
	existing = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	if existing:
		return existing

	doc = frappe.new_doc("Customer")
	doc.customer_name = name
	doc.customer_type = "Individual"
	doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	doc.a3_mobile_no = mobile
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_sales_invoice(item_code: str = "ACC-TGL-A55", rate: float = 299) -> str:
	"""A submitted invoice for tests that need one to link against.

	Uses an accessory so the device-serial guard (step 12) does not apply.
	"""
	existing = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
	if existing:
		return existing

	branch = ensure_branch("Kochi", "KCH")
	doc = frappe.new_doc("Sales Invoice")
	doc.customer = ensure_customer()
	doc.company = branch.company
	doc.branch = branch.branch
	doc.set_warehouse = branch.default_warehouse
	doc.update_stock = 0
	doc.append("items", {"item_code": item_code, "qty": 1, "rate": rate})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def ensure_stock(item_code: str, warehouse: str, qty: float = 10, rate: float = 800) -> float:
	"""Top a warehouse up to `qty` of an item via a Material Receipt.

	Stock-moving tests cannot rely on the demo opening stock: ERPNext commits
	while reposting the stock ledger, so quantities really are consumed as the
	suite runs. Each test that moves stock provisions its own.
	"""
	current = flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	)
	shortfall = flt(qty) - current
	if shortfall <= 0:
		return current

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.company = frappe.db.get_single_value("Global Defaults", "default_company")
	entry.append(
		"items",
		{
			"item_code": item_code,
			"qty": shortfall,
			"t_warehouse": warehouse,
			"basic_rate": flt(rate),
		},
	)
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return flt(qty)


def ensure_salary_structure(employee: str, base: float = 25000) -> str:
	"""Assign a minimal salary structure so Additional Salary can be raised.

	ERPNext refuses an Additional Salary for an employee with no structure, which
	is what damage recovery through payroll depends on.
	"""
	company = ensure_company()
	name = "A3 Retail Test Structure"

	if not frappe.db.exists("Salary Component", "Basic"):
		component = frappe.new_doc("Salary Component")
		component.salary_component = "Basic"
		component.salary_component_abbr = "B"
		component.type = "Earning"
		component.flags.ignore_permissions = True
		component.insert(ignore_permissions=True)

	if not frappe.db.exists("Salary Structure", name):
		structure = frappe.new_doc("Salary Structure")
		structure.__newname = name
		structure.company = company
		structure.payroll_frequency = "Monthly"
		structure.currency = "INR"
		structure.append("earnings", {"salary_component": "Basic", "amount": base})
		structure.flags.ignore_permissions = True
		structure.flags.ignore_mandatory = True
		structure.insert(ignore_permissions=True)
		structure.submit()

	assignment = frappe.db.exists(
		"Salary Structure Assignment",
		{"employee": employee, "salary_structure": name, "docstatus": 1},
	)
	if not assignment:
		doc = frappe.new_doc("Salary Structure Assignment")
		doc.employee = employee
		doc.salary_structure = name
		doc.company = company
		# Never before the person joined — ERPNext refuses that, and whichever
		# employee this fixture is handed may have started at any date.
		joined = frappe.db.get_value("Employee", employee, "date_of_joining")
		doc.from_date = max(getdate(joined or "2024-01-01"), getdate("2024-01-01"))
		doc.base = base
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		doc.submit()

	return name
