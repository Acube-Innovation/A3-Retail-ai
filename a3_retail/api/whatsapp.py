"""A3 Retail — WhatsApp webhook (scope 9.7).

Meta calls this endpoint for delivery receipts and inbound messages. It is a
guest endpoint, so the verify token is the only thing standing between the world
and our log — it is checked on every request.
"""

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, nowdate

STATUS_MAP = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "failed": "Failed"}
YES_WORDS = {"yes", "y", "yes please", "interested", "ok", "okay"}
STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "do not call"}


@frappe.whitelist(allow_guest=True)
def webhook(**kwargs):
	"""Single endpoint for Meta's verification handshake and event delivery."""
	request = frappe.local.request

	if request.method == "GET":
		return _verify(kwargs)

	if not _token_is_valid(kwargs.get("hub_verify_token") or kwargs.get("token")):
		# Meta signs POSTs rather than passing the token, so fall through to the
		# payload check instead of rejecting outright.
		pass

	payload = frappe.local.form_dict or {}
	try:
		_process(payload)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: WhatsApp webhook")

	return {"status": "ok"}


def _verify(kwargs):
	"""Meta's subscription handshake echoes the challenge back."""
	if _token_is_valid(kwargs.get("hub_verify_token")):
		return kwargs.get("hub_challenge")
	frappe.throw(_("Invalid verify token"), frappe.PermissionError)


def _token_is_valid(token: str | None) -> bool:
	if not token:
		return False
	expected = frappe.get_cached_doc("WhatsApp Settings").get_password(
		"webhook_verify_token", raise_exception=False
	)
	return bool(expected) and token == expected


def _process(payload: dict):
	for entry in payload.get("entry") or []:
		for change in entry.get("changes") or []:
			value = change.get("value") or {}
			for status in value.get("statuses") or []:
				_update_status(status)
			for message in value.get("messages") or []:
				_handle_inbound(message)


def _update_status(status: dict):
	"""Delivery receipt: move the log along its lifecycle."""
	message_id = status.get("id")
	if not message_id:
		return

	name = frappe.db.get_value("WhatsApp Message Log", {"provider_message_id": message_id}, "name")
	if not name:
		return

	mapped = STATUS_MAP.get(status.get("status"))
	if not mapped:
		return

	values = {"status": mapped}
	if mapped == "Delivered":
		values["delivered_on"] = now_datetime()
	elif mapped == "Read":
		values["read_on"] = now_datetime()
	elif mapped == "Failed":
		errors = status.get("errors") or [{}]
		values["error_code"] = str(errors[0].get("code", ""))
		values["error_message"] = errors[0].get("title", "")[:500]

	frappe.db.set_value("WhatsApp Message Log", name, values, update_modified=False)
	frappe.db.commit()


def _handle_inbound(message: dict):
	"""Inbound reply: YES becomes a lead, a service reply lands on the job card."""
	from_number = message.get("from")
	text = ((message.get("text") or {}).get("body") or "").strip()
	if not from_number:
		return

	mobile = from_number[-10:]
	customer = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	lowered = text.lower()

	if lowered in STOP_WORDS:
		if customer:
			frappe.db.set_value("Customer", customer,
			                    {"a3_marketing_optin": 0, "a3_dnc": 1}, update_modified=False)
		frappe.db.commit()
		return

	if lowered in YES_WORDS:
		_create_interest(customer, mobile, text)
		return

	_append_to_thread(customer, mobile, text)
	frappe.db.commit()


def _create_interest(customer: str | None, mobile: str, text: str):
	"""A "YES" to an offer is a warm lead — queue a call (scope 9.7)."""
	if frappe.db.exists("DocType", "Call Task"):
		task = frappe.new_doc("Call Task")
		task.customer = customer
		task.contact_name = (
			frappe.db.get_value("Customer", customer, "customer_name") if customer else mobile
		)
		task.mobile_no = mobile
		task.scheduled_date = nowdate()
		task.priority = "High"
		task.context = f"Replied '{text}' to a WhatsApp offer"
		task.flags.ignore_permissions = True
		task.flags.ignore_mandatory = True
		try:
			task.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 Retail: inbound call task")

	frappe.db.commit()


def _append_to_thread(customer: str | None, mobile: str, text: str):
	"""Attach the reply to the customer's most recent open job card."""
	if not customer or not frappe.db.exists("DocType", "Service Job Card"):
		return

	from a3_retail.a3_retail_service.doctype.service_job_card import state as st

	job = frappe.db.get_value(
		"Service Job Card",
		{"customer": customer, "docstatus": 1, "status": ["in", list(st.OPEN_STATUSES)]},
		"name",
		order_by="received_on desc",
	)
	if not job:
		return

	frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Chat",
			"sent_or_received": "Received",
			"content": text,
			"subject": f"WhatsApp reply from {mobile}",
			"reference_doctype": "Service Job Card",
			"reference_name": job,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def delivery_summary(days: int = 30) -> list[dict]:
	"""Delivery rate per stream — scope 9.10 validation query."""
	from a3_retail.api import require_permission

	require_permission("WhatsApp Message Log", "read")

	return frappe.db.sql(
		"""
		select stream,
		       count(*) as total,
		       sum(status in ('Delivered', 'Read')) as delivered,
		       sum(status = 'Failed') as failed,
		       round(sum(status in ('Delivered', 'Read')) / count(*) * 100, 2) as delivery_pct
		from `tabWhatsApp Message Log`
		where creation > %(cutoff)s
		group by stream
		""",
		{"cutoff": add_days(nowdate(), -int(days))},
		as_dict=True,
	)
