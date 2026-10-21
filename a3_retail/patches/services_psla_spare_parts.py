# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The spare parts drawer at Services PSLA, catalogued and counted.

491 displays, batteries, buttons, ports and flexes off the bench's own parts
sheet, with what each cost, what it is charged at, and how many are in the
drawer. They go into the Spare Parts group, which is where the job card's parts
picker looks, so a technician can put one on a repair the moment this lands.

A patch rather than an import because the bench cannot reach the server, and
Frappe runs each patch once per site and records it, so a later deploy passes
straight over this. It is written to be safe if it is ever run again by hand:
a part already on file is left exactly as it is, and a count is posted only
where the branch holds none and none has ever been opened there.

Two things about the sheet are worth knowing, because they shaped what is here.
Its HSN column drifted in the later rows and holds rack labels — "INNER 3",
"SERVICE 1" — rather than codes, so only a real code was taken and the rest
fall to 85076000 for a battery and 85177010 for everything else. That is the
usual pair for mobile spares, but the rate charged on them is the accountant's
call. And 96 of the parts have no price on the sheet; they are catalogued so a
technician can find them, with the price left at nothing to be filled in.
"""

import json
import os

import frappe
from frappe.utils import flt, getdate, nowdate

BRANCH = "PhoneXpert Services PSLA"
WAREHOUSE = "PhoneXpert Services PSLA - PT"
GROUP = "Spare Parts"
NOTE = "Opening stock — spare parts drawer counted at Services PSLA"


def execute():
	if not frappe.db.exists("Warehouse", WAREHOUSE):
		# Another site, or the branch renamed. Nothing to do and nothing to say.
		return

	parts = _data()
	if not parts:
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	price_list = frappe.db.get_value(
		"Branch Profile", {"branch": BRANCH}, "default_price_list") or "Standard Selling"
	_ensure_group()

	made = already = 0
	for row in parts:
		if _existing(row["name"]):
			already += 1
			continue
		_create(row, company, price_list)
		made += 1

	posted = _open_stock(parts, company)

	frappe.db.commit()
	print(f"Services PSLA spare parts: {made} created, {already} already on file")
	print(f"  opening stock: {posted or 'already posted, left alone'}")


def _data() -> list[dict]:
	path = os.path.join(os.path.dirname(__file__), "data",
	                    "services_psla_spare_parts.json")
	if not os.path.exists(path):
		return []
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def _ensure_group() -> None:
	"""The group the job card's parts picker reads."""
	if frappe.db.exists("Item Group", GROUP):
		return
	parent = frappe.db.get_value(
		"Item Group", {"is_group": 1, "parent_item_group": ""}, "name") \
		or "All Item Groups"
	doc = frappe.new_doc("Item Group")
	doc.item_group_name = GROUP
	doc.parent_item_group = parent
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)


def _existing(name: str) -> str | None:
	return frappe.db.get_value("Item", {"item_name": name}, "name")


def _create(row: dict, company: str, price_list: str) -> str:
	doc = frappe.new_doc("Item")
	doc.item_code = row["name"]
	doc.item_name = row["name"]
	doc.item_group = GROUP
	doc.stock_uom = "Nos"
	doc.is_stock_item = 1
	doc.is_purchase_item = 1
	doc.is_sales_item = 1
	doc.has_serial_no = 0
	if row.get("hsn") and doc.meta.has_field("gst_hsn_code") \
			and frappe.db.exists("GST HSN Code", row["hsn"]):
		doc.gst_hsn_code = row["hsn"]
	# What it fits and where it lives, which is what the bench actually asks.
	about = " · ".join(p for p in (
		row.get("type"),
		f"fits {row['fits']}" if row.get("fits") else "",
		f"kept in {row['loc']}" if row.get("loc") else "") if p)
	if about:
		doc.description = about[:500]
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	if flt(row.get("price")) > 0 and not frappe.db.exists(
			"Item Price", {"item_code": doc.name, "price_list": price_list}):
		price = frappe.new_doc("Item Price")
		price.item_code = doc.name
		price.price_list = price_list
		price.price_list_rate = flt(row["price"])
		price.flags.ignore_permissions = True
		price.insert(ignore_permissions=True)

	if flt(row.get("cost")) > 0 and doc.meta.has_field("last_purchase_rate"):
		frappe.db.set_value("Item", doc.name, "last_purchase_rate",
		                    flt(row["cost"]), update_modified=False)
	return doc.name


# ERPNext hands a reconciliation of more than a hundred lines to a background
# worker and leaves the document in draft until that worker gets to it. A patch
# runs during a deploy, where nothing is listening, so the drawer is counted in
# batches small enough to post there and then.
BATCH = 100


def _open_stock(parts: list[dict], company: str) -> str | None:
	"""One reconciliation for the drawer, for the lines that still need it.

	A reconciliation sets a figure rather than adding to it, so a line is only
	counted in where the branch holds none of it and none has ever been opened
	in this store. Stock Reconciliation carries no remarks field to leave a
	marker in, so the ledger itself is the record.
	"""
	lines = []
	for row in parts:
		qty = flt(row.get("qty"))
		rate = flt(row.get("cost")) or flt(row.get("price"))
		if qty <= 0 or rate <= 0:
			continue
		item = _existing(row["name"])
		if not item:
			continue
		if flt(frappe.db.get_value(
				"Bin", {"item_code": item, "warehouse": WAREHOUSE}, "actual_qty")):
			continue
		if frappe.db.exists("Stock Reconciliation Item",
		                    {"item_code": item, "warehouse": WAREHOUSE,
		                     "docstatus": 1}):
			continue
		lines.append({"item_code": item, "warehouse": WAREHOUSE,
		              "qty": qty, "valuation_rate": rate})

	if not lines:
		return None

	abbr = frappe.get_cached_value("Company", company, "abbr")
	# An opening entry books the other side against an asset account, not an
	# expense — ERPNext refuses the document otherwise.
	account = f"Temporary Opening - {abbr}"
	if not frappe.db.exists("Account", account):
		account = f"Stock Adjustment - {abbr}"

	made = []
	for start in range(0, len(lines), BATCH):
		reco = frappe.new_doc("Stock Reconciliation")
		reco.company = company
		reco.posting_date = getdate(nowdate())
		reco.set_posting_time = 1
		reco.purpose = "Opening Stock"
		reco.expense_account = account
		reco.set_warehouse = WAREHOUSE
		if reco.meta.has_field("branch"):
			reco.branch = BRANCH
		for line in lines[start:start + BATCH]:
			reco.append("items", line)
		reco.flags.ignore_permissions = True
		reco.insert(ignore_permissions=True)
		reco.submit()
		if reco.docstatus != 1:
			# Never leave a draft behind pretending the stock is on the shelf.
			frappe.throw(
				f"{reco.name} did not submit — the drawer has not been counted in.")
		reco.add_comment("Comment", NOTE)
		made.append(reco.name)

	return ", ".join(made)
