"""Portal page: /approve-estimate/<token> (scope 3.4, 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	token = None
	parts = (frappe.local.request.path or "").strip("/").split("/")
	if len(parts) >= 2 and parts[0] == "approve-estimate":
		token = parts[1]
	token = token or frappe.form_dict.get("token")

	context.no_cache = 1
	context.token = token
	context.estimate = None
	context.error = None

	if not token:
		context.error = _("This link is incomplete.")
		return context

	from a3_retail.a3_retail_service.doctype.service_estimate.service_estimate import hash_token

	name = frappe.db.get_value("Service Estimate", {"portal_token_hash": hash_token(token)}, "name")
	if not name:
		context.error = _("This approval link is not valid.")
		return context

	estimate = frappe.get_doc("Service Estimate", name)
	context.estimate = estimate
	context.decided = estimate.approval_status in ("Approved", "Rejected", "Revision Requested", "Expired")
	context.expired = estimate.is_expired()
	context.masked_mobile = _mask(estimate.customer_mobile)
	context.branch_name = estimate.branch
	return context


def _mask(mobile):
	if not mobile or len(mobile) < 4:
		return mobile
	return f"{'X' * (len(mobile) - 4)}{mobile[-4:]}"
