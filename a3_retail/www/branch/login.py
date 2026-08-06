"""Branch staff sign-in — /branch/login (separate from the ERPNext desk)."""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.setup.staff_portal import HOME_PAGE, current_employee

	context.no_cache = 1
	context.no_header = 1
	context.hide_login = 1

	# Already signed in as staff? Go straight in.
	if frappe.session.user != "Guest" and current_employee():
		frappe.local.flags.redirect_location = HOME_PAGE
		raise frappe.Redirect

	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.branches = frappe.get_all(
		"Branch Profile", filters={"is_active": 1}, pluck="branch", order_by="branch"
	)
	context.home_page = HOME_PAGE
	return context
