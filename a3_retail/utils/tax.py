# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""What rate an Item Tax Template actually charges.

A GST template is not one number. india_compliance writes fifteen rows into
every one of them — CGST, SGST and IGST, each again for reverse charge, refund
and input credit — so "GST 18%" contains 9, 18, -9, -18 and 9 again.

The rate the shop means, and the rate printed on the invoice, is the undivided
one: IGST, the whole charge in a single row, where CGST and SGST are the two
halves it splits into when buyer and seller share a state. Every other row is
either one of those halves or a negative counterpart, so the largest row in the
template is the rate. It is read in one place because every screen that shows a
tax rate has to agree with the one the bill posts.
"""

import frappe
from frappe.utils import cint, flt

DEFAULT_GST_RATE = 18.0


def template_rate(template: str | None) -> float:
	"""The GST percentage a template charges, or 0 if it charges nothing."""
	if not template:
		return 0.0
	return flt(frappe.db.get_value(
		"Item Tax Template Detail", {"parent": template}, "tax_rate",
		order_by="tax_rate desc"))


def item_rate(item_code: str) -> float:
	"""The rate this item is taxed at, falling back to the shop's usual 18%."""
	template = frappe.db.get_value(
		"Item Tax", {"parenttype": "Item", "parent": item_code}, "item_tax_template")
	# A deliberately nil-rated item charges nothing, and that is not a gap to
	# fill with a default — so only a missing template falls back.
	return template_rate(template) if template else DEFAULT_GST_RATE


def templates() -> list[dict]:
	"""Every rate an item can be put on, as the shop names it."""
	out = [{"name": name, "rate": template_rate(name)}
	       for name in frappe.get_all("Item Tax Template", pluck="name", order_by="name")]
	out.sort(key=lambda t: (t["rate"], t["name"]))
	return out


def input_gst_template(company: str, branch: str, supplier: str,
                       rate: int) -> str | None:
	"""The input-GST template for buying from this supplier, at that rate.

	In-state buying splits into CGST and SGST; from another state it is one
	IGST line. Which it is comes off the supplier's own GSTIN, since that is
	where the goods are being billed from.

	No GSTIN, no GST. An unregistered dealer cannot charge it, and india
	compliance refuses the document outright if the bill tries to — which is the
	right answer, just a late one. Callers that must not get that late refusal
	check `has_gstin()` first and say so while the counter can still fix it.
	"""
	theirs = supplier_gstin(supplier)
	if not theirs:
		return None

	ours = frappe.db.get_value("Branch Profile", {"branch": branch}, "state_code")
	out_of_state = bool(ours and not str(theirs).startswith(str(ours)))

	kind = "Out-state" if out_of_state else "In-state"
	for candidate in (f"Input GST {kind} {rate}%", f"Input GST In-state {rate}%"):
		name = frappe.db.get_value(
			"Purchase Taxes and Charges Template",
			{"title": candidate, "company": company}, "name")
		if name:
			return name
	return None


def supplier_gstin(supplier: str | None) -> str | None:
	"""The supplier's GSTIN, on a site where that column may not exist."""
	if not supplier or not frappe.db.has_column("Supplier", "gstin"):
		return None
	return frappe.db.get_value("Supplier", supplier, "gstin") or None


def bill_rate(items) -> int | None:
	"""The rate a bill is taxed at, from the items on it.

	A mixed bill takes the highest rate its lines carry; ERPNext still splits
	the tax per line on the document itself.
	"""
	rates = {cint(item_rate(row.item_code)) for row in items or [] if row.item_code}
	rates.discard(0)
	return max(rates) if rates else None


def template_for_rate(rate: float) -> str | None:
	"""The Item Tax Template charging this rate, when the shop has one.

	A bill carries one taxes-and-charges template for its account heads, but a
	line taxed differently from the rest needs its own template or ERPNext puts
	the bill's rate on it. This is how a mixed-rate bill still adds up.
	"""
	for row in templates():
		if cint(row["rate"]) == cint(rate):
			return row["name"]
	return None
