# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Paying a supplier's bill at the counter.

One Payment Entry, against the bill just recorded. It lives here rather than in
either caller because a purchase and a GST expense are the same act as far as
the ledger is concerned, and the cost centre has to be stamped on both: under
`apply_strict_user_permissions` a blank cost centre locks the counter out of
their own payment exactly as a foreign one does.
"""

import frappe
from frappe import _
from frappe.utils import flt


def settle_bill(invoice, paid: float, mode: str, cost_center: str | None = None) -> str:
	"""Pay `paid` against a submitted Purchase Invoice, and return the entry."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	payable = flt(invoice.rounded_total) or flt(invoice.grand_total)
	if paid > payable + 0.5:
		frappe.throw(
			_("Paid amount is more than the bill of {0}.").format(frappe.format_value(
				payable, {"fieldtype": "Currency"})),
			title=_("Paid"),
		)

	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode, "company": invoice.company},
		"default_account",
	)
	if not account:
		frappe.throw(
			_("{0} has no account set for this company — head office has to add it once.")
			.format(mode),
			title=_("Payment"),
		)

	# ERPNext reads the account's balance while building the entry, and branch
	# roles hold select-only on Account on purpose — the chart of accounts is
	# kept off the shop floor. The caller has already been checked for the bill
	# itself, so the mechanical posting runs elevated rather than opening the
	# ledger up to every till.
	actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		entry = get_payment_entry("Purchase Invoice", invoice.name, party_amount=paid)
		entry.reference_no = invoice.bill_no or invoice.name
		entry.reference_date = invoice.posting_date
		entry.mode_of_payment = mode
		entry.paid_from = account
		entry.paid_amount = paid
		entry.base_paid_amount = paid

		# A blank cost centre is as fatal as a foreign one under
		# `apply_strict_user_permissions`: either locks the counter out of the
		# payment they just took.
		centre = cost_center or invoice.get("cost_center")
		if centre:
			entry.cost_center = centre
			for row in entry.get("deductions") or []:
				row.cost_center = centre

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
	finally:
		frappe.set_user(actor)
	return entry.name
