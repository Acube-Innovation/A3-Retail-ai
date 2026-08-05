# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Visit Log — footfall (scope 8.1).

Every walk-in is logged in under ten seconds. The value is in the outcome: a
lost visit becomes a Call Task, an interested one becomes a Lead, and a
converted one back-links to the invoice or job card so conversion rate is a
fact rather than an estimate.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from a3_retail.api.customer import normalize_mobile
from a3_retail.utils import publish_dashboard_update
from a3_retail.utils.branch import A3BranchMixin
from a3_retail.utils.naming import set_branch_code

CONVERTED_PREFIX = "Converted"
LOST_PREFIX = "Lost"
LEAD_OUTCOME = "Lead Created (Follow-up)"


class BranchVisitLog(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.visit_datetime:
			self.visit_datetime = now_datetime()

	def validate(self):
		self.mobile_no = normalize_mobile(self.mobile_no)
		self.match_customer()
		self.pull_reference_value()

	def on_update(self):
		self.create_followups()
		publish_dashboard_update(self.branch_code, {"branch": self.branch, "visit": self.name})

	# ------------------------------------------------------------------ detail
	def match_customer(self):
		"""Recognise a returning customer from the mobile number alone."""
		if not self.mobile_no:
			return

		existing = frappe.db.get_value("Customer", {"a3_mobile_no": self.mobile_no}, "name")
		self.customer = existing
		self.is_existing_customer = 1 if existing else 0

		if existing and self.visitor_type == "New Walk-in":
			self.visitor_type = "Repeat Customer"

	def pull_reference_value(self):
		"""A converted visit carries the value of what it converted into."""
		if not self.reference_type or not self.reference_name:
			self.sale_value = 0
			return

		field = {
			"Sales Invoice": "grand_total",
			"POS Invoice": "grand_total",
			"Sales Order": "grand_total",
			"Quotation": "grand_total",
			"Service Job Card": "grand_total",
		}.get(self.reference_type)

		if field:
			self.sale_value = flt(
				frappe.db.get_value(self.reference_type, self.reference_name, field)
			)

	# --------------------------------------------------------------- follow-up
	def create_followups(self):
		if self.outcome and self.outcome.startswith(LOST_PREFIX) and self.follow_up_required:
			self.create_call_task()
		elif self.outcome == LEAD_OUTCOME:
			self.create_lead()

	def create_call_task(self):
		if self.call_task or not frappe.db.exists("DocType", "Call Task"):
			return

		task = frappe.new_doc("Call Task")
		task.customer = self.customer
		task.contact_name = self.visitor_name
		task.mobile_no = self.mobile_no
		task.branch = self.branch
		task.assigned_to = self.assigned_telecaller
		task.scheduled_date = self.follow_up_date or add_days(nowdate(), 2)
		task.context = _("Walk-in on {0}: {1}").format(
			getdate(self.visit_datetime), self.outcome
		)
		task.reference_type = "Branch Visit Log"
		task.reference_name = self.name
		task.flags.ignore_permissions = True
		task.flags.ignore_mandatory = True
		try:
			task.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: call task for {self.name}")
			return

		self.db_set("call_task", task.name, update_modified=False)

	def create_lead(self):
		if self.lead:
			return

		lead = frappe.new_doc("Lead")
		lead.lead_name = self.visitor_name
		lead.mobile_no = self.mobile_no
		lead.source = "Walk In"
		lead.status = "Lead"
		if lead.meta.has_field("a3_branch"):
			lead.a3_branch = self.branch
		if lead.meta.has_field("a3_visit_log"):
			lead.a3_visit_log = self.name
		if lead.meta.has_field("a3_budget_range"):
			lead.a3_budget_range = self.budget_range
		lead.flags.ignore_permissions = True
		lead.flags.ignore_mandatory = True
		try:
			lead.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: lead for {self.name}")
			return

		self.db_set("lead", lead.name, update_modified=False)


# ---------------------------------------------------------------------------
# Back-linking and analytics
# ---------------------------------------------------------------------------
def link_conversion(reference_type: str, reference_name: str, mobile_no: str,
                    branch: str | None = None) -> str | None:
	"""Attach a sale or job card to today's open visit for that number.

	Called from the Reception Desk and POS so conversion is recorded without the
	counter having to remember (scope 8.1).
	"""
	mobile = normalize_mobile(mobile_no)
	if not mobile:
		return None

	filters = {
		"mobile_no": mobile,
		"outcome": "Pending",
		"visit_datetime": [">=", f"{nowdate()} 00:00:00"],
	}
	if branch:
		filters["branch"] = branch

	visit = frappe.db.get_value("Branch Visit Log", filters, "name", order_by="visit_datetime desc")
	if not visit:
		return None

	outcome = (
		"Converted - Job Card" if reference_type == "Service Job Card" else "Converted - Sale"
	)
	doc = frappe.get_doc("Branch Visit Log", visit)
	doc.outcome = outcome
	doc.reference_type = reference_type
	doc.reference_name = reference_name
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return visit


@frappe.whitelist()
def log_visit(payload) -> dict:
	"""One-call footfall entry from the Footfall Register page."""
	from a3_retail.api import parse_payload, require_permission
	from a3_retail.utils.branch import get_user_branch

	require_permission("Branch Visit Log", "create")
	data = parse_payload(payload)

	doc = frappe.new_doc("Branch Visit Log")
	doc.branch = data.get("branch") or get_user_branch()
	doc.visitor_name = data.get("visitor_name")
	doc.mobile_no = data.get("mobile_no")
	doc.purpose = data.get("purpose")
	doc.visitor_type = data.get("visitor_type") or "New Walk-in"
	doc.budget_range = data.get("budget_range") or "Not Disclosed"
	doc.attended_by = data.get("attended_by") or _session_employee() or _branch_manager(doc.branch)
	doc.how_did_you_hear = data.get("how_did_you_hear")
	doc.remarks = data.get("remarks")
	doc.insert()

	return {"visit_log": doc.name, "customer": doc.customer,
	        "is_existing_customer": doc.is_existing_customer}


def _session_employee() -> str | None:
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


def _branch_manager(branch: str | None) -> str | None:
	"""Attribution fallback: an admin logging a walk-in still needs an owner."""
	if not branch:
		return None
	return frappe.db.get_value("Branch Profile", {"branch": branch}, "branch_manager")


@frappe.whitelist()
def conversion_summary(branch: str | None = None, from_date: str | None = None,
                       to_date: str | None = None) -> dict:
	"""Visits, conversions and value for the control tower and the report."""
	from a3_retail.api import require_permission

	require_permission("Branch Visit Log", "read")

	conditions = ["docstatus < 2"]
	values = {}
	if branch:
		conditions.append("branch = %(branch)s")
		values["branch"] = branch
	if from_date:
		conditions.append("visit_datetime >= %(from_date)s")
		values["from_date"] = from_date
	if to_date:
		conditions.append("visit_datetime <= %(to_date)s")
		values["to_date"] = to_date

	row = frappe.db.sql(
		f"""
		select count(*) as visits,
		       sum(case when outcome like 'Converted%%' then 1 else 0 end) as converted,
		       sum(case when outcome like 'Lost%%' then 1 else 0 end) as lost,
		       sum(case when outcome = 'Lead Created (Follow-up)' then 1 else 0 end) as leads,
		       sum(ifnull(sale_value, 0)) as value
		from `tabBranch Visit Log`
		where {" and ".join(conditions)}
		""",
		values,
		as_dict=True,
	)[0]

	visits = flt(row.visits)
	row["conversion_percent"] = round(flt(row.converted) / visits * 100, 2) if visits else 0.0
	row["average_ticket"] = round(flt(row.value) / flt(row.converted), 2) if flt(row.converted) else 0.0
	return row
