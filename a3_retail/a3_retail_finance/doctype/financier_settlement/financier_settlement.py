# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Financier Settlement (scope 4.6).

The financier disburses the loan net of MDR, subvention and TDS. This document
reconciles what we expected against what the bank actually credited, then clears
the partner's settlement receivable:

    Dr Bank                     33,904
    Dr MDR & Subvention Expense    875
    Dr Input CGST/SGST on MDR   78.75 each
    Dr TDS Receivable           62.50
        Cr Partner Settlement Receivable   34,999
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import (
	DISBURSED,
	GST_ON_MDR,
	SETTLED,
)
from a3_retail.utils import money

VARIANCE_TOLERANCE = 1.0  # rupees; anything larger is queried rather than posted


class FinancierSettlement(Document):
	def before_validate(self):
		if not self.company:
			self.company = frappe.db.get_single_value("Global Defaults", "default_company")

	def validate(self):
		self.validate_period()
		self.compute_totals()
		self.set_status()

	def before_update_after_submit(self):
		self.compute_totals()
		self.set_status()

	def before_submit(self):
		if not flt(self.net_received):
			frappe.throw(_("Enter the amount the financier actually credited before submitting."))

	def on_submit(self):
		self.post_settlement()

	def on_cancel(self):
		self.release_applications()
		self.status = "Draft"

	# ------------------------------------------------------------------ checks
	def validate_period(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date cannot be before From Date."))

	def compute_totals(self):
		"""Sum the rows, then derive what the bank should have sent."""
		partner = frappe.get_cached_doc("Finance Partner", self.finance_partner)

		gross = mdr = subvention = 0.0
		for row in self.get("applications") or []:
			application = frappe.db.get_value(
				"EMI Application",
				row.emi_application,
				["loan_amount", "mdr_amount", "merchant_subvention_cost", "sales_invoice",
				 "customer", "disbursement_date"],
				as_dict=True,
			)
			if not application:
				continue

			row.loan_amount = flt(application.loan_amount)
			row.mdr = flt(application.mdr_amount)
			row.subvention = flt(application.merchant_subvention_cost)
			row.gst_on_mdr = money(row.mdr * GST_ON_MDR / 100)
			row.net_amount = money(row.loan_amount - row.mdr - row.gst_on_mdr - row.subvention)
			row.sales_invoice = application.sales_invoice
			row.customer = application.customer
			row.invoice_date = application.disbursement_date

			gross += row.loan_amount
			mdr += row.mdr
			subvention += row.subvention

		self.gross_amount = money(gross)
		self.mdr_amount = money(mdr)
		self.subvention_amount = money(subvention)
		# GST on MDR is an input credit for us, so the financier withholds it too.
		self.gst_on_mdr = money(mdr * GST_ON_MDR / 100)

		if flt(partner.mdr_percent) and not flt(self.tds_amount) and partner.tds_applicable:
			# 194-H commission TDS, deducted by the financier on the MDR.
			self.tds_amount = money(mdr * 5.0 / 100)

		self.net_expected = money(
			self.gross_amount - self.mdr_amount - self.gst_on_mdr - self.subvention_amount
			- flt(self.tds_amount) - flt(self.other_deductions)
		)
		self.variance = money(flt(self.net_received) - flt(self.net_expected))

	def set_status(self):
		"""Reconciliation is visible while still drafting.

		The workflow is: draft -> pull applications -> key in the bank credit ->
		see whether it reconciles -> submit to post. So the status follows the
		numbers, and stays Draft only while no credit has been entered.
		"""
		if self.docstatus == 2:
			self.status = "Draft"
		elif not flt(self.net_received):
			self.status = "Draft"
		elif abs(flt(self.variance)) > VARIANCE_TOLERANCE:
			self.status = "Variance - Under Query"
		else:
			self.status = "Reconciled"

	# ---------------------------------------------------------------- posting
	def post_settlement(self):
		"""One Journal Entry clears the receivable and books every deduction."""
		if not self.get("applications"):
			frappe.throw(_("Add at least one application before submitting."))

		partner = frappe.get_cached_doc("Finance Partner", self.finance_partner)
		abbr = frappe.get_cached_value("Company", self.company, "abbr")

		entry = frappe.new_doc("Journal Entry")
		entry.voucher_type = "Journal Entry"
		entry.company = self.company
		entry.posting_date = getdate(nowdate())
		entry.user_remark = _("Settlement {0} from {1}").format(self.name, self.finance_partner)
		# ERPNext pairs cheque_no with cheque_date; setting only the date throws.
		if entry.meta.has_field("cheque_no") and self.utr_reference:
			entry.cheque_no = self.utr_reference
			entry.cheque_date = getdate(nowdate())

		# Debits — what we received and what was withheld.
		_append(entry, self.bank_account, debit=flt(self.net_received))
		_append(entry, partner.mdr_expense_account,
		        debit=money(flt(self.mdr_amount) + flt(self.subvention_amount)))

		for account_name in ("Input Tax CGST", "Input Tax SGST"):
			account = _find_account(self.company, account_name, abbr)
			if account:
				_append(entry, account, debit=money(flt(self.gst_on_mdr) / 2))

		if flt(self.tds_amount):
			tds_account = _find_account(self.company, "TDS Payable", abbr)
			if tds_account:
				_append(entry, tds_account, debit=flt(self.tds_amount))

		if flt(self.other_deductions):
			_append(entry, partner.mdr_expense_account, debit=flt(self.other_deductions))

		# Credit — clear the partner's receivable in full.
		_append(entry, partner.settlement_account, credit=flt(self.gross_amount))

		# A short credit from the bank is still an expense until it is queried.
		difference = flt(self.gross_amount) - sum(flt(row.debit_in_account_currency) for row in entry.accounts)
		if abs(difference) > 0.009:
			_append(entry, partner.mdr_expense_account, debit=difference)

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()

		self.db_set("journal_entry", entry.name, update_modified=False)
		self.mark_applications_settled()
		return entry.name

	def mark_applications_settled(self):
		for row in self.get("applications") or []:
			frappe.db.set_value(
				"EMI Application",
				row.emi_application,
				{"status": SETTLED, "settlement": self.name, "amount_received": flt(row.net_amount)},
				update_modified=False,
			)

	def release_applications(self):
		for row in self.get("applications") or []:
			frappe.db.set_value(
				"EMI Application",
				row.emi_application,
				{"status": DISBURSED, "settlement": None, "amount_received": 0},
				update_modified=False,
			)

	# ------------------------------------------------------------------ fetch
	@frappe.whitelist()
	def get_pending_applications(self) -> int:
		"""Pull every disbursed-but-unsettled application in the period."""
		existing = {row.emi_application for row in self.get("applications") or []}

		rows = frappe.get_all(
			"EMI Application",
			filters={
				"docstatus": 1,
				"finance_partner": self.finance_partner,
				"status": DISBURSED,
				"disbursement_date": ["between", [self.from_date, self.to_date]],
			},
			pluck="name",
		)

		added = 0
		for name in rows:
			if name in existing:
				continue
			self.append("applications", {"emi_application": name})
			added += 1

		self.compute_totals()
		return added


def _append(entry, account: str, debit: float = 0, credit: float = 0):
	if not account or (not flt(debit) and not flt(credit)):
		return
	entry.append(
		"accounts",
		{
			"account": account,
			"debit_in_account_currency": flt(debit),
			"credit_in_account_currency": flt(credit),
		},
	)


def _find_account(company: str, fragment: str, abbr: str) -> str | None:
	exact = f"{fragment} - {abbr}"
	if frappe.db.exists("Account", exact):
		return exact
	return frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 0, "account_name": ["like", f"%{fragment}%"]},
		"name",
	)


@frappe.whitelist()
def receivable_by_partner() -> list[dict]:
	"""Outstanding financier receivable — scope 4.11 validation query."""
	from a3_retail.api import require_permission

	require_permission("EMI Application", "read")

	return frappe.db.sql(
		"""
		select fp.name as finance_partner, fp.partner_name,
		       count(a.name) as applications, sum(a.loan_amount) as outstanding
		from `tabEMI Application` a
		join `tabFinance Partner` fp on fp.name = a.finance_partner
		where a.docstatus = 1 and a.status = %(status)s
		group by fp.name, fp.partner_name
		order by outstanding desc
		""",
		{"status": DISBURSED},
		as_dict=True,
	)
