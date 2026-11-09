# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Track the Apple stock by IMEI, wherever it still can be.

A phone, a watch or an iPad that carries no serial number cannot be matched to
the piece that was sold. Warranty lookup has nothing to work with, the
replacement flow cannot say which one came back, and a faulty return has no
number to send to the distributor. Thirty of the Apple lines were set up with
IMEI tracking and seventy-nine were not, which is why a counter can scan one
box and not the next.

WHAT COUNTS AS APPLE. The shop's own shelf labels, not a guess from the name:
the item groups APPLE, APPLE EARPODS and APPLE ADAPTOR, plus anything whose
brand is Apple. Reading names instead would have swept in BOAT AIRPODS, ZEB
BLUETOOTH AIRPODS and IPHONE PREMIUM TEMPERED GLASS — a screen protector with
211 on the shelf, which is not a thing with a serial number on it.

WHAT IS LEFT ALONE. A line with stock on the shelf. Those pieces were counted
in without IMEIs and could never produce one, so turning the setting over
underneath them leaves ERPNext asking for numbers that do not exist the next
time one is sold. Four lines are in that state; they are named when this runs,
and the shop can clear the shelf and set them from the item screen. Services
and charges in the group are skipped too — `CARD CHARGES` is filed under APPLE
and is not a thing at all.

ERPNext's own rule is blunter than the risk: any submitted document that ever
named the item refuses the change, including a reconciliation that moved zero
quantity. That is why `_set_serialisation` writes the column rather than saving
the Item — the stock on the shelf is the real question, and `can_serialise`
has already asked it.
"""

import frappe

#: The shop's own labels for the Apple shelf.
GROUPS = ("APPLE", "APPLE EARPODS", "APPLE ADAPTOR")
BRAND = "Apple"

#: Lines filed on the shelf that are not goods. `CARD CHARGES` sits in the
#: APPLE group marked as stock, which it is not — asking a counter for a serial
#: number before it can add a card fee to a bill would stop the sale. Named
#: when this runs, because the item itself wants correcting.
NOT_GOODS = ("CHARGE", "CHARGES", "FEE", "DISCOUNT", "ROUND OFF")


def execute():
	items = _apple_items()
	if not items:
		print("  no Apple items on this site")
		return

	from a3_retail.api.stock import _set_serialisation, can_serialise, on_hand

	turned, already, held, skipped = 0, 0, [], []
	for item in items:
		if frappe.db.get_value("Item", item, "has_serial_no"):
			already += 1
			continue
		if not frappe.db.get_value("Item", item, "is_stock_item") or _is_a_charge(item):
			skipped.append(item)
			continue
		if not can_serialise(item):
			held.append((item, on_hand(item)))
			continue
		_set_serialisation(item, 1)
		turned += 1

	frappe.db.commit()
	print(f"  Apple: {turned} item(s) now tracked by IMEI, {already} already were")
	if skipped:
		print(f"  {len(skipped)} line(s) that are not goods, left alone: "
		      + ", ".join(sorted(skipped)))
	if held:
		print(f"  {len(held)} still holding stock, left alone — clear the shelf and "
		      "set them from the item screen:")
		for item, qty in sorted(held):
			print(f"      {item} ({qty:g} on hand)")


def _is_a_charge(item: str) -> bool:
	"""Does this line read as money rather than a thing on a shelf?"""
	name = (frappe.db.get_value("Item", item, "item_name") or item).upper()
	return any(word in name.split() for word in NOT_GOODS)


def _apple_items() -> list[str]:
	"""Every item on the Apple shelf, by the shop's own filing."""
	groups = [g for g in GROUPS if frappe.db.exists("Item Group", g)]
	conditions, values = [], {}
	if groups:
		conditions.append("item_group in %(groups)s")
		values["groups"] = groups
	if frappe.db.exists("Brand", BRAND):
		conditions.append("brand = %(brand)s")
		values["brand"] = BRAND
	if not conditions:
		return []

	return [row[0] for row in frappe.db.sql(
		f"""select name from tabItem
		    where ifnull(disabled, 0) = 0 and ({" or ".join(conditions)})
		    order by name""", values)]
