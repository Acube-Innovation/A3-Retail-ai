# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Expense.

What the shop spent, itemised. The counter thinks of an expense the way its old
billing software showed it — a category, a few lines with a quantity and a rate,
who it was paid to, what was paid now and what is still owed — so that is what
this document holds.

What it posts underneath depends on what kind of spend it is, because the three
kinds are not interchangeable:

* a **GST bill** becomes a Purchase Invoice, because the input credit only
  reaches the purchase register and GSTR-2B from one of those — a journal
  debiting Input CGST balances the books and still loses the claim;
* a spend **an employee paid out of their own pocket** becomes an Expense Claim,
  so what the shop owes them sits against their name;
* **everything else** becomes a Journal Entry, which is what petty cash is.

Nothing here writes a ledger entry by hand.

Anything left owing is credited to the supplier's payable account instead, which
is the only reason a supplier is ever compulsory here: a balance has to be owed
to somebody.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.utils import tax
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code


class BranchExpense(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		# Runs after `insert` has re-applied defaults, which is the point: see
		# `api/expenses.create` for why a blank Employee cannot be left blank.
		if "paid_by_employee" in self.flags:
			self.employee = self.flags.paid_by_employee
		if not self.company:
			self.company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not self.cost_center:
			profile = get_branch_profile(self.branch) or frappe._dict()
			self.cost_center = profile.get("sales_cost_center") or profile.get("cost_center")

	def validate(self):
		self.validate_date()
		self.set_line_amounts()
		self.set_totals()
		self.validate_route()
		self.validate_payment()

	def validate_date(self):
		if getdate(self.posting_date) > getdate(nowdate()):
			frappe.throw(_("An expense cannot be dated in the future."), title=_("Date"))

	def set_line_amounts(self):
		"""Every line needs a figure, a description and somewhere to land."""
		for row in self.items:
			row.qty = flt(row.qty) or 1
			row.amount = flt(row.qty) * flt(row.rate)
			# The rate on the line is what was paid before tax, so the tax is on
			# top of it rather than inside it — an expense bill reads that way.
			row.gst_rate = flt(row.gst_rate) if self.with_gst else 0
			row.tax_amount = flt(row.amount * row.gst_rate / 100, 2)
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
		self.tax_amount = flt(sum(flt(row.tax_amount) for row in self.items))
		self.discount_amount = flt(self.discount_amount)
		if self.discount_amount > self.total:
			frappe.throw(
				_("The discount is more than the expense itself."), title=_("Discount"))
		self.grand_total = flt(self.total - self.discount_amount + self.tax_amount)

		# Nothing entered means it was all paid, which is what a shop means by an
		# expense unless it says otherwise. A screen that did say otherwise sets
		# the flag: a staff member who is owed the money back until month end
		# has to be able to enter nought and have it stay nought.
		told = self.flags.get("paid_amount_given")
		if self.paid_amount is None or (
				self.is_new() and not flt(self.paid_amount) and not told):
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
		# A balance has to be owed to somebody ERPNext can keep a payable
		# against. A supplier usually; an employee when they paid for it.
		if self.outstanding_amount > 0 and not (self.supplier or self.employee):
			frappe.throw(
				_("Something is still owed, so name the supplier it is owed to."),
				title=_("Supplier"))

	# -------------------------------------------------------------------- route
	def route(self) -> str:
		"""Which of the three documents this spend has to become."""
		if self.with_gst:
			return "Supplier Invoice"
		if self.employee:
			return "Employee Claim"
		return "Journal"

	def validate_route(self):
		"""Refuse, while the counter can still fix it, what would fail later."""
		if self.with_gst and self.employee:
			frappe.throw(
				_("A GST bill cannot also be an employee claim. Either enter it as "
				  "the supplier's bill, or as what {0} paid out of pocket.")
				.format(self.employee_name() or _("the employee")),
				title=_("One or the other"))

		if self.with_gst:
			if not self.supplier:
				frappe.throw(
					_("A GST bill is the supplier's own bill, so name the supplier "
					  "it came from."), title=_("Supplier"))
			# Caught here rather than by india_compliance on submit: the counter
			# is still looking at the screen, and the fix is one field away.
			if not tax.supplier_gstin(self.supplier):
				frappe.throw(
					_("{0} has no GSTIN on file, so this cannot be entered as a GST "
					  "bill. Add their GSTIN first, or untick Expense With GST.")
					.format(self.supplier_name() or self.supplier),
					title=_("GSTIN"))
			if not self.reference_no:
				frappe.throw(
					_("Enter the supplier's bill number. GST will not accept a "
					  "purchase bill without one."), title=_("Bill number"))

		# `is_paid` on an Expense Claim settles the whole claim or none of it,
		# so a half-reimbursed one has nowhere to put the remainder.
		if self.employee and flt(self.paid_amount) and self.outstanding_amount > 0.005:
			frappe.throw(
				_("An employee claim is either reimbursed in full or left owing. "
				  "Put {0} in Paid Now, or leave it at zero.")
				.format(frappe.format_value(self.grand_total,
				                            {"fieldtype": "Currency"})),
				title=_("Part payment"))

	# ------------------------------------------------------------------ posting
	def on_submit(self):
		posted = self.route()
		if posted == "Supplier Invoice":
			self.db_set({"purchase_invoice": self.make_purchase_invoice(),
			             "posted_as": posted})
		elif posted == "Employee Claim":
			self.db_set({"expense_claim": self.make_expense_claim(),
			             "posted_as": posted})
		else:
			self.db_set({"journal_entry": self.make_journal_entry(),
			             "posted_as": posted})

	def on_cancel(self):
		"""Reverse whatever this became, payment first so the bill will cancel."""
		if self.purchase_invoice:
			for name in frappe.get_all(
					"Payment Entry Reference",
					filters={"reference_name": self.purchase_invoice, "docstatus": 1},
					pluck="parent"):
				entry = frappe.get_doc("Payment Entry", name)
				if entry.docstatus == 1:
					entry.flags.ignore_permissions = True
					entry.cancel()
			# Loaded last on purpose: cancelling the payment rewrites the bill's
			# outstanding, so a copy read before that is already stale.
			self._reverse(frappe.get_doc("Purchase Invoice", self.purchase_invoice))

		for doctype, name in (("Expense Claim", self.expense_claim),
		                      ("Journal Entry", self.journal_entry)):
			if name:
				self._reverse(frappe.get_doc(doctype, name))

	@staticmethod
	def _reverse(doc) -> None:
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()

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

		# Input tax is money back from the department, not a cost, so it is its
		# own debit rather than part of what the shop spent. Kerala to Kerala, so
		# it splits in half the way every other local bill here does.
		for account, share in self.tax_debits():
			doc.append("accounts", {
				"account": account,
				"debit_in_account_currency": share,
				"cost_center": self.cost_center,
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

	def make_purchase_invoice(self) -> str:
		"""The supplier's own bill, so the input credit survives to return time.

		Nothing is stocked: an expense bill buys a service, a consumable or a
		repair, so there is no warehouse and no valuation — which is the whole
		difference between this and `api/purchases.py`.
		"""
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		from a3_retail.api import stamp_cost_center

		doc = frappe.new_doc("Purchase Invoice")
		doc.company = self.company
		doc.supplier = self.supplier
		doc.posting_date = self.posting_date
		doc.set_posting_time = 1
		doc.bill_no = self.reference_no
		doc.bill_date = self.posting_date
		if self.due_date:
			doc.due_date = self.due_date
		if doc.meta.has_field("branch"):
			doc.branch = self.branch
		doc.remarks = (self.notes or self.remark())[:500]

		for row in self.items:
			line = doc.append("items", {
				"qty": flt(row.qty) or 1,
				"rate": flt(row.rate),
				"expense_account": row.expense_account,
				"cost_center": self.cost_center,
			})
			if row.item_code:
				line.item_code = row.item_code
			# A typed line is not in the catalogue, so it carries its own name
			# rather than a code — the same shape courier dispatch bills use.
			line.item_name = (row.description or "")[:140]
			line.description = row.description
			if row.uom:
				line.uom = row.uom

		# The supplier's discount came off before they charged tax, so it goes
		# on the net total rather than into the rates.
		if flt(self.discount_amount):
			doc.apply_discount_on = "Net Total"
			doc.discount_amount = flt(self.discount_amount)

		self.apply_bill_tax(doc, get_taxes_and_charges)

		# After the taxes: `get_taxes_and_charges` brings the template's own cost
		# centre with it, and a cost centre from another branch makes the bill
		# unreadable to the counter that entered it.
		stamp_cost_center(doc, self.cost_center)

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()

		if flt(self.paid_amount):
			from a3_retail.utils.payments import settle_bill

			if not self.mode_of_payment:
				frappe.throw(_("Say how the supplier was paid."), title=_("Payment"))
			doc.reload()
			settle_bill(doc, flt(self.paid_amount), self.mode_of_payment,
			            self.cost_center)
		return doc.name

	def apply_bill_tax(self, doc, get_taxes_and_charges) -> None:
		"""Put the counter's GST on the bill, line rates and all."""
		rates = {cint(row.gst_rate) for row in self.items}
		rates.discard(0)
		if not rates:
			return

		template = tax.input_gst_template(
			self.company, self.branch, self.supplier, max(rates))
		if not template:
			frappe.throw(
				_("No input GST template for {0}% — head office has to add it once.")
				.format(max(rates)), title=_("GST"))

		doc.taxes_and_charges = template
		doc.set("taxes", [])
		for row in get_taxes_and_charges("Purchase Taxes and Charges Template", template):
			doc.append("taxes", row)

		# A bill carries one template for its account heads. A line taxed at a
		# different rate needs its own, or ERPNext charges it the bill's rate.
		if len(rates) > 1:
			for line, row in zip(doc.items, self.items):
				if cint(row.gst_rate) and cint(row.gst_rate) != max(rates):
					line.item_tax_template = tax.template_for_rate(row.gst_rate)

	def make_expense_claim(self) -> str:
		"""What a member of staff paid out of pocket, owed back to them."""
		doc = frappe.new_doc("Expense Claim")
		doc.employee = self.employee
		doc.company = self.company
		doc.posting_date = self.posting_date
		doc.cost_center = self.cost_center
		doc.remark = (self.notes or self.remark())[:500]
		doc.payable_account = self.payable_account()
		# The counter recording it is the approval: in a shop this size the
		# person who hands the money back is the person entering it.
		doc.approval_status = "Approved"

		claim_type = _claim_type()
		for row, share in zip(self.items, self.discounted_amounts()):
			doc.append("expenses", {
				"expense_date": self.posting_date,
				"expense_type": claim_type,
				"description": row.description,
				"amount": share,
				"sanctioned_amount": share,
				"cost_center": self.cost_center,
				# Set here on purpose: hrms keeps an account the caller gave and
				# only falls back to the claim type's own mapping when it is
				# blank. That is what lets the shop's own categories be used
				# without a claim type per category.
				"default_account": row.expense_account,
			})

		if flt(self.paid_amount):
			doc.is_paid = 1
			doc.mode_of_payment = self.mode_of_payment
			if not doc.mode_of_payment:
				frappe.throw(_("Say how the money was handed back."), title=_("Payment"))

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def employee_name(self) -> str | None:
		return frappe.db.get_value("Employee", self.employee, "employee_name") \
			if self.employee else None

	def tax_debits(self) -> list[tuple[str, float]]:
		"""The input GST, split so the two halves still add up to the whole."""
		if not flt(self.tax_amount):
			return []
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		central, state = f"Input Tax CGST - {abbr}", f"Input Tax SGST - {abbr}"
		for account in (central, state):
			if not frappe.db.exists("Account", account):
				frappe.throw(
					_("{0} is missing, so the input tax has nowhere to go.")
					.format(account), title=_("Input GST"))
		half = flt(flt(self.tax_amount) / 2, 2)
		return [(central, half), (state, flt(self.tax_amount - half, 2))]

	def discounted_amounts(self) -> list[float]:
		"""Each line's share of the total after the discount, adding up exactly."""
		amounts = [flt(row.amount) for row in self.items]
		if not flt(self.discount_amount) or not self.total:
			return amounts

		net = flt(self.total - self.discount_amount)
		scale = net / flt(self.total)
		shares = [flt(a * scale, 2) for a in amounts]
		drift = flt(net - sum(shares), 2)
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


def _claim_type() -> str:
	"""One claim type for everything the counter files.

	The expense category is carried on the line's own account instead, so the
	shop's own words for what it spends on do not have to be duplicated as a
	claim type each time somebody invents one.
	"""
	name = "Branch Expense"
	if not frappe.db.exists("Expense Claim Type", name):
		frappe.get_doc({"doctype": "Expense Claim Type", "expense_type": name,
		                "description": "Recorded from the branch expense screen."}
		               ).insert(ignore_permissions=True)
	return name
