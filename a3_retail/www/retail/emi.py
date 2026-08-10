"""EMI Management — /retail/emi.

Guarded like the counters: a session, an Employee record and a branch.
"""

import frappe

no_cache = 1


def get_context(context):
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
	context.active = "emi"
	# The workspace opens on whichever tab the caller asked for, so a KPI on the
	# dashboard or a link from the counter lands on the right list.
	context.tab = frappe.form_dict.get("tab") or "overview"
	context.application = frappe.form_dict.get("application") or ""
	context.invoice = frappe.form_dict.get("invoice") or ""
	context.customer = frappe.form_dict.get("customer") or ""
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	return context


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	return "".join(part[0] for part in parts[:2]).upper() or "A3"
