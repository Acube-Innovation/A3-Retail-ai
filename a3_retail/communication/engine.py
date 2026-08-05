# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Communication rule engine (scope 9.6).

A single dispatcher is registered on `doc_events["*"]`, so any doctype can drive
messaging without its controller knowing anything about WhatsApp. Rules decide
what fires; templates decide what is said; sender profiles decide which number
it comes from.

Three compliance rules are enforced before anything leaves (scope 9.5):
Marketing templates need `Customer.a3_marketing_optin`, they respect quiet
hours, and they honour a daily cap per customer. Utility templates — the
transaction-triggered ones — are always allowed.
"""

import frappe
from frappe.utils import (
	add_to_date,
	cint,
	flt,
	get_datetime,
	get_time,
	getdate,
	now_datetime,
	nowdate,
)

from a3_retail.utils import commit_if_not_testing

MARKETING = "Marketing"

TRIGGER_INSERT = "On Insert"
TRIGGER_SUBMIT = "On Submit"
TRIGGER_UPDATE = "On Update"
TRIGGER_STATUS = "On Status Change"
TRIGGER_CANCEL = "On Cancel"
TRIGGER_BEFORE_DATE = "Days Before Date Field"
TRIGGER_AFTER_DATE = "Days After Date Field"

EVENT_TRIGGERS = {
	"after_insert": TRIGGER_INSERT,
	"on_submit": TRIGGER_SUBMIT,
	"on_update": TRIGGER_UPDATE,
	"on_update_after_submit": TRIGGER_UPDATE,
	"on_cancel": TRIGGER_CANCEL,
}

# Never react to our own bookkeeping.
IGNORED_DOCTYPES = {
	"WhatsApp Message Log", "Communication Rule", "WhatsApp Template", "Error Log",
	"Version", "Activity Log", "Scheduled Job Log", "Access Log", "Route History",
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
	if not frappe.db.exists("DocType", "WhatsApp Settings"):
		return False
	return bool(frappe.db.get_single_value("WhatsApp Settings", "enabled"))


def rules_active() -> bool:
	"""Rules stay inert until explicitly switched on, so a demo cannot spam."""
	return bool(frappe.db.get_single_value("A3 Retail Settings", "activate_communication_rules"))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def handle(doc, method=None):
	"""Registered on every doctype; returns immediately when nothing matches."""
	trigger = EVENT_TRIGGERS.get(method)
	if not trigger or doc.doctype in IGNORED_DOCTYPES:
		return
	if not rules_active():
		return

	for rule in matching_rules(doc.doctype, trigger):
		try:
			evaluate_and_send(rule, doc, trigger)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: rule {rule.name} on {doc.name}")

	# A status-change rule is driven by the same update events.
	if trigger == TRIGGER_UPDATE:
		for rule in matching_rules(doc.doctype, TRIGGER_STATUS):
			try:
				evaluate_and_send(rule, doc, TRIGGER_STATUS)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"A3 Retail: rule {rule.name} on {doc.name}")


def matching_rules(doctype: str, trigger: str) -> list:
	"""Active rules for a doctype/trigger pair, highest priority first."""
	names = frappe.get_all(
		"Communication Rule",
		filters={"reference_doctype": doctype, "trigger_type": trigger, "is_active": 1},
		pluck="name",
		order_by="priority desc",
	)
	return [frappe.get_cached_doc("Communication Rule", name) for name in names]


def evaluate_and_send(rule, doc, trigger: str):
	if not rule_applies(rule, doc, trigger):
		return
	if already_sent(rule, doc):
		return
	send_for_rule(rule, doc)


def rule_applies(rule, doc, trigger: str) -> bool:
	if trigger == TRIGGER_STATUS and not status_changed(rule, doc):
		return False
	return evaluate_condition(rule, doc)


def status_changed(rule, doc) -> bool:
	"""Only fire when the watched field actually moved to the wanted value."""
	field = rule.watch_field or "status"
	current = doc.get(field)

	if rule.to_value and current != rule.to_value:
		return False

	before = doc.get_doc_before_save()
	previous = before.get(field) if before else None

	if rule.from_value and previous != rule.from_value:
		return False
	return previous != current


def evaluate_condition(rule, doc) -> bool:
	if not rule.condition:
		return True
	try:
		return bool(frappe.safe_eval(rule.condition, None, {"doc": doc}))
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: condition on rule {rule.name}")
		return False


def already_sent(rule, doc) -> bool:
	"""`max_sends_per_document` is what stops a status flapping into spam."""
	cap = cint(rule.max_sends_per_document)
	if cap <= 0:
		return False

	sent = frappe.db.count(
		"WhatsApp Message Log",
		{
			"communication_rule": rule.name,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"status": ["not in", ["Failed", "Blocked (Opt-out)"]],
		},
	)
	return sent >= cap


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def send_for_rule(rule, doc) -> bool:
	template = (
		frappe.get_cached_doc("WhatsApp Template", rule.whatsapp_template)
		if rule.whatsapp_template
		else None
	)
	recipients = resolve_recipients(rule, doc)
	if not recipients:
		return False

	sent = False
	for number in recipients:
		params = resolve_parameters(template, doc) if template else {}
		result = send_template(
			template_key=template.template_key if template else None,
			to_number=number,
			params=params,
			stream=template.stream if template else "Service",
			reference_doc=doc,
			rule=rule.name,
		)
		sent = sent or result

	return sent


def resolve_recipients(rule, doc) -> list[str]:
	"""Turn the rule's recipient setting into phone numbers."""
	numbers: list = []

	if rule.recipient_type == "Customer":
		numbers.append(customer_number(doc))
	elif rule.recipient_type == "Field on Document":
		numbers.append(doc.get(rule.recipient_field))
	elif rule.recipient_type == "Static List":
		numbers.extend((rule.static_recipients or "").split(","))
	elif rule.recipient_type == "Role" and rule.recipient_role:
		numbers.extend(role_numbers(rule.recipient_role))
	elif rule.recipient_type == "Employee Field":
		employee = doc.get(rule.recipient_field)
		if employee:
			numbers.append(frappe.db.get_value("Employee", employee, "cell_number"))

	if rule.cc_branch_manager and doc.get("branch"):
		numbers.append(branch_manager_number(doc.get("branch")))

	return [str(n).strip() for n in numbers if n and str(n).strip()]


def customer_number(doc) -> str | None:
	for field in ("customer_mobile", "mobile_no", "contact_mobile", "consignee_mobile"):
		if doc.get(field):
			return doc.get(field)

	customer = doc.get("customer")
	if customer:
		return frappe.db.get_value("Customer", customer, "a3_whatsapp_no") or frappe.db.get_value(
			"Customer", customer, "a3_mobile_no"
		)
	return None


def role_numbers(role: str) -> list[str]:
	users = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not users:
		return []
	return frappe.get_all(
		"Employee", filters={"user_id": ["in", users], "status": "Active"}, pluck="cell_number"
	)


def branch_manager_number(branch: str) -> str | None:
	manager = frappe.db.get_value("Branch Profile", {"branch": branch}, "branch_manager")
	return frappe.db.get_value("Employee", manager, "cell_number") if manager else None


def resolve_parameters(template, doc) -> dict:
	"""Fill {{1}}, {{2}}… from fields, Jinja or static values (scope 9.5)."""
	params: dict = {}

	for row in template.get("parameters") or []:
		value = ""
		if row.source == "Field" and row.fieldname:
			value = doc.get(row.fieldname)
		elif row.source == "Jinja" and row.jinja_expression:
			try:
				value = frappe.render_template(row.jinja_expression, {"doc": doc})
			except Exception:
				value = ""
		elif row.source == "Static":
			value = row.static_value

		params[str(row.param_index)] = format_param(value, row.format)

	return params


def format_param(value, fmt: str | None) -> str:
	if value in (None, ""):
		return ""
	if fmt == "Currency":
		return frappe.format_value(flt(value), {"fieldtype": "Currency"})
	if fmt == "Date":
		return frappe.format_value(getdate(value), {"fieldtype": "Date"})
	if fmt == "Datetime":
		return frappe.format_value(get_datetime(value), {"fieldtype": "Datetime"})
	return str(value)


def send_template(template_key: str | None, to_number: str | None, params: dict,
                  stream: str = "Service", reference_doc=None, rule: str | None = None) -> bool:
	"""Compliance gate, then hand off to the provider layer."""
	from a3_retail.communication.dispatch import queue_message

	if not to_number:
		return False

	template = None
	if template_key and frappe.db.exists("WhatsApp Template", template_key):
		template = frappe.get_cached_doc("WhatsApp Template", template_key)

	customer = _customer_for(reference_doc, to_number)
	blocked = compliance_block(template, customer)

	return queue_message(
		template=template,
		to_number=to_number,
		params=params,
		stream=(template.stream if template else stream),
		reference_doc=reference_doc,
		rule=rule,
		customer=customer,
		blocked=blocked,
	)


def _customer_for(doc, to_number: str) -> str | None:
	if doc is not None and doc.get("customer"):
		return doc.get("customer")
	return frappe.db.get_value("Customer", {"a3_mobile_no": to_number}, "name")


def compliance_block(template, customer: str | None) -> str | None:
	"""Return a blocking status, or None when the message may go.

	Utility templates are transaction-triggered and always allowed; only
	Marketing is gated (scope 9.5 compliance note).
	"""
	if not template or template.category != MARKETING:
		return None

	settings = frappe.get_cached_doc("WhatsApp Settings")

	if settings.respect_marketing_optin and customer:
		if not frappe.db.get_value("Customer", customer, "a3_marketing_optin"):
			return "Blocked (Opt-out)"

	if in_quiet_hours(settings):
		return "Held (Quiet Hours)"

	cap = cint(settings.daily_marketing_cap_per_customer)
	if cap and customer and marketing_sent_today(customer) >= cap:
		return "Blocked (Opt-out)"

	return None


def in_quiet_hours(settings) -> bool:
	start, end = settings.quiet_hours_from, settings.quiet_hours_to
	if not start or not end:
		return False

	now = now_datetime().time()
	start, end = get_time(start), get_time(end)

	# Quiet hours normally wrap past midnight (21:00 -> 08:00).
	if start <= end:
		return start <= now <= end
	return now >= start or now <= end


def marketing_sent_today(customer: str) -> int:
	return frappe.db.sql(
		"""
		select count(l.name) from `tabWhatsApp Message Log` l
		join `tabWhatsApp Template` t on t.name = l.template
		where l.customer = %(customer)s and t.category = 'Marketing'
		  and date(l.creation) = %(today)s
		  and l.status not in ('Failed', 'Blocked (Opt-out)')
		""",
		{"customer": customer, "today": nowdate()},
	)[0][0]


# ---------------------------------------------------------------------------
# Convenience wrappers used by the rest of the app
# ---------------------------------------------------------------------------
def notify(template_key: str, doc=None, to_number: str | None = None, params: dict | None = None,
           stream: str = "Service") -> bool:
	"""Fire a template at a customer. Safe to call when messaging is off."""
	if not to_number and doc is not None:
		to_number = customer_number(doc)
	return send_template(template_key, to_number, params or {}, stream, reference_doc=doc)


def send_otp(mobile_no: str, otp: str, purpose: str = "General") -> bool:
	return send_template("portal_otp", mobile_no, {"1": otp, "2": purpose}, stream="Service")


# ---------------------------------------------------------------------------
# Scheduler — date-based rules (scope 9.6)
# ---------------------------------------------------------------------------
def run_date_based_rules():
	"""Daily — fire "N days before/after <date field>" rules."""
	if not rules_active():
		return 0

	rules = frappe.get_all(
		"Communication Rule",
		filters={"is_active": 1, "trigger_type": ["in", [TRIGGER_BEFORE_DATE, TRIGGER_AFTER_DATE]]},
		pluck="name",
	)

	sent = 0
	for name in rules:
		rule = frappe.get_cached_doc("Communication Rule", name)
		if not rule.date_field or not frappe.db.exists("DocType", rule.reference_doctype):
			continue

		offset = cint(rule.days_offset)
		target = add_to_date(
			nowdate(), days=offset if rule.trigger_type == TRIGGER_BEFORE_DATE else -offset
		)

		for doc_name in frappe.get_all(
			rule.reference_doctype,
			filters={rule.date_field: getdate(target)},
			pluck="name",
			limit_page_length=500,
		):
			doc = frappe.get_doc(rule.reference_doctype, doc_name)
			if not evaluate_condition(rule, doc) or already_sent(rule, doc):
				continue
			if send_for_rule(rule, doc):
				sent += 1

	commit_if_not_testing()
	return sent


def retry_failed_messages():
	"""Hourly — retry failures up to the configured attempt count."""
	if not is_enabled():
		return 0

	from a3_retail.communication.dispatch import deliver

	settings = frappe.get_cached_doc("WhatsApp Settings")
	attempts = cint(settings.retry_attempts) or 3

	rows = frappe.get_all(
		"WhatsApp Message Log",
		filters={"status": "Failed", "retry_count": ["<", attempts]},
		pluck="name",
		limit_page_length=200,
	)

	for name in rows:
		log = frappe.get_doc("WhatsApp Message Log", name)
		log.db_set("retry_count", cint(log.retry_count) + 1, update_modified=False)
		deliver(log)

	commit_if_not_testing()
	return len(rows)


def release_held_messages():
	"""Hourly — send messages parked for quiet hours once the window closes."""
	if not is_enabled():
		return 0

	from a3_retail.communication.dispatch import deliver

	settings = frappe.get_cached_doc("WhatsApp Settings")
	if in_quiet_hours(settings):
		return 0

	rows = frappe.get_all(
		"WhatsApp Message Log", filters={"status": "Held (Quiet Hours)"}, pluck="name",
		limit_page_length=200,
	)

	for name in rows:
		log = frappe.get_doc("WhatsApp Message Log", name)
		log.db_set("status", "Queued", update_modified=False)
		deliver(log)

	commit_if_not_testing()
	return len(rows)
