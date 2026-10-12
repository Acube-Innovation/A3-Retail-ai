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
from frappe.utils import flt

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
