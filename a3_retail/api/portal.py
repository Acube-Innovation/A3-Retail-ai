"""A3 Retail — customer portal API (scope 13.1).

Portal access is token + OTP, never a login. Guest is allowed to call these, so
every entry point rate-limits and validates its own inputs rather than relying on
a permission check.
"""

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime, nowdate

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


# ---------------------------------------------------------------------------
# Track Service — /track-service (scope 13.1)
# ---------------------------------------------------------------------------
TIMELINE_STAGES = [
	("Received", ("Open",)),
	("Diagnosis", ("Under Diagnosis",)),
	("Estimate", ("Estimate Pending", "Estimate Sent", "Estimate Approved", "Estimate Rejected")),
	("Repair", ("Awaiting Parts", "In Progress", "QC Pending", "QC Failed")),
	("Ready", ("Ready for Delivery",)),
	("Delivered", ("Delivered", "Closed")),
]


@frappe.whitelist(allow_guest=True)
def track_service(reference: str, mobile_no: str, otp_token: str) -> dict:
	"""Live status for a job card, after the customer proves the mobile is theirs."""
	session = verify_session_token(otp_token, "Service Tracking")
	if not session:
		frappe.throw(_("Verify the OTP sent to your mobile first."), frappe.PermissionError)

	mobile = normalize_mobile(mobile_no)
	if normalize_mobile(session["mobile"]) != mobile:
		frappe.throw(_("This OTP belongs to a different number."), frappe.PermissionError)

	reference = (reference or "").strip()
	name = frappe.db.get_value(
		"Service Job Card",
		{"name": reference, "customer_mobile": mobile, "docstatus": ["<", 2]},
		"name",
	) or frappe.db.get_value(
		"Service Job Card",
		{"imei_1": reference, "customer_mobile": mobile, "docstatus": ["<", 2]},
		"name",
		order_by="creation desc",
	)
	if not name:
		frappe.throw(_("No repair found for that reference and mobile number."))

	job = frappe.get_doc("Service Job Card", name)
	return {
		"job_card": job.name,
		"status": job.status,
		"branch": job.branch,
		"device": f"{job.brand or ''} {job.device_model or ''}".strip(),
		"imei": job.imei_1,
		"received_on": str(job.received_on or ""),
		"promised_on": str(job.estimated_delivery_date or ""),
		"delivered_on": str(job.delivered_on or ""),
		"amount": flt(job.customer_payable),
		"paid": flt(job.advance_amount),
		"outstanding": flt(job.outstanding_amount),
		"payment_status": job.payment_status,
		"estimate": job.service_estimate,
		"timeline": _timeline(job),
		"pay_url": payment_link(job) if flt(job.outstanding_amount) > 0 else None,
	}


def _timeline(job) -> list[dict]:
	reached = {row.to_status for row in job.get("status_log") or []} | {job.status}
	timeline, passed = [], True
	for label, statuses in TIMELINE_STAGES:
		done = bool(reached & set(statuses))
		current = job.status in statuses
		timeline.append({"label": label, "done": done, "current": current})
		if current:
			passed = False
		elif not passed:
			timeline[-1]["done"] = False
	return timeline


def payment_link(job) -> str:
	from a3_retail.utils.tokens import portal_url

	return portal_url("Service Job Card", job.name, "pay", "payment")


# ---------------------------------------------------------------------------
# Complaints — /support (scope 13.1)
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def submit_complaint(subject: str, description: str, mobile_no: str, otp_token: str,
                     branch: str | None = None, category: str | None = None,
                     job_card: str | None = None, email: str | None = None) -> dict:
	"""Raise an Issue from the public complaint form."""
	session = verify_session_token(otp_token, "Complaint")
	if not session:
		frappe.throw(_("Verify the OTP sent to your mobile first."), frappe.PermissionError)

	mobile = normalize_mobile(mobile_no)
	if normalize_mobile(session["mobile"]) != mobile:
		frappe.throw(_("This OTP belongs to a different number."), frappe.PermissionError)

	if not (subject or "").strip():
		frappe.throw(_("Tell us briefly what went wrong."))

	customer = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")

	issue = frappe.new_doc("Issue")
	issue.subject = subject.strip()[:140]
	issue.description = description
	issue.raised_by = email or None
	issue.customer = customer
	issue.status = "Open"
	if issue.meta.has_field("a3_branch"):
		issue.a3_branch = branch
	if issue.meta.has_field("a3_complaint_category"):
		issue.a3_complaint_category = category
	if issue.meta.has_field("a3_job_card"):
		issue.a3_job_card = job_card
	if issue.meta.has_field("a3_channel"):
		issue.a3_channel = "Website"
	issue.flags.ignore_permissions = True
	issue.insert(ignore_permissions=True)

	commit_if_not_testing()
	return {"issue": issue.name, "status": issue.status}


# ---------------------------------------------------------------------------
# Feedback — /feedback/<token> (scope 13.1)
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def submit_feedback(token: str, rating: float, comments: str | None = None,
                    would_recommend: int | None = None, nps: int | None = None) -> dict:
	"""Record a Customer Feedback against the job card the link points at."""
	from a3_retail.utils.tokens import verify as verify_token

	job_card = verify_token(token, "Service Job Card", "feedback")
	if not job_card:
		frappe.throw(_("This feedback link is not valid."), frappe.PermissionError)

	job = frappe.get_doc("Service Job Card", job_card)
	if job.customer_feedback and frappe.db.exists("Customer Feedback", job.customer_feedback):
		return {"feedback": job.customer_feedback, "already_submitted": True}

	stars = flt(rating)
	doc = frappe.new_doc("Customer Feedback")
	doc.feedback_date = nowdate()
	doc.customer = job.customer
	doc.mobile_no = job.customer_mobile
	doc.branch = job.branch
	doc.channel = "Web Portal"
	doc.reference_type = "Service Job Card"
	doc.reference_name = job.name
	doc.attended_employee = job.assigned_technician
	# Frappe stores a Rating as 0–1.
	doc.overall_rating = stars / 5 if stars > 1 else stars
	doc.comments = comments
	if nps is not None:
		doc.nps_score = cint(nps)
	if would_recommend is not None:
		doc.would_recommend = cint(would_recommend)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	job.db_set("customer_feedback", doc.name, update_modified=False)
	job.db_set("feedback_rating", doc.overall_rating, update_modified=False)
	commit_if_not_testing()

	return {"feedback": doc.name, "sentiment": doc.sentiment}


# ---------------------------------------------------------------------------
# Public listings — /offers and /stores (scope 13.1)
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def active_offers(branch: str | None = None) -> list[dict]:
	filters = {"status": "Active", "docstatus": 1}
	offers = frappe.get_all(
		"Seasonal Offer Campaign",
		filters=filters,
		fields=["name", "campaign_name", "offer_type", "valid_from", "valid_upto", "description",
		        "banner_image", "discount_percentage", "discount_amount", "coupon_code"],
		order_by="valid_upto asc",
	)

	if branch:
		offers = [
			offer for offer in offers
			if not frappe.db.exists("Offer Branch", {"parent": offer.name})
			or frappe.db.exists("Offer Branch", {"parent": offer.name, "branch": branch})
		]
	return offers


@frappe.whitelist(allow_guest=True)
def store_locator() -> list[dict]:
	from a3_retail.print_helpers import a3_branch_profile

	stores = []
	for row in frappe.get_all(
		"Branch Profile",
		filters={"is_active": 1},
		fields=["branch", "branch_type", "latitude", "longitude", "working_hours_from",
		        "working_hours_to", "weekly_off"],
	):
		profile = a3_branch_profile(row.branch)
		stores.append(
			{
				"branch": row.branch,
				"type": row.branch_type,
				"address": profile.get("address"),
				"phone": profile.get("phone"),
				"email": profile.get("email"),
				"latitude": row.latitude,
				"longitude": row.longitude,
				"opens": str(row.working_hours_from or ""),
				"closes": str(row.working_hours_to or ""),
				"weekly_off": row.weekly_off,
			}
		)
	return stores
