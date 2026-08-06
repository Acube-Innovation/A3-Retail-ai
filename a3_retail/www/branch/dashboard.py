"""Branch staff welcome dashboard — /branch/dashboard."""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.api.staff import dashboard as dashboard_data
	from a3_retail.setup.staff_portal import current_employee

	context.no_cache = 1

	if frappe.session.user == "Guest" or not current_employee():
		frappe.local.flags.redirect_location = "/branch/login"
		raise frappe.Redirect

	context.data = dashboard_data()
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.greeting = _greeting()
	return context


def _greeting() -> str:
	from frappe import _
	from frappe.utils import now_datetime

	hour = now_datetime().hour
	if hour < 12:
		return _("Good morning")
	if hour < 17:
		return _("Good afternoon")
	return _("Good evening")
