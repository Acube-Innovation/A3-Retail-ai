"""Portal page: /pay/<token> (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.api.payments import payment_context

	parts = (frappe.local.request.path or "").strip("/").split("/")
	token = parts[1] if len(parts) >= 2 and parts[0] == "pay" else frappe.form_dict.get("token")

	context.no_cache = 1
	context.token = token
	context.error = None
	context.payment = None

	try:
		context.payment = payment_context(token)
	except frappe.PermissionError:
		context.error = _("This payment link is not valid.")
	return context
