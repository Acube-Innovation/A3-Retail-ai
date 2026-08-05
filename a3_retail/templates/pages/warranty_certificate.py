"""Portal page: /warranty/<token> (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.utils.tokens import verify

	token = _token_from_path("warranty")
	context.no_cache = 1
	context.error = None
	context.registration = None

	name = verify(token, "Warranty Registration", "certificate") if token else None
	if not name:
		# Registrations created before signed links carry their own stored hash.
		name = _by_stored_hash(token)

	if not name:
		context.error = _("This certificate link is not valid.")
		return context

	context.registration = frappe.get_doc("Warranty Registration", name)
	context.claims = frappe.get_all(
		"Warranty Claim Log", filters={"parent": name},
		fields=["job_card", "claim_date", "amount", "status"], order_by="claim_date",
	)
	context.print_url = f"/api/method/frappe.utils.print_format.download_pdf?doctype=Warranty%20Registration&name={name}&format=Warranty%20Certificate&no_letterhead=0"
	return context


def _token_from_path(prefix: str) -> str | None:
	parts = (frappe.local.request.path or "").strip("/").split("/")
	if len(parts) >= 2 and parts[0] == prefix:
		return parts[1]
	return frappe.form_dict.get("token")


def _by_stored_hash(token: str | None) -> str | None:
	if not token:
		return None
	import hashlib

	digest = hashlib.sha256(token.encode()).hexdigest()
	return frappe.db.get_value("Warranty Registration", {"certificate_token_hash": digest}, "name")
