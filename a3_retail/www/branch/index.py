"""/branch — send people to the right place."""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.setup.staff_portal import HOME_PAGE, current_employee

	target = HOME_PAGE if (frappe.session.user != "Guest" and current_employee()) else "/branch/login"
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect
