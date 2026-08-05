# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Telecalling Campaign (scope 8.4).

"Generate Call List" turns a report, a doctype filter or a visit-log query into
Call Tasks, round-robin across the team. Two exclusions are non-negotiable:
customers flagged Do Not Call, and anyone contacted within the campaign's
cooling-off window.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing

DRAFT = "Draft"
ACTIVE = "Active"
COMPLETED = "Completed"


class TelecallingCampaign(Document):
	def validate(self):
		self.validate_dates()
		self.refresh_metrics()

	def validate_dates(self):
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))

	def refresh_metrics(self):
		if self.is_new():
			return

		rows = frappe.get_all(
			"Call Task",
			filters={"campaign": self.name},
			fields=["call_status", "outcome", "conversion_value"],
		)
		self.allocated_count = len(rows)
		self.called_count = sum(1 for r in rows if r.call_status != "Not Called")
		self.connected_count = sum(1 for r in rows if r.call_status == "Connected")
		self.converted_count = sum(1 for r in rows if r.outcome == "Converted")
		self.conversion_value = sum(flt(r.conversion_value) for r in rows)

		for row in self.get("assigned_team") or []:
			allocated = frappe.db.count(
				"Call Task", {"campaign": self.name, "assigned_to": row.employee}
			)
			completed = frappe.db.count(
				"Call Task",
				{"campaign": self.name, "assigned_to": row.employee,
				 "call_status": ["!=", "Not Called"]},
			)
			row.allocated = allocated
			row.completed = completed

	# ----------------------------------------------------------- call list
	@frappe.whitelist()
	def generate_call_list(self, limit: int = 500) -> dict:
		"""Build the queue and hand it out round-robin."""
		if not self.get("assigned_team"):
			frappe.throw(_("Add at least one telecaller to the team first."))

		candidates = self._candidates(cint(limit))
		eligible = self._filter_eligible(candidates)
		created = self._allocate(eligible)

		self.db_set("target_count", len(candidates), update_modified=False)
		self.reload()
		self.refresh_metrics()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

		return {
			"candidates": len(candidates),
			"eligible": len(eligible),
			"created": created,
			"excluded": len(candidates) - len(eligible),
		}

	def _candidates(self, limit: int) -> list[dict]:
		"""Rows of {customer, contact_name, mobile_no, reference_*} for the queue."""
		if self.target_source == "Branch Visit Log":
			return self._from_visit_logs(limit)
		if self.target_source == "Report" and self.source_report:
			return self._from_report(limit)
		return self._from_doctype(limit)

	def _from_visit_logs(self, limit: int) -> list[dict]:
		filters = {"outcome": ["like", "Lost%"], "follow_up_required": 1}
		if self.branch:
			filters["branch"] = self.branch

		rows = frappe.get_all(
			"Branch Visit Log",
			filters=filters,
			fields=["name", "customer", "visitor_name", "mobile_no", "branch", "outcome"],
			limit_page_length=limit,
			order_by="visit_datetime desc",
		)
		return [
			{
				"customer": r.customer,
				"contact_name": r.visitor_name,
				"mobile_no": r.mobile_no,
				"branch": r.branch,
				"reference_type": "Branch Visit Log",
				"reference_name": r.name,
				"context": _("Lost walk-in: {0}").format(r.outcome),
			}
			for r in rows
		]

	def _from_doctype(self, limit: int) -> list[dict]:
		doctype = self.source_doctype or "Warranty Registration"
		if not frappe.db.exists("DocType", doctype):
			return []

		filters = frappe.parse_json(self.source_filters) if self.source_filters else {}
		meta = frappe.get_meta(doctype)
		fields = ["name"]
		for candidate in ("customer", "customer_mobile", "mobile_no", "branch", "item_name"):
			if meta.has_field(candidate):
				fields.append(candidate)

		rows = frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=limit)
		return [
			{
				"customer": r.get("customer"),
				"contact_name": r.get("customer") or r.get("name"),
				"mobile_no": r.get("customer_mobile") or r.get("mobile_no")
				or _customer_mobile(r.get("customer")),
				"branch": r.get("branch") or self.branch,
				"reference_type": doctype if doctype in _REFERENCE_TYPES else None,
				"reference_name": r.get("name") if doctype in _REFERENCE_TYPES else None,
				"context": _("{0}: {1}").format(doctype, r.get("item_name") or r.get("name")),
			}
			for r in rows
		]

	def _from_report(self, limit: int) -> list[dict]:
		from frappe.desk.query_report import run as run_report

		filters = frappe.parse_json(self.source_filters) if self.source_filters else {}
		try:
			result = run_report(self.source_report, filters=filters, ignore_prepared_report=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: campaign report {self.source_report}")
			return []

		rows = result.get("result") or []
		candidates = []
		for row in rows[:limit]:
			data = row if isinstance(row, dict) else {}
			mobile = data.get("mobile") or data.get("mobile_no") or data.get("customer_mobile")
			if not mobile:
				continue
			candidates.append(
				{
					"customer": data.get("customer"),
					"contact_name": data.get("customer") or data.get("customer_name") or "-",
					"mobile_no": mobile,
					"branch": data.get("branch") or self.branch,
					"context": self.objective,
				}
			)
		return candidates

	def _filter_eligible(self, candidates: list[dict]) -> list[dict]:
		"""Drop DNC customers and anyone contacted too recently (scope 8.4)."""
		cooling_off = cint(self.exclude_contacted_days)
		cutoff = add_days(nowdate(), -cooling_off) if cooling_off else None

		eligible = []
		seen = set()
		for row in candidates:
			mobile = (row.get("mobile_no") or "").strip()
			if not mobile or mobile in seen:
				continue

			if row.get("customer") and frappe.db.get_value("Customer", row["customer"], "a3_dnc"):
				continue

			if cutoff and frappe.db.exists(
				"Call Task",
				{"mobile_no": mobile, "call_datetime": [">", cutoff]},
			):
				continue

			if frappe.db.exists(
				"Call Task", {"campaign": self.name, "mobile_no": mobile}
			):
				continue

			seen.add(mobile)
			eligible.append(row)

		return eligible

	def _allocate(self, rows: list[dict]) -> int:
		"""Round-robin across the team, respecting each caller's target."""
		team = [r for r in self.get("assigned_team") or []]
		if not team:
			return 0

		created = 0
		for index, row in enumerate(rows):
			caller = team[index % len(team)]
			task = frappe.new_doc("Call Task")
			task.campaign = self.name
			task.customer = row.get("customer")
			task.contact_name = row.get("contact_name") or "-"
			task.mobile_no = row.get("mobile_no")
			task.branch = row.get("branch") or self.branch
			task.assigned_to = caller.employee
			task.scheduled_date = getdate(nowdate())
			task.context = row.get("context")
			task.reference_type = row.get("reference_type")
			task.reference_name = row.get("reference_name")
			task.flags.ignore_permissions = True
			task.flags.ignore_mandatory = True
			try:
				task.insert(ignore_permissions=True)
				created += 1
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"A3 Retail: call task for {row}")

		return created


_REFERENCE_TYPES = {"Warranty Registration", "Service Job Card", "Branch Visit Log", "Lead", "Customer"}


def _customer_mobile(customer: str | None) -> str | None:
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, "a3_mobile_no")


def close_finished_campaigns():
	"""Daily — close campaigns whose end date has passed."""
	names = frappe.get_all(
		"Telecalling Campaign",
		filters={"status": ACTIVE, "end_date": ["<", nowdate()]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Telecalling Campaign", name, "status", COMPLETED, update_modified=False)

	commit_if_not_testing()
	return len(names)
