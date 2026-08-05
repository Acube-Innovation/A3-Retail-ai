"""Seed 03 — Departments, designations, grades, 17 Employees, 13 Users (scope 10.1, 13.2)."""

import frappe

from a3_retail.overrides.employee import sync_user_permissions
from a3_retail.setup.accounts import ensure_branch_cost_centers

DEPARTMENTS = [
	"Retail Sales",
	"Service & Technical",
	"Customer Care",
	"Telecalling",
	"Warehouse & Logistics",
	"Accounts",
	"HR & Admin",
	"Management",
]

DESIGNATIONS = [
	"Branch Manager",
	"Service Manager",
	"Sales Executive",
	"Senior Sales Executive",
	"Reception Executive",
	"Technician L1",
	"Technician L2",
	"Technician L3",
	"Store Keeper",
	"Delivery Executive",
	"Telecaller",
	"Helpdesk Agent",
	"EMI Coordinator",
	"Accountant",
	"Accounts Manager",
	"HR Executive",
	"HR Manager",
]

GRADES = [
	("G1 Trainee", 15000),
	("G2 Executive", 18000),
	("G3 Senior Executive", 25000),
	("G4 Supervisor", 35000),
	("G5 Manager", 50000),
	("G6 Head", 70000),
]

# employee_name, designation, department, branch, grade, doj, base, user_id, roles
EMPLOYEES = [
	("Arun Menon", "Branch Manager", "Retail Sales", "Kochi", "G5 Manager", "2019-06-01", 55000,
	 "arun@mobileworld.in", ["Branch Manager", "Sales Executive"]),
	("Vipin S", "Senior Sales Executive", "Retail Sales", "Kochi", "G3 Senior Executive", "2021-03-15", 24000,
	 "vipin@mobileworld.in", ["Sales Executive"]),
	("Reshma K", "Reception Executive", "Customer Care", "Kochi", "G2 Executive", "2023-01-10", 18000,
	 "reshma@mobileworld.in", ["Reception Executive"]),
	("Vishnu P", "Technician L3", "Service & Technical", "Kochi", "G4 Supervisor", "2018-08-20", 38000,
	 "vishnu@mobileworld.in", ["Technician", "Service Manager"]),
	("Sajeer K", "Technician L2", "Service & Technical", "Kochi", "G3 Senior Executive", "2020-11-05", 26000,
	 "sajeer@mobileworld.in", ["Technician"]),
	("Anoop R", "Technician L1", "Service & Technical", "Kochi", "G2 Executive", "2024-02-01", 17000,
	 "anoop@mobileworld.in", ["Technician"]),
	("Jithin Raj", "Delivery Executive", "Warehouse & Logistics", "Kochi", "G1 Trainee", "2024-06-01", 15000,
	 None, []),
	("Manoj Kumar", "EMI Coordinator", "Retail Sales", "Kochi", "G3 Senior Executive", "2022-08-01", 22000,
	 "manoj@mobileworld.in", ["EMI Coordinator", "Sales Executive"]),
	("Nikhil Das", "Branch Manager", "Retail Sales", "Thiruvananthapuram", "G5 Manager", "2020-02-01", 48000,
	 "nikhil@mobileworld.in", ["Branch Manager"]),
	("Divya P", "Reception Executive", "Customer Care", "Thiruvananthapuram", "G2 Executive", "2023-07-01", 17000,
	 None, []),
	("Rijo Thomas", "Technician L2", "Service & Technical", "Thiruvananthapuram", "G3 Senior Executive",
	 "2021-09-12", 25000, "rijo@mobileworld.in", ["Technician"]),
	("Fahad Rahman", "Branch Manager", "Retail Sales", "Kozhikode", "G5 Manager", "2022-04-01", 45000,
	 "fahad@mobileworld.in", ["Branch Manager"]),
	("Rafeeq M", "Sales Executive", "Retail Sales", "Kozhikode", "G2 Executive", "2024-01-15", 19000,
	 None, []),
	("Sneha M", "Telecaller", "Telecalling", "Head Office", "G2 Executive", "2024-03-01", 16000,
	 "sneha@mobileworld.in", ["Telecaller"]),
	("Arjun V", "Telecaller", "Telecalling", "Head Office", "G1 Trainee", "2025-01-06", 14000,
	 None, []),
	("Lakshmi Nair", "Accounts Manager", "Accounts", "Head Office", "G5 Manager", "2018-04-01", 52000,
	 "lakshmi@mobileworld.in", ["Accounts Manager"]),
	("Priya Suresh", "HR Manager", "HR & Admin", "Head Office", "G5 Manager", "2019-01-15", 50000,
	 "priya@mobileworld.in", ["HR Manager"]),
]

ADMIN_USER = ("admin@mobileworld.in", "A3 Retail Admin", ["System Manager", "A3 Retail Admin"])

BRANCH_MANAGERS = {
	"Kochi": "Arun Menon",
	"Thiruvananthapuram": "Nikhil Das",
	"Kozhikode": "Fahad Rahman",
}


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	_ensure_holiday_list(company)
	_ensure_departments(company)
	_ensure_designations()
	_ensure_grades()
	_ensure_admin_user()

	for spec in EMPLOYEES:
		_ensure_employee(spec, company)

	_link_branch_managers()
	_sync_permissions()


def _ensure_holiday_list(company):
	name = "Kerala Holidays 2026-27"
	if frappe.db.exists("Holiday List", name):
		return name

	doc = frappe.new_doc("Holiday List")
	doc.holiday_list_name = name
	doc.from_date = "2026-04-01"
	doc.to_date = "2027-03-31"
	doc.weekly_off = "Sunday"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.get_weekly_off_dates()
	for date, description in (
		("2026-08-26", "Thiruvonam"),
		("2026-08-25", "First Onam"),
		("2026-04-14", "Vishu"),
		("2026-12-25", "Christmas"),
		("2027-03-10", "Eid al-Fitr"),
		("2026-05-27", "Bakrid"),
	):
		if not any(str(h.holiday_date) == date for h in doc.holidays):
			doc.append("holidays", {"holiday_date": date, "description": description})
	doc.save(ignore_permissions=True)
	return name


def _ensure_departments(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	for dept in DEPARTMENTS:
		if frappe.db.exists("Department", f"{dept} - {abbr}") or frappe.db.exists("Department", dept):
			continue
		doc = frappe.new_doc("Department")
		doc.department_name = dept
		doc.company = company
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def _ensure_designations():
	for designation in DESIGNATIONS:
		if frappe.db.exists("Designation", designation):
			continue
		doc = frappe.new_doc("Designation")
		doc.designation_name = designation
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _ensure_grades():
	for grade, base in GRADES:
		if frappe.db.exists("Employee Grade", grade):
			continue
		doc = frappe.new_doc("Employee Grade")
		doc.__newname = grade
		doc.default_base_pay = base
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _ensure_user(email, full_name, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		parts = full_name.split(" ", 1)
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = parts[0]
		user.last_name = parts[1] if len(parts) > 1 else ""
		user.send_welcome_email = 0
		user.user_type = "System User"
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)

	existing = {r.role for r in user.get("roles", [])}
	added = False
	for role in roles:
		if role not in existing and frappe.db.exists("Role", role):
			user.append("roles", {"role": role})
			added = True
	if added:
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
	return email


def _ensure_admin_user():
	email, name, roles = ADMIN_USER
	_ensure_user(email, name, roles)


def _department_name(dept, company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	scoped = f"{dept} - {abbr}"
	return scoped if frappe.db.exists("Department", scoped) else dept


def _ensure_employee(spec, company):
	name, designation, department, branch, grade, doj, base, user_id, roles = spec

	if frappe.db.exists("Employee", {"employee_name": name}):
		return frappe.db.get_value("Employee", {"employee_name": name}, "name")

	if user_id:
		_ensure_user(user_id, name, roles)

	cost_centers = ensure_branch_cost_centers(branch, company) if branch != "Head Office" else None

	parts = name.split(" ", 1)
	doc = frappe.new_doc("Employee")
	doc.first_name = parts[0]
	doc.last_name = parts[1] if len(parts) > 1 else ""
	doc.employee_name = name
	doc.company = company
	doc.gender = "Female" if name.split()[0] in ("Reshma", "Divya", "Sneha", "Lakshmi", "Priya") else "Male"
	doc.date_of_birth = "1992-05-15"
	doc.date_of_joining = doj
	doc.status = "Active"
	doc.branch = branch
	doc.department = _department_name(department, company)
	doc.designation = designation
	doc.grade = grade
	doc.holiday_list = "Kerala Holidays 2026-27"
	if user_id:
		doc.user_id = user_id
		doc.create_user_permission = 0
	if cost_centers:
		doc.payroll_cost_center = cost_centers["group"]
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _link_branch_managers():
	"""Seed 02 creates profiles before Employees exist — back-fill the manager."""
	for branch, manager_name in BRANCH_MANAGERS.items():
		profile_name = frappe.db.get_value("Branch Profile", {"branch": branch}, "name")
		employee = frappe.db.get_value("Employee", {"employee_name": manager_name}, "name")
		if not profile_name or not employee:
			continue
		if frappe.db.get_value("Branch Profile", profile_name, "branch_manager") == employee:
			continue
		profile = frappe.get_doc("Branch Profile", profile_name)
		profile.branch_manager = employee
		if branch == "Kochi":
			service_manager = frappe.db.get_value("Employee", {"employee_name": "Vishnu P"}, "name")
			profile.service_manager = service_manager
		profile.flags.ignore_permissions = True
		profile.save(ignore_permissions=True)


def _sync_permissions():
	for employee in frappe.get_all(
		"Employee",
		filters={"status": "Active", "user_id": ["is", "set"], "branch": ["is", "set"]},
		fields=["user_id", "branch"],
	):
		sync_user_permissions(employee.user_id, employee.branch)
