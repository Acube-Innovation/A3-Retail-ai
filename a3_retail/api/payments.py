# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Online payments: request, checkout, webhook and reconciliation (scope 13.1).

The `payments` app is optional on this bench, so the Razorpay integration is
implemented directly against the gateway's webhook contract: the signature is
verified with the shared secret from A3 Retail Settings, the payload is recorded
on a Payment Request, and a Payment Entry is created and allocated to the
invoice. When the `payments` app *is* installed its Payment Gateway Account is
used for the checkout URL instead of ours.

Everything the customer touches is guest-accessible, so each entry point proves
the caller holds a signed token or a verified OTP before it reads anything.
"""

import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import flt, get_url, nowdate

from a3_retail.utils import commit_if_not_testing
from a3_retail.utils.tokens import portal_url, verify as verify_token

GATEWAY = "Razorpay"


# ---------------------------------------------------------------------------
# Payment Request
# ---------------------------------------------------------------------------
def request_on_ready_for_delivery(doc, method=None):
	"""A job card that becomes Ready for Delivery gets a payment link (scope 13.1)."""
	if doc.get("status") != "Ready for Delivery":
		return
	if flt(doc.get("outstanding_amount")) <= 0 and flt(doc.get("customer_payable")) <= 0:
		return
	if not frappe.db.get_single_value("A3 Retail Settings", "enable_online_payment"):
		return

	create_payment_request(doc)


def create_payment_request(job) -> str | None:
	"""One open Payment Request per job card, for whatever is still due."""
	amount = flt(job.get("outstanding_amount")) or flt(job.get("customer_payable")) - flt(
		job.get("advance_amount")
	)
	if amount <= 0:
		return None

	existing = frappe.db.get_value(
		"Payment Request",
		{"reference_doctype": "Service Job Card", "reference_name": job.name,
		 "status": ["in", ["Draft", "Requested", "Initiated"]], "docstatus": ["<", 2]},
		"name",
	)
	if existing:
		return existing

	request = frappe.new_doc("Payment Request")
	request.payment_request_type = "Inward"
	request.transaction_date = nowdate()
	request.reference_doctype = "Service Job Card"
	request.reference_name = job.name
	request.party_type = "Customer"
	request.party = job.customer
	request.grand_total = amount
	request.currency = frappe.get_cached_value("Company", job.company, "default_currency")
	request.mode_of_payment = "Online"
	request.email_to = job.get("customer_email") or None
	request.subject = _("Repair {0} is ready").format(job.name)
	request.message = _("Your device is ready for collection. Pay online to save time at the counter.")
	request.payment_gateway_account = gateway_account(job.company)
	request.flags.ignore_permissions = True
	request.flags.ignore_mandatory = True

	try:
		request.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: payment request for {job.name}")
		return None

	return request.name


def gateway_account(company: str | None = None) -> str | None:
	if not frappe.db.exists("DocType", "Payment Gateway Account"):
		return None
	filters = {"payment_gateway": GATEWAY}
	if company:
		filters["company"] = company
	return frappe.db.get_value("Payment Gateway Account", filters, "name") or frappe.db.get_value(
		"Payment Gateway Account", {"payment_gateway": GATEWAY}, "name"
	)


# ---------------------------------------------------------------------------
# Portal checkout
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def payment_context(token: str) -> dict:
	"""What /pay/<token> shows: the amount due and the checkout parameters."""
	job_card = verify_token(token, "Service Job Card", "payment")
	invoice = None if job_card else verify_token(token, "Sales Invoice", "payment")
	if not job_card and not invoice:
		frappe.throw(_("This payment link is not valid."), frappe.PermissionError)

	if job_card:
		job = frappe.get_doc("Service Job Card", job_card)
		amount = flt(job.outstanding_amount) or max(
			flt(job.customer_payable) - flt(job.advance_amount), 0
		)
		context = {
			"reference_doctype": "Service Job Card",
			"reference_name": job.name,
			"customer": job.customer_name,
			"description": _("Repair {0} — {1}").format(job.name, job.device_model or ""),
			"amount": amount,
			"paid": flt(job.advance_amount),
			"status": job.payment_status,
			"branch": job.branch,
		}
	else:
		si = frappe.get_doc("Sales Invoice", invoice)
		context = {
			"reference_doctype": "Sales Invoice",
			"reference_name": si.name,
			"customer": si.customer_name,
			"description": _("Invoice {0}").format(si.name),
			"amount": flt(si.outstanding_amount),
			"paid": flt(si.grand_total) - flt(si.outstanding_amount),
			"status": si.status,
			"branch": si.get("branch"),
		}

	context["currency"] = "INR"
	context["key_id"] = frappe.db.get_single_value("A3 Retail Settings", "razorpay_key_id")
	context["upi_uri"] = _upi_for(context)
	context["gateway_ready"] = bool(context["key_id"])
	return context


def _upi_for(context: dict) -> str:
	from a3_retail.utils.qr import upi_uri

	return upi_uri(context["amount"], context["reference_name"])


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def razorpay_webhook():
	"""Razorpay calls this on payment.captured / payment.failed (scope 13.1)."""
	body = frappe.request.get_data(as_text=True) if frappe.request else "{}"
	signature = frappe.get_request_header("X-Razorpay-Signature")

	if not verify_signature(body, signature):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "error": "invalid signature"}

	payload = json.loads(body or "{}")
	event = payload.get("event")
	entity = (payload.get("payload") or {}).get("payment", {}).get("entity", {}) or {}

	log = _record_transaction(event, entity, payload)

	if event == "payment.captured":
		_settle(log, entity)

	commit_if_not_testing()
	return {"ok": True, "event": event, "transaction": log}


def verify_signature(body: str, signature: str | None) -> bool:
	secret = frappe.db.get_single_value("A3 Retail Settings", "razorpay_webhook_secret")
	if not secret:
		# Nothing configured: refuse rather than trust an unsigned caller.
		return False
	if not signature:
		return False

	expected = hmac.new(secret.encode(), (body or "").encode(), hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, signature)


def _record_transaction(event: str, entity: dict, payload: dict) -> str | None:
	"""Keep the raw gateway record whether or not it can be matched."""
	if not frappe.db.exists("DocType", "Integration Request"):
		return None

	request = frappe.new_doc("Integration Request")
	request.integration_request_service = GATEWAY
	request.request_id = entity.get("id")
	request.status = "Completed" if event == "payment.captured" else "Failed"
	request.data = json.dumps(payload)[:140000]
	request.output = entity.get("notes") and json.dumps(entity.get("notes")) or ""
	request.flags.ignore_permissions = True
	try:
		request.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: gateway transaction log")
		return None
	return request.name


def _settle(log: str | None, entity: dict):
	"""Create the Payment Entry and allocate it to the invoice."""
	notes = entity.get("notes") or {}
	reference_doctype = notes.get("reference_doctype")
	reference_name = notes.get("reference_name")
	amount = flt(entity.get("amount")) / 100  # Razorpay reports paise

	if not reference_doctype or not frappe.db.exists(reference_doctype, reference_name or ""):
		# Unmatched — the reconciliation report picks it up from the log.
		return

	invoice = _invoice_for(reference_doctype, reference_name)
	if not invoice:
		return

	entry = _make_payment_entry(invoice, amount, entity.get("id"))
	if entry and reference_doctype == "Service Job Card":
		frappe.db.set_value("Service Job Card", reference_name, "payment_status", "Paid",
		                    update_modified=False)


def _invoice_for(doctype: str, name: str) -> str | None:
	if doctype == "Sales Invoice":
		return name
	return frappe.db.get_value("Service Job Card", name, "sales_invoice")


def _make_payment_entry(invoice: str, amount: float, transaction_id: str | None) -> str | None:
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if transaction_id and frappe.db.exists("Payment Entry", {"reference_no": transaction_id}):
		return None

	try:
		entry = get_payment_entry("Sales Invoice", invoice)
		entry.mode_of_payment = "Online"
		entry.reference_no = transaction_id or f"RZP-{frappe.generate_hash(length=8)}"
		entry.reference_date = nowdate()
		if amount:
			entry.paid_amount = amount
			entry.received_amount = amount
			for row in entry.references:
				row.allocated_amount = min(flt(row.outstanding_amount), amount)
		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
		return entry.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: gateway settlement for {invoice}")
		return None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
@frappe.whitelist()
def unmatched_transactions(days: int = 30) -> list[dict]:
	"""Gateway captures with no Payment Entry against them (scope 13.1)."""
	from a3_retail.api import require_permission
	from frappe.utils import add_days

	require_permission("Payment Entry")

	if not frappe.db.exists("DocType", "Integration Request"):
		return []

	rows = frappe.get_all(
		"Integration Request",
		filters={
			"integration_request_service": GATEWAY,
			"status": "Completed",
			"creation": [">", add_days(nowdate(), -abs(int(days)))],
		},
		fields=["name", "request_id", "creation", "data"],
		order_by="creation desc",
	)

	unmatched = []
	for row in rows:
		if row.request_id and frappe.db.exists("Payment Entry", {"reference_no": row.request_id}):
			continue
		payload = frappe.parse_json(row.data or "{}")
		entity = (payload.get("payload") or {}).get("payment", {}).get("entity", {}) or {}
		unmatched.append(
			{
				"transaction": row.request_id,
				"logged_on": str(row.creation),
				"amount": flt(entity.get("amount")) / 100,
				"method": entity.get("method"),
				"contact": entity.get("contact"),
				"reference": (entity.get("notes") or {}).get("reference_name"),
			}
		)
	return unmatched


def payment_url(doctype: str, name: str) -> str:
	return portal_url(doctype, name, "pay", "payment")


def site_payment_base() -> str:
	return get_url()
