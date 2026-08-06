"""Branch app dashboard — /branch/dashboard.

Standalone document, server-rendered for the first paint and refreshed from
`a3_retail.api.staff.dashboard` afterwards. Nothing about the ERPNext desk is
loaded here; the page talks to the same API a mobile client would.
"""

import frappe

no_cache = 1

NAV = [
	("dashboard", "Dashboard", "#top"),
	("work", "What needs you", "#work"),
	("activity", "Branch activity", "#activity"),
]


def get_context(context):
	from a3_retail.api.staff import dashboard as dashboard_data
	from a3_retail.setup.staff_portal import current_employee

	context.no_cache = 1

	if frappe.session.user == "Guest" or not current_employee():
		frappe.local.flags.redirect_location = "/branch/login"
		raise frappe.Redirect

	data = dashboard_data()
	context.data = data
	context.me = data["context"]
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.greeting = _greeting()
	context.initials = _initials(context.me["employee_name"])
	context.nav = NAV
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
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


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	if not parts:
		return "A3"
	if len(parts) == 1:
		return parts[0][:2].upper()
	return (parts[0][0] + parts[-1][0]).upper()
