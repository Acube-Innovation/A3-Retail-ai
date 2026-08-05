"""Portal page: /feedback/<token> (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.utils.tokens import verify

	parts = (frappe.local.request.path or "").strip("/").split("/")
	token = parts[1] if len(parts) >= 2 and parts[0] == "feedback" else frappe.form_dict.get("token")

	context.no_cache = 1
	context.token = token
	context.error = None
	context.job = None

	name = verify(token, "Service Job Card", "feedback") if token else None
	if not name:
		context.error = _("This feedback link is not valid.")
		return context

	job = frappe.get_doc("Service Job Card", name)
	context.job = job
	context.already = bool(job.customer_feedback)
	return context
