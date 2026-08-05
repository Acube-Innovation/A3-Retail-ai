# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Message queue and provider hand-off (scope 9.2, 9.7).

Every send writes a WhatsApp Message Log first, then delivers. Writing the log
before the network call is deliberate: a provider timeout leaves an auditable
row to retry rather than a message that may or may not have gone.
"""

import frappe
from frappe.utils import cint, now_datetime

from a3_retail.communication.providers import get_provider


def queue_message(template, to_number: str, params: dict, stream: str = "Service",
                  reference_doc=None, rule: str | None = None, customer: str | None = None,
                  blocked: str | None = None) -> bool:
	"""Log the intent, then deliver (or park it when compliance says no)."""
	log = frappe.new_doc("WhatsApp Message Log")
	log.to_number = normalize_number(to_number)
	log.stream = stream
	log.template = template.name if template else None
	log.communication_rule = rule
	log.customer = customer
	log.status = blocked or "Queued"
	log.message_body = render_body(template, params)
	log.payload = frappe.as_json({"template": template.template_key if template else None,
	                              "params": params})

	if reference_doc is not None:
		log.reference_doctype = reference_doc.doctype
		log.reference_name = reference_doc.name
		log.branch = reference_doc.get("branch")

	log.sender_profile = resolve_sender(stream, log.branch)
	log.flags.ignore_permissions = True
	log.insert(ignore_permissions=True)

	if blocked:
		# Parked on purpose — opt-out, quiet hours or the daily cap.
		return False

	deliver(log)
	return True


def render_body(template, params: dict) -> str:
	"""Substitute {{1}}, {{2}}… so the log shows what the customer will read."""
	if not template:
		return frappe.as_json(params)

	body = template.body_text or ""
	for index, value in (params or {}).items():
		body = body.replace("{{" + str(index) + "}}", str(value))
	return body


def resolve_sender(stream: str, branch: str | None = None) -> str | None:
	"""A branch-specific profile wins; otherwise the stream's default number."""
	if branch:
		specific = frappe.db.get_value(
			"WhatsApp Sender Profile", {"stream": stream, "branch": branch, "is_active": 1}, "name"
		)
		if specific:
			return specific

	# `["in", ["", None]]` does not match SQL NULL; "is not set" compiles to
	# ifnull(branch, '') = '' which does.
	return frappe.db.get_value(
		"WhatsApp Sender Profile",
		{"stream": stream, "branch": ["is", "not set"], "is_active": 1},
		"name",
	)


def normalize_number(number: str) -> str:
	"""E.164 without the plus, which is what the Cloud API expects."""
	digits = "".join(ch for ch in str(number or "") if ch.isdigit())
	if len(digits) == 10:
		code = frappe.db.get_single_value("WhatsApp Settings", "default_country_code") or "91"
		digits = f"{code}{digits}"
	return digits


def deliver(log):
	"""Send now, or hand to the background queue when configured."""
	from a3_retail.communication.engine import is_enabled

	if not is_enabled():
		# Nothing configured yet: the intent stays Queued and auditable.
		return

	if frappe.db.get_single_value("WhatsApp Settings", "queue_messages") and not frappe.flags.in_test:
		frappe.enqueue(
			"a3_retail.communication.dispatch.send_now",
			queue="short",
			log_name=log.name,
			enqueue_after_commit=True,
		)
		return

	send_now(log.name)


def send_now(log_name: str):
	"""Actually call the provider and record what happened."""
	log = frappe.get_doc("WhatsApp Message Log", log_name)
	provider = get_provider()

	try:
		result = provider.send(log)
	except Exception as exc:
		log.db_set("status", "Failed", update_modified=False)
		log.db_set("error_message", str(exc)[:500], update_modified=False)
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: WhatsApp send {log_name}")
		return

	if result.get("ok"):
		log.db_set("status", "Sent", update_modified=False)
		log.db_set("sent_on", now_datetime(), update_modified=False)
		log.db_set("provider_message_id", result.get("message_id"), update_modified=False)
	else:
		log.db_set("status", "Failed", update_modified=False)
		log.db_set("error_code", result.get("error_code"), update_modified=False)
		log.db_set("error_message", (result.get("error") or "")[:500], update_modified=False)


# ---------------------------------------------------------------------------
# Email — the mirror channel (scope 9.8)
# ---------------------------------------------------------------------------
def send_email_for_rule(rule, doc, recipients: list[str]):
	"""Queue the email twin of a WhatsApp rule through Frappe's Email Queue."""
	if not rule.email_template or not recipients:
		return False

	template = frappe.get_cached_doc("Email Template", rule.email_template)
	context = {"doc": doc}

	frappe.sendmail(
		recipients=recipients,
		subject=frappe.render_template(template.subject or rule.rule_name, context),
		message=frappe.render_template(template.response or "", context),
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		now=frappe.flags.in_test,
	)
	return True
