# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Track REALME 16X GLORY WHITE 4/128 by IMEI.

The handset was set up unserialised. A phone that carries no serial number
cannot be matched to the piece that was sold: warranty lookup, the replacement
flow and the whole Serial Numbers list on the item simply have nothing to work
with, and a faulty return has no IMEI to send back to the supplier.

Safe to turn over here because the item holds nothing. Its only history is two
Stock Reconciliations that both moved zero quantity, and the shelf is empty, so
there are no pieces already counted in that could never produce an IMEI.
ERPNext's own rule refuses the change on any submitted document at all, which
is why `_set_serialisation` writes the column rather than saving the Item.
"""

import frappe

ITEMS = ("REALME 16X GLORY WHITE 4/128",)


def execute():
	from a3_retail.api.stock import _set_serialisation, can_serialise, on_hand

	for item_code in ITEMS:
		if not frappe.db.exists("Item", item_code):
			print(f"  {item_code}: no such item, skipped")
			continue
		if frappe.db.get_value("Item", item_code, "has_serial_no"):
			print(f"  {item_code}: already tracked by IMEI")
			continue
		if not can_serialise(item_code):
			# Said plainly rather than thrown: a patch that stops a migration
			# over one handset helps nobody.
			print(f"  {item_code}: {on_hand(item_code)} on hand — left alone, "
			      "clear the shelf and set it from the item screen")
			continue

		_set_serialisation(item_code, 1)
		print(f"  {item_code}: now tracked by IMEI")
