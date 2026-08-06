"""Branch app landing page — /branch.

The front door of the branch application: what it is, who it is for, and one way
in. Public, because a member of staff has to be able to reach it before they have
a session — and because signing out lands here.
"""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.www.branch import asset_version

	context.asset_v = asset_version()
	from a3_retail.setup.staff_portal import current_employee

	context.no_cache = 1
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.branch_count = frappe.db.count("Branch Profile", {"is_active": 1}) or 0

	employee = current_employee() if frappe.session.user != "Guest" else None
	context.signed_in = bool(employee)
	context.employee_name = employee.employee_name if employee else ""
	context.branch = employee.branch if employee else ""
	return context
