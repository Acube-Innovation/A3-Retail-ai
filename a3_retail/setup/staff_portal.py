# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch staff portal accounts (`/branch`).

Shop-floor staff work in a small web app of their own, not in the ERPNext desk.
That separation is enforced by Frappe's own user type: a **Website User** is
refused at `/app` (frappe/www/app.py raises PermissionError), can only reach
whitelisted endpoints, and still passes through the same role permissions and
branch User Permissions as everyone else.

    bench --site <site> execute a3_retail.setup.staff_portal.provision

Head-office roles — Accounts Manager, HR Manager, A3 Retail Admin — stay System
Users, because their work genuinely lives in the desk.
"""

import frappe
from frappe.utils import cint

PORTAL_ROLE = "A3 Branch Staff"
HOME_PAGE = "/branch/dashboard"

# Roles whose work is in the desk; these users are left as System Users.
DESK_ROLES = {"System Manager", "A3 Retail Admin", "Accounts Manager", "HR Manager", "Auditor"}

# Shop-floor roles. Frappe derives `user_type` from the roles a user holds — one
# role with `desk_access` and the account is a System User again — so these are
# the roles that must be desk-free for the branch app to be the only way in.
BRANCH_ROLES = [
	"Branch Manager",
	"Service Manager",
	"Technician",
	"Reception Executive",
	"Sales Executive",
	"Store Keeper",
	"Telecaller",
	"Helpdesk Agent",
	"EMI Coordinator",
	"Delivery Executive",
]

# Frappe and HRMS add these to every desk account; a portal account must not hold
# them, or it is pulled back into the desk on the next save.
STRIP_ROLES = {"Desk User", "Employee", "Employee Self Service"}


def ensure_role() -> str:
	"""The role that says 'this account belongs to the branch portal'."""
	if not frappe.db.exists("Role", PORTAL_ROLE):
		role = frappe.new_doc("Role")
		role.role_name = PORTAL_ROLE
		role.desk_access = 0
		role.is_custom = 1
		role.flags.ignore_permissions = True
		role.insert(ignore_permissions=True)

	# `Role.home_page` is what sends a website user somewhere after login.
	frappe.db.set_value("Role", PORTAL_ROLE, {"desk_access": 0, "home_page": HOME_PAGE},
	                    update_modified=False)
	return PORTAL_ROLE


def close_desk_for_branch_roles(verbose: bool = False) -> list[str]:
	"""Take desk access off the shop-floor roles.

	This is the switch that makes the branch app the only door: while any of these
	roles keeps `desk_access`, Frappe promotes its holders back to System User and
	`/app` opens for them again.
	"""
	changed = []
	for role in BRANCH_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		if frappe.db.get_value("Role", role, "desk_access"):
			frappe.db.set_value("Role", role, "desk_access", 0, update_modified=False)
			changed.append(role)

	if verbose and changed:
		print(f"desk access removed from: {', '.join(changed)}")
	return changed


def provision(branch: str | None = None, password: str | None = None,
              verbose: bool = True) -> list[dict]:
	"""Turn branch employees into portal accounts. Idempotent.

	`password` is for demo and UAT sites only — on a live tenant leave it out and
	let each user set their own through the reset-password mail.
	"""
	ensure_role()
	close_desk_for_branch_roles()

	filters = {"status": "Active", "user_id": ["is", "set"], "branch": ["is", "set"]}
	if branch:
		filters["branch"] = branch

	provisioned = []
	for employee in frappe.get_all(
		"Employee", filters=filters,
		fields=["name", "employee_name", "user_id", "branch", "designation"],
	):
		if employee.branch == "Head Office":
			continue

		roles = set(frappe.get_roles(employee.user_id))
		if roles & DESK_ROLES:
			# A head-office role on a branch employee: leave them in the desk.
			continue

		_convert(employee.user_id, password)
		provisioned.append(
			{
				"employee": employee.employee_name,
				"designation": employee.designation,
				"branch": employee.branch,
				"user": employee.user_id,
				"roles": sorted(roles - {"All", "Guest", PORTAL_ROLE}),
			}
		)

	frappe.db.commit()

	if verbose:
		width = max((len(row["employee"]) for row in provisioned), default=10) + 2
		print(f"\n{'Employee'.ljust(width)}{'Designation'.ljust(24)}{'Branch'.ljust(20)}Login")
		print("-" * (width + 70))
		for row in provisioned:
			print(f"{row['employee'].ljust(width)}{(row['designation'] or '').ljust(24)}"
			      f"{row['branch'].ljust(20)}{row['user']}")
		print(f"\n{len(provisioned)} portal accounts ready at {HOME_PAGE}")

	return provisioned


def _convert(user: str, password: str | None):
	doc = frappe.get_doc("User", user)
	doc.send_welcome_email = 0

	# Drop the framework's desk roles, keep the functional ones.
	doc.set("roles", [row for row in doc.get("roles") or [] if row.role not in STRIP_ROLES])

	if not any(row.role == PORTAL_ROLE for row in doc.get("roles") or []):
		doc.append("roles", {"role": PORTAL_ROLE})

	if password:
		doc.new_password = password

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	# `set_system_user()` derives the type from role desk access on save; assert the
	# result rather than assume it, because a stray desk role silently undoes this.
	if frappe.db.get_value("User", user, "user_type") != "Website User":
		frappe.db.set_value("User", user, "user_type", "Website User", update_modified=False)


def revoke(user: str):
	"""Put an account back in the desk — the opposite of provision()."""
	doc = frappe.get_doc("User", user)
	doc.set("roles", [row for row in doc.get("roles") or [] if row.role != PORTAL_ROLE])
	if not any(row.role == "Desk User" for row in doc.get("roles") or []):
		doc.append("roles", {"role": "Desk User"})
	doc.user_type = "System User"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Session helpers used by the portal pages and API
# ---------------------------------------------------------------------------
def current_employee(user: str | None = None) -> dict | None:
	"""The Employee behind the logged-in portal user, or None."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None

	return frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["name", "employee_name", "branch", "designation", "department", "image",
		 "a3_staff_category"],
		as_dict=True,
	)


def is_portal_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user != "Guest" and PORTAL_ROLE in frappe.get_roles(user)


def has_desk_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return cint(frappe.db.get_value("User", user, "user_type") == "System User")
