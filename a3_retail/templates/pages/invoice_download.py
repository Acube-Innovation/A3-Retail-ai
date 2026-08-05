"""Portal page: /invoice/<token> (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.utils.tokens import verify

	parts = (frappe.local.request.path or "").strip("/").split("/")
	token = parts[1] if len(parts) >= 2 and parts[0] == "invoice" else frappe.form_dict.get("token")

	context.no_cache = 1
	context.error = None
	context.invoice = None

	name = verify(token, "Sales Invoice", "invoice") if token else None
	if not name:
		context.error = _("This invoice link is not valid.")
		return context

	context.invoice = frappe.get_doc("Sales Invoice", name)
	context.print_url = (
		"/api/method/frappe.utils.print_format.download_pdf"
		f"?doctype=Sales%20Invoice&name={name}&format=Retail%20Tax%20Invoice"
	)
	return context
