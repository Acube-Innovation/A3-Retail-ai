# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The eight accessories that were already on file under a short code.

The shop's stock sheet listed eighteen lines. Ten were new and went in with
`accessories_psla_opening_stock`. The other eight were already in the catalogue
under the codes the old shop used — T100, P 150, P 250-2 — so they were left
alone rather than entered twice.

That was right about duplicates and wrong about everything else: a counter
looking for tempered glass types "tempered" and finds nothing, because the item
is called "T100". So each keeps its code — bills and the ledger point at it —
and gains the name the shop uses, the heading it belongs under, its barcode and
its price.

It deliberately posts no stock. Three of the eight have a twin left over from
the migration — T100 and T100-2, P 150 and P 150-2 — and the twin is where the
stock actually sits. Counting the sheet onto the bare code while the twin holds
its own figure shows one product twice and inflates the shelf. The pairs have
to be merged first, and which record survives is the shop's call, not a
patch's. Until then this reports each pair and leaves the figures alone.
"""

import frappe
from frappe.utils import flt, getdate, nowdate

BRANCH = "PhoneXpert Accessories PSLA"
WAREHOUSE = "PhoneXpert Accessories PSLA - PT"
NOTE = "Opening stock — accessories already on file under a short code"

ITEMS = (
	{"code": "T100", "name": "TEMPERED - 100 T100", "group": "TEMPERED GLASS",
	 "hsn": "70071900", "barcode": "842648753788", "price": 100.0, "qty": 4216},
	{"code": "T 150", "name": "TEMPERED - 150 T150", "group": "TEMPERED GLASS",
	 "hsn": "70071900", "barcode": "815645174144", "price": 150.0, "qty": 4570},
	{"code": "T 200", "name": "TEMPERED - 200 T200", "group": "TEMPERED GLASS",
	 "hsn": "70071900", "barcode": "992688342326", "price": 200.0, "qty": 649},
	{"code": "T 300", "name": "TEMPERED - 300 IPHONE PREMIUM T300",
	 "group": "TEMPERED GLASS", "hsn": "70071900",
	 "barcode": "373610659717", "price": 300.0, "qty": 470},
	{"code": "T 450", "name": "TEMPERED - 450 PREMIUM PRIVACY / BOARDERLESS T450",
	 "group": "TEMPERED GLASS", "hsn": "70071900",
	 "barcode": "715855130919", "price": 450.0, "qty": 2006},
	{"code": "P 150", "name": "POUCH - 150 P150", "group": "PHONE POUCH",
	 "hsn": "42029900", "barcode": "822408317957", "price": 150.0, "qty": 2253},
	{"code": "P 200", "name": "POUCH - 200 P200", "group": "PHONE POUCH",
	 "hsn": "42029900", "barcode": "570784062257", "price": 200.0, "qty": 776},
	{"code": "P 250-2", "name": "POUCH - 250 P250", "group": "PHONE POUCH",
	 "hsn": "42029900", "barcode": "577083163805", "price": 250.0, "qty": 3035},
)


def execute():
	if not frappe.db.exists("Warehouse", WAREHOUSE):
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	price_list = frappe.db.get_value(
		"Branch Profile", {"branch": BRANCH}, "default_price_list") or "Standard Selling"

	named = []
	for row in ITEMS:
		if frappe.db.exists("Item", row["code"]):
			_describe(row, price_list)
			named.append(row["code"])

	frappe.db.commit()
	print(f"Accessories PSLA short codes: {len(named)} item(s) named and priced")
	print("  no stock posted — these need their duplicates settled first:")
	for line in _pairs():
		print(f"    {line}")


def _describe(row, price_list) -> None:
	"""The name a counter will search for, the heading, the price."""
	doc = frappe.get_doc("Item", row["code"])
	doc.item_name = row["name"]
	if frappe.db.exists("Item Group", row["group"]):
		doc.item_group = row["group"]
	if doc.meta.has_field("gst_hsn_code") and not doc.gst_hsn_code \
			and frappe.db.exists("GST HSN Code", row["hsn"]):
		doc.gst_hsn_code = row["hsn"]
	if row["barcode"] and not any(b.barcode == row["barcode"] for b in doc.barcodes) \
			and not frappe.db.exists("Item Barcode", {"barcode": row["barcode"]}):
		doc.append("barcodes", {"barcode": row["barcode"]})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	if flt(row["price"]) > 0 and not frappe.db.exists(
			"Item Price", {"item_code": doc.name, "price_list": price_list}):
		price = frappe.new_doc("Item Price")
		price.item_code = doc.name
		price.price_list = price_list
		price.price_list_rate = flt(row["price"])
		price.flags.ignore_permissions = True
		price.insert(ignore_permissions=True)


def _pairs() -> list[str]:
	"""Each line as it stands: what the sheet said, and where the stock is."""
	out = []
	for row in ITEMS:
		if not frappe.db.exists("Item", row["code"]):
			continue
		here = flt(frappe.db.get_value(
			"Bin", {"item_code": row["code"], "warehouse": WAREHOUSE}, "actual_qty"))
		twin = f"{row['code']}-2"
		has_twin = frappe.db.exists("Item", twin)
		there = flt(frappe.db.get_value(
			"Bin", {"item_code": twin, "warehouse": WAREHOUSE}, "actual_qty")) \
			if has_twin else 0
		note = f"{row['code']} holds {here:g}"
		if has_twin:
			note += f", {twin} holds {there:g}, together {here + there:g}"
		note += f" — the sheet counted {flt(row['qty']):g}"
		out.append(note)
	return out
