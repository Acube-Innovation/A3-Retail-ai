# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Expense.

What the shop spent, itemised. The counter thinks of an expense the way its old
billing software showed it — a category, a few lines with a quantity and a rate,
who it was paid to, what was paid now and what is still owed — so that is what
this document holds.

The accounting underneath stays the plain one it has always been: a Journal
Entry debiting each line's expense account and crediting whatever the money came
out of. Nothing here writes a ledger entry by hand.

Anything left owing is credited to the supplier's payable account instead, which
is the only reason a supplier is ever compulsory here: a balance has to be owed
to somebody.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code


class BranchExpense(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.company:
			self.company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not self.cost_center:
			profile = get_branch_profile(self.branch) or frappe._dict()
			self.cost_center = profile.get("sales_cost_center") or profile.get("cost_center")

	def validate(self):
		self.validate_date()
		self.set_line_amounts()
		self.set_totals()
		self.validate_payment()

	def validate_date(self):
		if getdate(self.posting_date) > getdate(nowdate()):
			frappe.throw(_("An expense cannot be dated in the future."), title=_("Date"))

	def set_line_amounts(self):
		"""Every line needs a figure, a description and somewhere to land."""
		for row in self.items:
			row.qty = flt(row.qty) or 1
			row.amount = flt(row.qty) * flt(row.rate)
			if not row.description:
				row.description = frappe.db.get_value("Item", row.item_code, "item_name") \
					if row.item_code else None
			if not row.description:
				frappe.throw(
					_("Row {0}: say what the money was spent on.").format(row.idx),
					title=_("Description"))
			if not row.expense_account:
				row.expense_account = _item_account(row.item_code) or self.category

	def set_totals(self):
		self.total = flt(sum(flt(row.amount) for row in self.items))
		self.discount_amount = flt(self.discount_amount)
		if self.discount_amount > self.total:
			frappe.throw(
				_("The discount is more than the expense itself."), title=_("Discount"))
		self.grand_total = flt(self.total - self.discount_amount)

		# Nothing entered means it was all paid, which is what a shop means by an
		# expense unless it says otherwise.
		if self.paid_amount is None or self.is_new() and not flt(self.paid_amount):
			self.paid_amount = self.grand_total
		self.paid_amount = flt(self.paid_amount)
		self.outstanding_amount = flt(self.grand_total - self.paid_amount)

	def validate_payment(self):
		if self.grand_total <= 0:
			frappe.throw(_("An expense has to come to something."), title=_("Amount"))
		if self.paid_amount < 0:
			frappe.throw(_("Paid now cannot be negative."), title=_("Paid"))
		if self.outstanding_amount < 0:
			frappe.throw(
				_("More was paid than the expense comes to."), title=_("Paid"))
		if flt(self.paid_amount) and not self.paid_from:
			frappe.throw(_("Say where the money came from."), title=_("Paid from"))
		if self.outstanding_amount > 0 and not self.supplier:
			frappe.throw(
				_("Something is still owed, so name the supplier it is owed to."),
				title=_("Supplier"))

	# ------------------------------------------------------------------ posting
	def on_submit(self):
		self.journal_entry = self.make_journal_entry()
		self.db_set("journal_entry", self.journal_entry)

	def on_cancel(self):
		if not self.journal_entry:
			return
		entry = frappe.get_doc("Journal Entry", self.journal_entry)
		if entry.docstatus == 1:
			entry.flags.ignore_permissions = True
			entry.cancel()

	def make_journal_entry(self) -> str:
		"""Debit what it was spent on, credit what it was paid with."""
		doc = frappe.new_doc("Journal Entry")
		doc.voucher_type = "Journal Entry"
		doc.company = self.company
		doc.posting_date = self.posting_date
		doc.user_remark = self.remark()
		if self.reference_no:
			# The posting carries the shop's own slip number. ERPNext treats the
			# pair as one field and refuses the number without a date for it.
			doc.cheque_no = self.reference_no
			doc.cheque_date = self.posting_date
		if doc.meta.has_field("branch"):
			doc.branch = self.branch
		if doc.meta.has_field("a3_is_branch_expense"):
			doc.a3_is_branch_expense = 1

		# A discount is a smaller expense, not an income, so it comes off the
		# lines rather than going somewhere of its own. Spread across them in
		# proportion, with the rounding put on the largest line.
		for row, share in zip(self.items, self.discounted_amounts()):
			doc.append("accounts", {
				"account": row.expense_account,
				"debit_in_account_currency": share,
				"cost_center": self.cost_center,
				"user_remark": row.description,
			})

		if flt(self.paid_amount):
			doc.append("accounts", {
				"account": self.paid_from,
				"credit_in_account_currency": flt(self.paid_amount),
				"cost_center": self.cost_center,
			})
		if flt(self.outstanding_amount):
			doc.append("accounts", {
				"account": self.payable_account(),
				"credit_in_account_currency": flt(self.outstanding_amount),
				"party_type": "Supplier",
				"party": self.supplier,
				"cost_center": self.cost_center,
			})

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def discounted_amounts(self) -> list[float]:
		"""Each line's share of the total after the discount, adding up exactly."""
		amounts = [flt(row.amount) for row in self.items]
		if not flt(self.discount_amount) or not self.total:
			return amounts

		scale = flt(self.grand_total) / flt(self.total)
		shares = [flt(a * scale, 2) for a in amounts]
		drift = flt(self.grand_total - sum(shares), 2)
		if drift:
			biggest = amounts.index(max(amounts))
			shares[biggest] = flt(shares[biggest] + drift, 2)
		return shares

	def payable_account(self) -> str:
		account = frappe.get_cached_value("Company", self.company, "default_payable_account")
		if not account:
			frappe.throw(
				_("This company has no default payable account, so nothing can be "
				  "left owing on an expense."),
				title=_("Payables"))
		return account

	def remark(self) -> str:
		who = self.supplier_name() or self.paid_to
		parts = [self.notes or frappe.db.get_value("Account", self.category, "account_name")]
		if who:
			parts.append(_("paid to {0}").format(who))
		parts.append(f"{self.branch}")
		return " — ".join(p for p in parts if p)

	def supplier_name(self) -> str | None:
		return frappe.db.get_value("Supplier", self.supplier, "supplier_name") \
			if self.supplier else None


def _item_account(item_code: str | None) -> str | None:
	"""An item's own expense account, when it has been given one."""
	if not item_code:
		return None
	return frappe.db.get_value("Item Default", {"parent": item_code}, "expense_account")
