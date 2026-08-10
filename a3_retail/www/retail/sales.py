"""Counter billing — /retail/sales.

The shell is server-rendered; everything after that is the POS API. Guarded the
same way as the dashboard: a session, an Employee record and a branch.
"""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.www.retail import asset_version

	context.asset_v = asset_version()
	from a3_retail.api.pos import _profile, item_groups
	from a3_retail.api.staff import session_context
	from a3_retail.setup.staff_portal import current_employee

	context.no_cache = 1

	if frappe.session.user == "Guest" or not current_employee():
		frappe.local.flags.redirect_location = "/retail/login"
		raise frappe.Redirect

	context.me = session_context()
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.initials = _initials(context.me["employee_name"])
	context.active = "sales"
	context.groups = item_groups()
	from a3_retail.print_helpers import a3_branch_profile

	context.profile = _profile(context.me["branch"])
	context.profile.state = (a3_branch_profile(context.me["branch"]) or {}).get("state")
	context.payment_modes = _payment_modes()
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	return context


def _payment_modes() -> list[str]:
	modes = frappe.get_all(
		"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name"
	)
	preferred = [mode for mode in ("Cash", "UPI", "Credit Card", "Debit Card") if mode in modes]
	return preferred + [mode for mode in modes if mode not in preferred]


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	if not parts:
		return "A3"
	if len(parts) == 1:
		return parts[0][:2].upper()
	return (parts[0][0] + parts[-1][0]).upper()
