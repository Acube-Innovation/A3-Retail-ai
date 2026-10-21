# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The accessories shelf at PSLA, counted and put on the books.

Ten lines of tempered glass, pouches and flip cases that the branch sells and
the catalogue did not have. They came off the shop's own stock sheet; the other
eight lines on that sheet were already on file under short codes (T100, P 150
and the rest) and are deliberately not here — adding them again would give two
items for one product with the stock split between them.

A patch rather than an import because the counter cannot reach the server, and
Frappe runs each patch once per site and records it, so a later deploy passes
straight over this. It is written to be safe even if it is run again by hand:
an item already on file is left exactly as it is, and the opening count is
posted only if this branch has never had one from here.

COST: the shop did not give what these cost, so the opening stock is valued at
what it sells for. That overstates what the shelf is worth and leaves no margin
on the first sale of each. Put the real figures in COSTS below — before the
deploy if you can, afterwards by editing the valuation on the reconciliation
this patch creates.
"""

import frappe
from frappe.utils import flt, getdate, nowdate

BRANCH = "PhoneXpert Accessories PSLA"
WAREHOUSE = "PhoneXpert Accessories PSLA - PT"
NOTE = "Opening stock — accessories counted at PSLA"

# What each costs the shop, before tax. Anything left out is valued at its
# selling price, which is the best guess available and almost certainly high.
COSTS: dict[str, float] = {
	# "FLIPCASE - 250": 120,
}

ITEMS = (
	{"name": "TEMPERED - 250 FINGER READING", "code": "129214409095",
	 "group": "TEMPERED GLASS", "hsn": "70071900", "sell": 250, "qty": 700},
	{"name": "PREMIUM UV CURVED GLASS", "code": "544319371244",
	 "group": "TEMPERED GLASS", "hsn": "70071900", "sell": 800, "qty": 888},
	{"name": "PREMIUM FULL GLUE CURVED GLASS", "code": "88722174910",
	 "group": "TEMPERED GLASS", "hsn": "70071900", "sell": 800, "qty": 200},
	{"name": "POUCH - 350 PREMIUM SILICONE P350", "code": "436900221996",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 350, "qty": 289},
	{"name": "POUCH - 450 MAGSAFE TYPE P450", "code": "64058275942",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 450, "qty": 106},
	{"name": "POUCH - 350 TRANSPARENT PT350", "code": "702014642275",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 350, "qty": 23},
	{"name": "POUCH - 450 TRANSPARENT MAGSAFE PT450", "code": "437093374342",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 450, "qty": 40},
	{"name": "FLIPCASE - 250", "code": "179740841502",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 250, "qty": 204},
	{"name": "FLIPCASE - 300", "code": "573706774994",
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 300, "qty": 555},
	{"name": "FLIPCASE - 450", "code": None,
	 "group": "PHONE POUCH", "hsn": "42029900", "sell": 450, "qty": 10},
)


def execute():
	if not frappe.db.exists("Warehouse", WAREHOUSE):
		# Another site, or the branch renamed. Nothing to do and nothing to say.
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	price_list = frappe.db.get_value(
		"Branch Profile", {"branch": BRANCH}, "default_price_list") or "Standard Selling"

	made, already = [], []
	for row in ITEMS:
		name = _existing(row)
		if name:
			already.append(name)
			continue
		made.append(_create(row, company, price_list))

	posted = _open_stock(company)

	frappe.db.commit()
	print(f"Accessories PSLA: {len(made)} item(s) created, "
	      f"{len(already)} already on file")
	print(f"  opening stock: {posted or 'already posted, left alone'}")


def _existing(row) -> str | None:
	"""The item this row would duplicate, if the site already has it."""
	by_name = frappe.db.get_value("Item", {"item_name": row["name"]}, "name")
	if by_name:
		return by_name
	if row["code"]:
		return frappe.db.get_value("Item Barcode", {"barcode": row["code"]}, "parent")
	return None


def _create(row, company: str, price_list: str) -> str:
	doc = frappe.new_doc("Item")
	doc.item_code = row["name"]
	doc.item_name = row["name"]
	doc.item_group = row["group"] if frappe.db.exists("Item Group", row["group"]) \
		else "Uncategorised"
	doc.stock_uom = "Nos"
	doc.is_stock_item = 1
	doc.is_purchase_item = 1
	doc.is_sales_item = 1
	doc.has_serial_no = 0
	if doc.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", row["hsn"]):
		doc.gst_hsn_code = row["hsn"]
	if row["code"] and not frappe.db.exists("Item Barcode", {"barcode": row["code"]}):
		doc.append("barcodes", {"barcode": row["code"]})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	if flt(row["sell"]) > 0 and not frappe.db.exists(
			"Item Price", {"item_code": doc.name, "price_list": price_list}):
		price = frappe.new_doc("Item Price")
		price.item_code = doc.name
		price.price_list = price_list
		price.price_list_rate = flt(row["sell"])
		price.flags.ignore_permissions = True
		price.insert(ignore_permissions=True)

	return doc.name


def _open_stock(company: str) -> str | None:
	"""One reconciliation for the whole shelf, for the lines that still need it.

	Two things are asked of every line before it is counted in, because a
	reconciliation *sets* a figure rather than adding to it and getting that
	wrong twice would be silent: the branch must not already hold any, and this
	item must never have been opened in this store before. Stock Reconciliation
	carries no remarks field to leave a marker in, so the ledger itself is the
	record — which is sturdier than a marker anyway.
	"""
	lines = []
	for row in ITEMS:
		item = _existing(row)
		if not item or flt(row["qty"]) <= 0:
			continue
		held = frappe.db.get_value(
			"Bin", {"item_code": item, "warehouse": WAREHOUSE}, "actual_qty")
		if flt(held):
			continue
		if frappe.db.exists("Stock Reconciliation Item",
		                    {"item_code": item, "warehouse": WAREHOUSE,
		                     "docstatus": 1}):
			continue
		rate = flt(COSTS.get(row["name"])) or flt(row["sell"])
		if rate <= 0:
			continue
		lines.append({"item_code": item, "warehouse": WAREHOUSE,
		              "qty": flt(row["qty"]), "valuation_rate": rate})

	if not lines:
		return None

	abbr = frappe.get_cached_value("Company", company, "abbr")
	# An opening entry books the other side against an asset account, not an
	# expense — ERPNext refuses the document otherwise.
	account = f"Temporary Opening - {abbr}"
	if not frappe.db.exists("Account", account):
		account = f"Stock Adjustment - {abbr}"

	reco = frappe.new_doc("Stock Reconciliation")
	reco.company = company
	reco.posting_date = getdate(nowdate())
	reco.set_posting_time = 1
	reco.purpose = "Opening Stock"
	reco.expense_account = account
	reco.set_warehouse = WAREHOUSE
	if reco.meta.has_field("branch"):
		reco.branch = BRANCH
	for line in lines:
		reco.append("items", line)
	reco.flags.ignore_permissions = True
	reco.insert(ignore_permissions=True)
	reco.submit()
	# Why it exists, where somebody looking at it will actually read it.
	reco.add_comment("Comment", NOTE)
	return reco.name
