"""A3 Retail — customer portal API (scope 13.1).

Portal access is token + OTP, never a login. Guest is allowed to call these, so
every entry point rate-limits and validates its own inputs rather than relying on
a permission check.
"""

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from a3_retail.utils import commit_if_not_testing

from a3_retail.api.customer import normalize_mobile

OTP_LENGTH = 6


def _hash(value: str) -> str:
	return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _settings():
	return {
		"validity": cint(frappe.db.get_single_value("A3 Retail Settings", "otp_validity_minutes")) or 10,
		"max_attempts": cint(frappe.db.get_single_value("A3 Retail Settings", "otp_max_attempts")) or 5,
		"max_per_hour": cint(frappe.db.get_single_value("A3 Retail Settings", "otp_max_requests_per_hour")) or 5,
	}


def _client_ip() -> str | None:
	return getattr(frappe.local, "request_ip", None)


@frappe.whitelist(allow_guest=True)
def request_otp(mobile_no: str, purpose: str = "General", reference_doctype: str | None = None,
                reference_name: str | None = None) -> dict:
	"""Issue a 6-digit OTP. Rate limited per number per hour (scope 13.1)."""
	mobile = normalize_mobile(mobile_no)
	if len(mobile) != 10:
		frappe.throw(_("Enter a valid 10-digit mobile number."))

	config = _settings()
	recent = frappe.db.count(
		"Portal OTP",
		{"mobile_no": mobile, "creation": [">", add_to_date(now_datetime(), hours=-1)]},
	)
	if recent >= config["max_per_hour"]:
		frappe.throw(
			_("Too many OTP requests. Please try again after an hour."),
			frappe.TooManyRequestsError if hasattr(frappe, "TooManyRequestsError") else frappe.ValidationError,
		)

	otp = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"

	doc = frappe.new_doc("Portal OTP")
	doc.mobile_no = mobile
	doc.otp_hash = _hash(otp)
	doc.purpose = purpose
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.expires_on = add_to_date(now_datetime(), minutes=config["validity"])
	doc.ip_address = _client_ip()
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	commit_if_not_testing()

	# Delivery goes through the communication engine (step 22). In developer
	# mode the OTP is returned so the flow can be exercised without a WABA.
	payload = {"sent": True, "mobile_no": mobile, "expires_on": str(doc.expires_on)}
	if frappe.conf.get("developer_mode"):
		payload["otp"] = otp

	_queue_otp_message(mobile, otp, purpose)
	return payload


def _queue_otp_message(mobile: str, otp: str, purpose: str):
	"""Hand the OTP to the messaging layer if it is configured."""
	try:
		from a3_retail.communication.engine import send_otp

		send_otp(mobile, otp, purpose)
	except Exception:
		# Never fail OTP issuance because messaging is not configured yet.
		frappe.log_error(frappe.get_traceback(), "A3 Retail: OTP dispatch failed")


@frappe.whitelist(allow_guest=True)
def verify_otp(mobile_no: str, otp: str, purpose: str = "General") -> dict:
	"""Verify an OTP. Burns the attempt whether or not it matched."""
	mobile = normalize_mobile(mobile_no)
	config = _settings()

	name = frappe.db.get_value(
		"Portal OTP",
		{"mobile_no": mobile, "purpose": purpose, "verified": 0},
		"name",
		order_by="creation desc",
	)
	if not name:
		frappe.throw(_("Request an OTP first."))

	doc = frappe.get_doc("Portal OTP", name)

	if get_datetime(doc.expires_on) < now_datetime():
		frappe.throw(_("This OTP has expired. Please request a new one."))

	if cint(doc.attempts) >= config["max_attempts"]:
		frappe.throw(_("Too many incorrect attempts. Please request a new OTP."))

	doc.db_set("attempts", cint(doc.attempts) + 1, update_modified=False)

	if doc.otp_hash != _hash(otp):
		commit_if_not_testing()
		frappe.throw(_("Incorrect OTP."))

	doc.db_set("verified", 1, update_modified=False)
	doc.db_set("verified_on", now_datetime(), update_modified=False)
	commit_if_not_testing()

	return {"verified": True, "token": _issue_session_token(mobile, purpose)}


def _issue_session_token(mobile: str, purpose: str) -> str:
	"""Short-lived proof-of-OTP kept in the guest session."""
	token = secrets.token_urlsafe(24)
	frappe.cache().set_value(
		f"a3_portal_session:{token}", {"mobile": mobile, "purpose": purpose}, expires_in_sec=1800
	)
	return token


def verify_session_token(token: str, purpose: str | None = None) -> dict | None:
	if not token:
		return None
	data = frappe.cache().get_value(f"a3_portal_session:{token}")
	if not data:
		return None
	if purpose and data.get("purpose") != purpose:
		return None
	return data


@frappe.whitelist(allow_guest=True)
def submit_estimate_decision(token: str, decision: str, otp_token: str | None = None,
                             approver_name: str | None = None, remarks: str | None = None,
                             optional_items: str | None = None) -> dict:
	"""Record an Approve / Reject / Request Revision from the portal."""
	from a3_retail.a3_retail_service.doctype.service_estimate.service_estimate import resolve_token

	if decision not in ("Approved", "Rejected", "Revision Requested"):
		frappe.throw(_("Unknown decision."))

	estimate = resolve_token(token)

	session = verify_session_token(otp_token, "Estimate Approval")
	if not session:
		frappe.throw(_("Verify the OTP sent to your mobile before deciding."), frappe.PermissionError)

	if normalize_mobile(session["mobile"]) != normalize_mobile(estimate.customer_mobile):
		frappe.throw(_("This OTP does not belong to the customer on this estimate."), frappe.PermissionError)

	selected = frappe.parse_json(optional_items) if optional_items else None

	estimate.approval_channel = "Portal"
	estimate.record_decision(
		decision,
		approver_name=approver_name,
		remarks=remarks,
		ip_address=_client_ip(),
		optional_items=selected,
	)

	return {
		"estimate": estimate.name,
		"status": estimate.approval_status,
		"grand_total": estimate.grand_total,
		"sales_order": estimate.sales_order,
	}


def clear_expired_otps():
	"""Daily — drop OTP rows older than a day."""
	frappe.db.delete("Portal OTP", {"creation": ["<", add_to_date(now_datetime(), days=-1)]})
	commit_if_not_testing()
