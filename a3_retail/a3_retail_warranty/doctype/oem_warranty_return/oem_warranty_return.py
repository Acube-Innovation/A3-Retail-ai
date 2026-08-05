# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""OEM Warranty Return (scope 5.5) — defective parts sent back for credit."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin


class OEMWarrantyReturn(A3BranchMixin, Document):
	def validate(self):
		self.compute_totals()
		self.compute_ageing()
		self.validate_credit()

	def before_update_after_submit(self):
		self.compute_totals()
		self.compute_ageing()
		self.validate_credit()

	def on_submit(self):
		if self.status == "Draft":
			self.status = "Dispatched"
		if not self.dispatch_date:
			self.dispatch_date = getdate(nowdate())

	def compute_totals(self):
		self.total_claim_value = money(sum(flt(row.claim_value) for row in self.get("items") or []))

	def compute_ageing(self):
		self.ageing_days = date_diff(nowdate(), self.dispatch_date) if self.dispatch_date else 0

	def validate_credit(self):
		"""A credit larger than the claim means the rows are wrong."""
		if flt(self.credit_amount) > flt(self.total_claim_value) + 0.01:
			frappe.throw(
				_("Credit received ({0}) exceeds the claim value ({1}).").format(
					frappe.format_value(self.credit_amount, {"fieldtype": "Currency"}),
					frappe.format_value(self.total_claim_value, {"fieldtype": "Currency"}),
				)
			)

		if flt(self.credit_amount) and self.status in ("Dispatched", "Acknowledged"):
			received = sum(flt(row.credit_received) for row in self.get("items") or [])
			self.status = (
				"Credit Received"
				if flt(self.credit_amount) >= flt(self.total_claim_value) - 0.01
				else "Partially Credited"
			)


def flag_overdue_returns():
	"""Weekly — chase OEM returns that have gone quiet."""
	rows = frappe.get_all(
		"OEM Warranty Return",
		filters={"docstatus": 1, "status": ["in", ["Dispatched", "Acknowledged"]]},
		fields=["name", "dispatch_date", "supplier", "total_claim_value"],
	)

	overdue = []
	for row in rows:
		days = date_diff(nowdate(), row.dispatch_date) if row.dispatch_date else 0
		frappe.db.set_value("OEM Warranty Return", row.name, "ageing_days", days,
		                    update_modified=False)
		if days > 30:
			overdue.append(row.name)

	commit_if_not_testing()
	return overdue
