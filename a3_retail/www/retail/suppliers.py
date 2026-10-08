"""Supplier management — /retail/suppliers.

Guarded like the counters: a session, an Employee record and a branch.
"""

import frappe

no_cache = 1


def get_context(context):
	from a3_retail.api.pos import _profile
	from a3_retail.api.staff import session_context
	from a3_retail.setup.staff_portal import current_employee
	from a3_retail.www.retail import asset_version

	context.asset_v = asset_version()
	context.no_cache = 1

	if frappe.session.user == "Guest" or not current_employee():
		frappe.local.flags.redirect_location = "/retail/login"
		raise frappe.Redirect

	context.me = session_context()
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.initials = _initials(context.me["employee_name"])
	context.active = "suppliers"

	from a3_retail.print_helpers import a3_branch_profile

	context.profile = _profile(context.me["branch"])
	context.profile.state = (a3_branch_profile(context.me["branch"]) or {}).get("state")
	# What a payment can be made out of, so the dialog does not have to ask the
	# server before it can open.
	context.payment_modes = _payment_modes()
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	return context


def _payment_modes() -> list[str]:
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	rows = frappe.db.sql(
		"""select distinct mp.name
		   from `tabMode of Payment` mp
		   join `tabMode of Payment Account` mpa on mpa.parent = mp.name
		   where mp.enabled = 1 and mpa.company = %s
		     and ifnull(mpa.default_account, '') != ''
		   order by mp.name""", company, pluck=True)
	return rows or ["Cash"]


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	return "".join(part[0] for part in parts[:2]).upper() or "A3"
