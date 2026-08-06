"""The service counter — /branch/service.

Guarded the same way as the sales counter: a session, an Employee record and a
branch. Everything after the shell is the service POS API.
"""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.api.pos import _profile
	from a3_retail.api.staff import session_context
	from a3_retail.setup.staff_portal import current_employee
	from a3_retail.www.branch import asset_version

	context.asset_v = asset_version()
	context.no_cache = 1

	if frappe.session.user == "Guest" or not current_employee():
		frappe.local.flags.redirect_location = "/branch/login"
		raise frappe.Redirect

	from a3_retail.api.service_pos import SERVICE_TYPES

	context.service_types = SERVICE_TYPES
	context.me = session_context()
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.initials = _initials(context.me["employee_name"])
	context.active = "services"
	context.today = frappe.utils.format_datetime(
		frappe.utils.now_datetime(), "EEEE, d MMM yyyy · h:mm a"
	)

	from a3_retail.print_helpers import a3_branch_profile

	context.profile = _profile(context.me["branch"])
	context.profile.state = (a3_branch_profile(context.me["branch"]) or {}).get("state")
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	return context


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	return "".join(part[0] for part in parts[:2]).upper() or "A3"
