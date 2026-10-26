# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Keeping a repair's payment state in step with its bill.

A Service Job Card was stamped once, when its invoice was raised, and never
again. But the money almost never arrives at that moment: the counter raises
the bill while the customer is still at the desk, then takes the cash, and the
payment lands as a separate entry a minute or a week later. Nothing told the
card, so every settled repair on the bookings list still read "Unpaid".

So the state is derived rather than remembered. Whenever a repair's bill is
submitted, amended or cancelled, and whenever money moves against it, the card
is recomputed from the bill. The bill is the thing that knows.
"""

import frappe
from frappe.utils import cint, flt


def refresh(job_card: str) -> str | None:
	"""Recompute one repair's payment state from its bill. Returns the state."""
	card = frappe.db.get_value(
		"Service Job Card", job_card,
		["name", "sales_invoice", "is_chargeable", "customer_payable",
		 "advance_amount", "payment_status", "outstanding_amount"], as_dict=True)
	if not card:
		return None

	invoice = frappe.db.get_value(
		"Sales Invoice", card.sales_invoice,
		["docstatus", "grand_total", "outstanding_amount"], as_dict=True
	) if card.sales_invoice else None

	# No bill, or one that has been cancelled: what the customer has handed over
	# is the advance and nothing more, so the card says so rather than keeping a
	# "Paid" it earned under a bill that no longer exists.
	if not invoice or cint(invoice.docstatus) != 1:
		owed = flt(card.customer_payable) - flt(card.advance_amount)
		status = _status(card, owed, flt(card.customer_payable))
	else:
		owed = flt(invoice.outstanding_amount)
		status = _status(card, owed, flt(invoice.grand_total))

	changed = {}
	if status != card.payment_status:
		changed["payment_status"] = status
	if abs(flt(card.outstanding_amount) - owed) > 0.005:
		changed["outstanding_amount"] = owed
	if changed:
		# `update_modified=False`: this is the bill talking, not a person
		# editing the repair, and it must not look like one in the audit trail.
		frappe.db.set_value("Service Job Card", card.name, changed,
		                    update_modified=False)
	return status


def _status(card, owed: float, billed: float) -> str:
	"""What to call that. Mirrors `Service Job Card.set_payment_status`."""
	if not flt(card.customer_payable):
		return "Warranty - No Charge" if not cint(card.is_chargeable) else "Unpaid"
	if owed <= 0.005:
		return "Paid"
	# Something has been handed over but not all of it — whether it came in as
	# an advance at booking or a part payment against the bill.
	if flt(card.advance_amount) > 0 or owed < billed - 0.005:
		return "Partly Paid (Advance)"
	return "Unpaid"


def from_invoice(doc, method=None):
	"""Hook: a repair's bill was submitted, amended or cancelled."""
	card = card_for_invoice(doc)
	if card:
		refresh(card)


def from_payment(doc, method=None):
	"""Hook: money moved against a bill, which is when a repair gets paid."""
	for invoice in {row.reference_name for row in doc.get("references") or []
	                if row.reference_doctype == "Sales Invoice" and row.reference_name}:
		card = frappe.db.get_value("Service Job Card", {"sales_invoice": invoice}, "name")
		if card:
			refresh(card)


def card_for_invoice(doc) -> str | None:
	"""The repair a bill came out of, by either of the two links between them."""
	if doc.meta.has_field("a3_service_job_card") and doc.get("a3_service_job_card"):
		return doc.a3_service_job_card
	return frappe.db.get_value("Service Job Card", {"sales_invoice": doc.name}, "name")
