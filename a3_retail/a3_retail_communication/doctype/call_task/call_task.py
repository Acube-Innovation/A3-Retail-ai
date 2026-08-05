# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Call Task (scope 8.4) — one row per person to ring.

The disposition drives what happens next: schedule a call-back, fire a WhatsApp
follow-up, or flag the customer Do Not Call. Attempts are capped at three so a
campaign cannot harass a number that never answers.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from a3_retail.api.customer import normalize_mobile

MAX_ATTEMPTS = 3
CONTACTED_STATUSES = ("Connected", "No Answer", "Busy", "Switched Off", "Wrong Number",
                      "Call Back Later", "Do Not Call")


class CallTask(Document):
	def validate(self):
		self.mobile_no = normalize_mobile(self.mobile_no)
		self.pull_customer()
		self.validate_dnc()
		self.validate_attempts()
		self.apply_disposition()

	def on_update(self):
		self.run_disposition_side_effects()

	# ------------------------------------------------------------------ checks
	def pull_customer(self):
		if not self.customer and self.mobile_no:
			self.customer = frappe.db.get_value("Customer", {"a3_mobile_no": self.mobile_no}, "name")
		if self.customer and not self.contact_name:
			self.contact_name = frappe.db.get_value("Customer", self.customer, "customer_name")

	def validate_dnc(self):
		"""A customer on the Do Not Call list is never queued (scope 8.6)."""
		if not self.customer or self.call_status != "Not Called":
			return
		if frappe.db.get_value("Customer", self.customer, "a3_dnc"):
			frappe.throw(
				_("{0} is on the Do Not Call list.").format(self.contact_name or self.customer),
				title=_("Do Not Call"),
			)

	def validate_attempts(self):
		if cint(self.attempt_no) > MAX_ATTEMPTS:
			frappe.throw(
				_("A number may be attempted at most {0} times.").format(MAX_ATTEMPTS)
			)

	def apply_disposition(self):
		"""Record when the call happened and what the disposition implies."""
		if self.call_status in CONTACTED_STATUSES and not self.call_datetime:
			self.call_datetime = now_datetime()

		if not self.disposition:
			return

		disposition = frappe.get_cached_doc("Call Disposition", self.disposition)

		if disposition.requires_next_call and not self.next_call_date:
			self.next_call_date = add_days(nowdate(), cint(disposition.default_next_call_days) or 1)

		if disposition.category == "Positive" and self.outcome == "Pending":
			self.outcome = "Interested - Follow-up"
		elif disposition.category == "Negative" and self.outcome == "Pending":
			self.outcome = "Not Interested"
		elif disposition.category == "Invalid" and self.outcome == "Pending":
			self.outcome = "Invalid Contact"

	# ------------------------------------------------------------ side effects
	def run_disposition_side_effects(self):
		if not self.disposition:
			return

		disposition = frappe.get_cached_doc("Call Disposition", self.disposition)

		if disposition.is_dnc and self.customer:
			frappe.db.set_value("Customer", self.customer, "a3_dnc", 1, update_modified=False)

		if disposition.triggers_whatsapp and not self.whatsapp_sent:
			self._send_whatsapp(disposition)

	def _send_whatsapp(self, disposition):
		from a3_retail.communication.engine import notify

		sent = notify(
			disposition.whatsapp_template or "seasonal_offer_blast",
			doc=self,
			to_number=self.mobile_no,
			params={"1": self.contact_name},
			stream="Marketing",
		)
		if sent:
			self.db_set("whatsapp_sent", 1, update_modified=False)


# ---------------------------------------------------------------------------
# Console API
# ---------------------------------------------------------------------------
@frappe.whitelist()
def my_queue(telecaller: str | None = None, limit: int = 50) -> dict:
	"""Today's queue for the logged-in telecaller (scope 8.4 console)."""
	from a3_retail.api import require_permission

	require_permission("Call Task", "read")

	telecaller = telecaller or frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
	)
	if not telecaller:
		return {"telecaller": None, "tasks": [], "stats": {}}

	tasks = frappe.get_all(
		"Call Task",
		filters={
			"assigned_to": telecaller,
			"call_status": ["in", ["Not Called", "Call Back Later", "No Answer", "Busy"]],
		},
		fields=["name", "campaign", "customer", "contact_name", "mobile_no", "priority",
		        "context", "scheduled_date", "attempt_no", "call_status"],
		order_by="priority desc, scheduled_date asc",
		limit_page_length=cint(limit),
	)

	today = nowdate()
	all_today = frappe.get_all(
		"Call Task",
		filters={"assigned_to": telecaller, "scheduled_date": today},
		fields=["call_status", "outcome", "duration_seconds"],
	)

	return {
		"telecaller": telecaller,
		"tasks": tasks,
		"stats": {
			"assigned": len(all_today),
			"called": sum(1 for r in all_today if r.call_status != "Not Called"),
			"connected": sum(1 for r in all_today if r.call_status == "Connected"),
			"converted": sum(1 for r in all_today if r.outcome == "Converted"),
			"talk_time": sum(cint(r.duration_seconds) for r in all_today),
		},
	}


@frappe.whitelist()
def customer_context(call_task: str) -> dict:
	"""Everything the telecaller should see before dialling (scope 8.4)."""
	from a3_retail.api import require_permission

	require_permission("Call Task", "read")

	task = frappe.get_doc("Call Task", call_task)
	context = {
		"call_task": task.name,
		"contact_name": task.contact_name,
		"mobile_no": task.mobile_no,
		"context": task.context,
		"attempt_no": task.attempt_no,
		"devices": [],
		"job_cards": [],
		"outstanding": 0,
		"warranty": None,
	}

	if not task.customer:
		return context

	context["devices"] = frappe.get_all(
		"Serial No",
		filters={"customer": task.customer},
		fields=["name", "item_code", "a3_warranty_state", "a3_brand_warranty_expiry"],
		limit_page_length=5,
	)
	context["job_cards"] = frappe.get_all(
		"Service Job Card",
		filters={"customer": task.customer, "docstatus": 1},
		fields=["name", "status", "device_model", "received_on"],
		order_by="received_on desc",
		limit_page_length=5,
	)
	context["outstanding"] = flt(
		frappe.db.sql(
			"""select sum(outstanding_amount) from `tabSales Invoice`
			   where customer = %s and docstatus = 1""",
			task.customer,
		)[0][0]
	)

	registration = frappe.db.get_value(
		"Warranty Registration",
		{"customer": task.customer, "docstatus": 1},
		["name", "ew_plan", "ew_expiry_date", "status"],
		as_dict=True,
		order_by="creation desc",
	)
	context["warranty"] = registration
	return context


@frappe.whitelist()
def record_call(call_task: str, call_status: str, disposition: str | None = None,
                notes: str | None = None, duration_seconds: int = 0,
                next_call_date: str | None = None) -> dict:
	"""Save the outcome of a call and set up the next one."""
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Call Task", call_task)
	require_permission("Call Task", "write", doc)

	doc.call_status = call_status
	doc.disposition = disposition
	doc.notes = notes
	doc.duration_seconds = cint(duration_seconds)
	doc.call_datetime = now_datetime()
	if next_call_date:
		doc.next_call_date = getdate(next_call_date)

	# A retry consumes an attempt; the cap is enforced in validate.
	if call_status in ("No Answer", "Busy", "Switched Off"):
		doc.attempt_no = min(cint(doc.attempt_no) + 1, MAX_ATTEMPTS)

	doc.save()
	return {"call_task": doc.name, "call_status": doc.call_status, "outcome": doc.outcome,
	        "next_call_date": str(doc.next_call_date or "")}
