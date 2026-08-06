"""Branch app sign-in — /branch/login.

A standalone document: it does not extend ERPNext's web template, so the desk
navbar, its bundles and its styling are all absent. The only thing shared with
ERPNext is the session the login endpoint opens.
"""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.setup.staff_portal import HOME_PAGE, current_employee

	context.no_cache = 1

	if frappe.session.user != "Guest" and current_employee():
		frappe.local.flags.redirect_location = HOME_PAGE
		raise frappe.Redirect

	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.home_page = HOME_PAGE
	return context
