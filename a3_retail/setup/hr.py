# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""HRMS configuration: shifts, leave types, payroll and asset categories (scope 10.1, 10.3).

Departments, designations, grades and the holiday list are seeded with the demo
employees (demo/03_roles_users.py) because they are demo-shaped master data. What
lives here is the configuration every install needs regardless of demo data:
shift types, leave types, the salary component library, the salary structure and
the asset categories.

Every helper guards on `frappe.db.exists`, so `run()` is safe on every migrate.
"""

import frappe
from frappe.utils import flt

# ---------------------------------------------------------------------------
# Shifts (scope 10.1)
# ---------------------------------------------------------------------------
SHIFT_TYPES = [
	# name, start, end, auto attendance
	("General", "09:30:00", "19:30:00"),
	("Morning", "09:00:00", "17:00:00"),
	("Evening", "13:00:00", "21:00:00"),
	("Service Bay", "09:30:00", "18:30:00"),
]

# name, max per year, carry forward, is lwp, is optional/paid
LEAVE_TYPES = [
	("Casual Leave", 12, 0, 0),
	("Sick Leave", 8, 0, 0),
	("Earned Leave", 15, 1, 0),
	("Compensatory Off", 0, 0, 0),
	("Leave Without Pay", 0, 0, 1),
	("Maternity Leave", 182, 0, 0),
	("Paternity Leave", 7, 0, 0),
]

# name, abbr, type, formula/amount, condition, depends_on_payment_days
SALARY_COMPONENTS = [
	# `depends_on_payment_days` stays off wherever the formula already references a
	# component that is itself pro-rated — HRMS refuses the double deduction.
	("Basic", "B", "Earning", "base * 0.50", None, 1),
	("HRA", "HRA", "Earning", "B * 0.40", None, 0),
	("Conveyance Allowance", "CA", "Earning", "1600", None, 1),
	("Special Allowance", "SA", "Earning", "base - (B + HRA + CA)", None, 0),
	("Sales Incentive", "SI", "Earning", None, None, 0),
	("Technician Incentive", "TI", "Earning", None, None, 0),
	("Overtime", "OT", "Earning", None, None, 0),
	("PF (Employee)", "PF", "Deduction", "min(B, 15000) * 0.12", None, 0),
	("ESI (Employee)", "ESI", "Deduction", "gross_pay * 0.0075", "gross_pay <= 21000", 0),
	("Professional Tax", "PT", "Deduction", "200", "gross_pay > 20000", 0),
	("Damage Recovery", "DR", "Deduction", None, None, 0),
	("Advance Recovery", "AR", "Deduction", None, None, 0),
]

# Components paid through Additional Salary rather than the structure.
ADDITIONAL_SALARY_COMPONENTS = {
	"Sales Incentive",
	"Technician Incentive",
	"Overtime",
	"Damage Recovery",
	"Advance Recovery",
}

STRUCTURE_NAME = "A3 Retail Standard"

# scope 10.3
ASSET_CATEGORIES = [
	("Service Tools & Equipment", "Straight Line", 5),
	("Test & Measuring Instruments", "Straight Line", 5),
	("Computers & POS Hardware", "Written Down Value", 3),
	("Furniture & Display Fixtures", "Straight Line", 10),
	("Vehicles (Delivery)", "Written Down Value", 8),
	("Mobile Phones (Staff Issue)", "Straight Line", 3),
	("Air Conditioners & Electricals", "Straight Line", 10),
	("Software Licences", "Straight Line", 3),
]


def run():
	if not frappe.db.exists("DocType", "Shift Type"):
		# HRMS is not installed on this site; the rest of the app does not need it.
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		return

	ensure_shift_types()
	ensure_leave_types()
	ensure_salary_components(company)
	ensure_salary_structure(company)
	ensure_asset_categories(company)
	sync_payroll_cost_centers(company)


# ---------------------------------------------------------------------------
def ensure_shift_types():
	for name, start, end in SHIFT_TYPES:
		if frappe.db.exists("Shift Type", name):
			continue
		doc = frappe.new_doc("Shift Type")
		doc.__newname = name
		doc.start_time = start
		doc.end_time = end
		doc.holiday_list = _holiday_list()
		doc.enable_auto_attendance = 1
		doc.determine_check_in_and_check_out = "Alternating entries as IN and OUT during the same shift"
		doc.working_hours_calculation_based_on = "First Check-in and Last Check-out"
		doc.begin_check_in_before_shift_start_time = 60
		doc.allow_check_out_after_shift_end_time = 60
		doc.late_entry_grace_period = 10
		doc.early_exit_grace_period = 10
		doc.working_hours_threshold_for_half_day = 4
		doc.working_hours_threshold_for_absent = 2
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def _holiday_list() -> str | None:
	return frappe.db.get_value("Holiday List", {"holiday_list_name": ["like", "%Kerala%"]}, "name")


def ensure_leave_types():
	for name, max_leaves, carry_forward, is_lwp in LEAVE_TYPES:
		if frappe.db.exists("Leave Type", name):
			# ERPNext ships some of these names with a zero allowance; the policy
			# in scope 10.1 is what the shop actually grants.
			frappe.db.set_value(
				"Leave Type", name,
				{"max_leaves_allowed": max_leaves, "is_carry_forward": carry_forward,
				 "is_lwp": is_lwp},
				update_modified=False,
			)
			continue
		doc = frappe.new_doc("Leave Type")
		doc.leave_type_name = name
		doc.max_leaves_allowed = max_leaves
		doc.is_carry_forward = carry_forward
		doc.is_lwp = is_lwp
		doc.include_holiday = 0
		doc.applicable_after = 0
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def ensure_salary_components(company: str):
	abbr = frappe.get_cached_value("Company", company, "abbr")

	for name, short, kind, formula, condition, depends_on_days in SALARY_COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			# Names like "Basic" may already exist from an ERPNext demo with no
			# formula at all — the scope 10.1 salary structure is the authority.
			frappe.db.set_value(
				"Salary Component", name,
				{
					"type": kind,
					"amount_based_on_formula": 1 if formula else 0,
					"formula": formula or "",
					"condition": condition or "",
					"depends_on_payment_days": depends_on_days,
				},
				update_modified=False,
			)
			_ensure_component_account(name, company, abbr, kind)
			continue

		doc = frappe.new_doc("Salary Component")
		doc.salary_component = name
		doc.salary_component_abbr = short
		doc.type = kind
		doc.depends_on_payment_days = depends_on_days
		if formula:
			doc.amount_based_on_formula = 1
			doc.formula = formula
		if condition:
			doc.condition = condition
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		_ensure_component_account(name, company, abbr, kind)


def _ensure_component_account(component: str, company: str, abbr: str, kind: str):
	"""Point the component at an existing account so payroll can post."""
	doc = frappe.get_doc("Salary Component", component)
	if any(row.company == company for row in doc.get("accounts") or []):
		return

	if kind == "Earning":
		account = _first_existing(
			[f"Salary - {abbr}", f"Salaries - {abbr}", f"Indirect Expenses - {abbr}"]
		)
	else:
		account = _first_existing(
			[f"Payroll Payable - {abbr}", f"Duties and Taxes - {abbr}", f"Current Liabilities - {abbr}"]
		)
	if not account:
		return

	doc.append("accounts", {"company": company, "account": account})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def _first_existing(names: list[str]) -> str | None:
	for name in names:
		if frappe.db.exists("Account", name) and not frappe.db.get_value("Account", name, "is_group"):
			return name
	return None


def ensure_salary_structure(company: str):
	"""One structure for the whole company; branch lands via payroll_cost_center."""
	if frappe.db.exists("Salary Structure", STRUCTURE_NAME):
		return STRUCTURE_NAME

	doc = frappe.new_doc("Salary Structure")
	doc.__newname = STRUCTURE_NAME
	doc.company = company
	doc.is_active = "Yes"
	doc.payroll_frequency = "Monthly"
	doc.currency = frappe.get_cached_value("Company", company, "default_currency")
	doc.salary_slip_based_on_timesheet = 0
	doc.payment_account = _first_existing(
		[f"Cash - {frappe.get_cached_value('Company', company, 'abbr')}"]
	)

	for name, _short, kind, formula, condition, depends_on_days in SALARY_COMPONENTS:
		if name in ADDITIONAL_SALARY_COMPONENTS or not formula:
			continue
		row = {
			"salary_component": name,
			"amount_based_on_formula": 1,
			"formula": formula,
			"depends_on_payment_days": depends_on_days,
		}
		if condition:
			row["condition"] = condition
		doc.append("earnings" if kind == "Earning" else "deductions", row)

	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def assign_salary_structure(employee: str, base: float, from_date: str) -> str | None:
	"""Idempotent Salary Structure Assignment for one employee."""
	if not frappe.db.exists("Salary Structure", STRUCTURE_NAME):
		return None
	if frappe.db.exists(
		"Salary Structure Assignment",
		{"employee": employee, "salary_structure": STRUCTURE_NAME, "docstatus": ["!=", 2]},
	):
		return None

	employee_doc = frappe.get_cached_doc("Employee", employee)
	doc = frappe.new_doc("Salary Structure Assignment")
	doc.employee = employee
	doc.salary_structure = STRUCTURE_NAME
	doc.from_date = from_date
	doc.company = employee_doc.company
	doc.base = flt(base)
	doc.payroll_cost_center = employee_doc.payroll_cost_center
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def ensure_asset_categories(company: str):
	if not frappe.db.exists("DocType", "Asset Category"):
		return

	abbr = frappe.get_cached_value("Company", company, "abbr")
	fixed_asset = _first_existing([f"Furniture and Fixtures - {abbr}", f"Fixed Assets - {abbr}"])
	accumulated = _first_existing(
		[f"Accumulated Depreciation - {abbr}", f"Fixed Assets - {abbr}"]
	)
	depreciation_expense = _first_existing(
		[f"Depreciation - {abbr}", f"Indirect Expenses - {abbr}"]
	)

	for name, method, life_years in ASSET_CATEGORIES:
		if frappe.db.exists("Asset Category", name):
			continue

		doc = frappe.new_doc("Asset Category")
		doc.asset_category_name = name
		doc.enable_cwip_accounting = 0
		if fixed_asset and accumulated and depreciation_expense:
			doc.append(
				"accounts",
				{
					"company_name": company,
					"fixed_asset_account": fixed_asset,
					"accumulated_depreciation_account": accumulated,
					"depreciation_expense_account": depreciation_expense,
				},
			)
			doc.append(
				"finance_books",
				{
					"depreciation_method": method,
					"total_number_of_depreciations": life_years * 12,
					"frequency_of_depreciation": 1,
				},
			)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: asset category {name}")


def sync_payroll_cost_centers(company: str) -> int:
	"""Salary expense must land in the branch P&L (scope 10.1 technical note)."""
	from a3_retail.setup.accounts import ensure_branch_cost_centers

	updated = 0
	for employee in frappe.get_all(
		"Employee",
		filters={"status": "Active", "branch": ["is", "set"], "payroll_cost_center": ["is", "not set"]},
		fields=["name", "branch"],
	):
		if employee.branch == "Head Office":
			continue
		try:
			centers = ensure_branch_cost_centers(employee.branch, company)
		except Exception:
			continue
		if centers and centers.get("group"):
			frappe.db.set_value(
				"Employee", employee.name, "payroll_cost_center", centers["group"],
				update_modified=False,
			)
			updated += 1
	return updated


def stamp_row_dimensions(doc, method=None):
	"""Give every Journal Entry row the Branch dimension implied by its cost center.

	Payroll writes one accrual JE for the whole run with a row per branch cost
	center (from each employee's payroll_cost_center). Stamping the branch on the
	row is what makes the Branch-dimension P&L agree with the cost-center P&L.
	"""
	if not frappe.get_meta("Journal Entry Account").has_field("branch"):
		return

	for row in doc.get("accounts") or []:
		if row.get("branch") or not row.get("cost_center"):
			continue
		# The back-reference on Cost Center is `custom_branch` (scope step 2).
		branch = frappe.db.get_value("Cost Center", row.cost_center, "custom_branch")
		if branch:
			row.branch = branch
