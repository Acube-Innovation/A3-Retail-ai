# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Track six named Apple accessories by serial number.

Apple prints a serial on the adapter and the earpods as well as on the handset,
and the shop wants them followed individually: a warranty claim on an adapter
is answered by the piece, not by a count of them.

Turning serial tracking on is only safe for an item with nothing on a shelf.
Stock already on hand was counted in without serials and could never produce
one, so flipping the flag underneath it leaves pieces nobody can sell — ERPNext
asks for a serial on the next movement and there is none to give. That rule
lives in `stock.can_serialise`, and this patch asks it rather than deciding for
itself.

At the time of writing all six hold stock, so this patch will name them and
change nothing. It is written to be run again: clear a shelf and run it, and
that item is picked up. Nothing here moves stock — counting it out is the
shop's own decision and worth real money.
"""

import frappe

ITEMS = [
	"APPLE ADAPTOR 30 W",
	"APPLE 15 128 GB TEAL",
	"APPLE EARPODS WITH USB-C (MYQY3ZM/A)",
	"APPLE 20W USB C ADAPTER MUVR3HN/A",
	"APPLE 20W USB C POWER ADAPTER MUVR3HN/A",
	"APPLE 30W USB C POWER ADAPTER (MW2G3HN/A)",
]


def execute():
	from a3_retail.api.stock import _set_serialisation, can_serialise, on_hand

	turned, already, held, missing = [], [], [], []

	for wanted in ITEMS:
		code = frappe.db.get_value("Item", {"item_name": wanted}, "name") \
			or (wanted if frappe.db.exists("Item", wanted) else None)
		if not code:
			missing.append(wanted)
			continue

		if frappe.db.get_value("Item", code, "has_serial_no"):
			already.append(code)
			continue
		if not frappe.db.get_value("Item", code, "is_stock_item"):
			# A charge or a service is not a thing with a serial on it.
			missing.append(f"{wanted} (not a stock item)")
			continue

		if not can_serialise(code):
			held.append((code, on_hand(code)))
			continue

		_set_serialisation(code, 1)
		turned.append(code)

	frappe.db.commit()

	print(f"  Apple accessories: {len(turned)} now tracked by serial, "
	      f"{len(already)} already were")
	for code in sorted(turned):
		print(f"      {code}")
	if missing:
		print(f"  {len(missing)} not found on this site:")
		for name in sorted(missing):
			print(f"      {name}")
	if held:
		print(f"  {len(held)} still holding stock, left alone. Count the shelf out, "
		      "run this patch again, then count it back in against serials:")
		for code, qty in sorted(held):
			print(f"      {code} ({qty:g} on hand)")
