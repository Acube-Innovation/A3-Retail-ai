# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The accessories shelf at UK, counted on 6 November 2026 and put on the books.

566 lines off myBillBook's own stock summary for the branch — cables, cases,
chargers, buds, power banks and watches. Most of them are already in the
catalogue: the branch's items were created in August from an earlier pull of
the same business, and three opening counts were posted that day and then
cancelled, which is why the shelf shows bins with nothing in them. This is the
count that replaces them.

A patch rather than an import because the counter cannot reach the server, and
Frappe runs each patch once per site and records it, so a later deploy passes
straight over this. It is written to be safe if it is ever run again by hand:
an item already on file is left exactly as it is, and a line is counted in only
where the branch holds none of it and none has ever been opened there.

Three things about the sheet shaped what is here.

COST. Its Purchase Price column is zero on 571 of 575 rows, so what the shelf
cost is simply not in the file. Each line is valued at what the shop charges
for it, which is the only figure available and is certainly high: it puts the
shelf on the books at about Rs 47.8 lakh and leaves no margin on the first sale
of each line. Where the site already knows a real buying rate, that is used
instead. COST_RATIO below scales the rest — set it to 0.7 and re-run before the
deploy if the shop gives a margin, or correct the valuation on the
reconciliations this patch creates afterwards.

NEGATIVES. 72 lines are below zero, 4,836 pieces in all — myBillBook billing
stock out that was never billed in. A shelf cannot hold minus eleven chargers,
so those are catalogued and left uncounted for the branch to find and fix. They
are listed by name when this runs.

NAMES. The sheet repeats seven names at different prices — SKIN at 150, 200 and
250, HYTROGEL at 350, 550 and 650 — which is one shelf label over several
products. Those are added up into one line each, valued at the
quantity-weighted price, because splitting them needs somebody who can see the
shelf. They are listed when this runs too.

Matching is deliberately forgiving about spacing, and that is load-bearing: 69
lines differ from the catalogue only by a double space, and four more are the
short codes the two shops write differently — this sheet's "T 150" and "P 200"
are the catalogue's T150 and P200, the tempered glass and the pouch Accessories
PSLA already sells. Flattening a name only settles it where exactly one item
answers to it, because the migration left twins (AIRPODS 700 and AIRPODS 700-2)
that flatten alike and choosing between those is the shop's call, not a
patch's. 547 of the 566 lines land on an item the branch already has;
19 are new.

One consequence worth knowing. 253 of these lines carry a barcode that already
belongs to a different item — the same product catalogued again for Accessories
PSLA, under the fuller name on the box. A barcode can only live on one item in
ERPNext, so the stock goes on the item this branch sells under the name the
branch uses, and scanning that box at UK will still find the PSLA record. That
is a catalogue merge, not a stock count, and is left alone here.
"""

import json
import os
import re

import frappe
from frappe.utils import flt, getdate, nowdate

BRANCH = "PhoneXpert Accessories UK"
WAREHOUSE = "PhoneXpert Accessories UK - PT"
NOTE = "Opening stock — accessories counted at UK on 6 November 2026"

#: The date the shop took the count. Posted at midnight, so the shelf is
#: already there before anything sold that day.
COUNTED_ON = "2026-11-06"

#: What the shelf cost the shop, as a fraction of what it sells for. 1.0 values
#: the stock at retail — high, but the only figure the sheet gives. A real
#: buying rate already on the item always wins over this.
COST_RATIO = 1.0

#: ERPNext hands a reconciliation of more than a hundred lines to a background
#: worker and leaves the document in draft until that worker gets to it. A patch
#: runs during a deploy, where nothing is listening, so the shelf is counted in
#: batches small enough to post there and then.
BATCH = 100

#: GST Settings refuses to save an item without an HSN code. A new line takes
#: the code its own category already uses; this is for the handful whose
#: category is blank or new, and the rate on them is the accountant's call.
FALLBACK_HSN = "85177090"


def execute():
	if not frappe.db.exists("Warehouse", WAREHOUSE):
		# Another site, or the branch renamed. Nothing to do and nothing to say.
		return

	shelf = _data()
	if not shelf:
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	price_list = frappe.db.get_value(
		"Branch Profile", {"branch": BRANCH}, "default_price_list") or "Standard Selling"

	loose, tight = _index()
	made, matched = [], {}
	for row in shelf:
		item = _resolve(row, loose, tight)
		if not item:
			item = _create(row, price_list)
			loose[_norm(row["name"])] = item
			made.append(item)
		matched[row["name"]] = item

	posted, counted, value = _open_stock(shelf, matched, company)

	frappe.db.commit()
	print(f"Accessories UK: {len(made)} item(s) created, "
	      f"{len(shelf) - len(made)} already on file")
	print(f"  counted in: {counted} line(s), valued at Rs {value:,.0f}")
	print(f"  opening stock: {posted or 'already posted, left alone'}")
	_report(shelf)


def _report(shelf: list[dict]) -> None:
	"""The lines somebody has to look at, said out loud rather than buried."""
	short = [r["name"] for r in shelf if flt(r.get("qty")) < 0]
	if short:
		print(f"  {len(short)} line(s) below zero on the sheet, left uncounted: "
		      + ", ".join(sorted(short)[:8])
		      + (" …" if len(short) > 8 else ""))
	doubled = [r["name"] for r in shelf if r.get("merged")]
	if doubled:
		print(f"  {len(doubled)} name(s) the sheet held twice, added up: "
		      + ", ".join(sorted(doubled)))


def _data() -> list[dict]:
	path = os.path.join(os.path.dirname(__file__), "data",
	                    "accessories_uk_stock.json")
	if not os.path.exists(path):
		return []
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def _norm(name: str) -> str:
	"""One spelling of a name, so spacing alone never makes a second item.

	The sheet writes "AMAQ    20W PD" where the catalogue holds "AMAQ 20W PD".
	Matching on the exact string would have made 69 duplicates of items this
	branch already sells.
	"""
	return re.sub(r"\s+", " ", (name or "")).strip().upper()


def _tight(name: str) -> str:
	"""The same name with every space and mark taken out.

	For the short codes the two shops write differently: this sheet says
	"T 150" and "P 200" where the catalogue holds T150 and P200 — the tempered
	glass and the pouch the other branch already sells. Only used where exactly
	one item answers to the flattened key, because the migration left a good
	many twins (AIRPODS 700 and AIRPODS 700-2) that flatten to the same thing
	and picking between those is the shop's call.
	"""
	return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _index() -> tuple[dict[str, str], dict[str, str]]:
	"""Every item on file, by name and by code — read once, not 566 times.

	Two indexes: the ordinary one, and the flattened one with its ambiguous
	keys dropped.
	"""
	loose: dict[str, str] = {}
	tight: dict[str, str] = {}
	clashed: set[str] = set()
	for item in frappe.get_all("Item", fields=["name", "item_name"], limit=0):
		for key in (_norm(item.item_name), _norm(item.name)):
			loose.setdefault(key, item.name)
		for key in (_tight(item.item_name), _tight(item.name)):
			if not key:
				continue
			if tight.setdefault(key, item.name) != item.name:
				clashed.add(key)
	for key in clashed:
		tight.pop(key, None)
	return loose, tight


def _resolve(row: dict, loose: dict[str, str], tight: dict[str, str]) -> str | None:
	"""The item this line belongs to, if the site already has it.

	Name first: these are the records this branch was given in August and has
	been selling from, and they carry its prices. Then the barcode, for a line
	the branch never had its own record for. Then the flattened name, which is
	only ever the short codes.
	"""
	found = loose.get(_norm(row["name"]))
	if found:
		return found
	if row.get("code"):
		found = frappe.db.get_value("Item Barcode", {"barcode": row["code"]}, "parent")
		if found:
			return found
	return tight.get(_tight(row["name"]))


def _create(row: dict, price_list: str) -> str:
	group = _group(row.get("cat"))
	doc = frappe.new_doc("Item")
	doc.item_code = row["name"][:140]
	doc.item_name = row["name"][:140]
	doc.item_group = group
	doc.stock_uom = "Nos"
	doc.is_stock_item = 1
	doc.is_purchase_item = 1
	doc.is_sales_item = 1
	doc.has_serial_no = 0
	if doc.meta.has_field("gst_hsn_code"):
		doc.gst_hsn_code = _hsn(group)
	if row.get("code") and not frappe.db.exists("Item Barcode", {"barcode": row["code"]}):
		doc.append("barcodes", {"barcode": row["code"]})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	sell = flt(row.get("sell")) or flt(row.get("mrp"))
	if sell > 0 and not frappe.db.exists(
			"Item Price", {"item_code": doc.name, "price_list": price_list}):
		price = frappe.new_doc("Item Price")
		price.item_code = doc.name
		price.price_list = price_list
		price.price_list_rate = sell
		price.flags.ignore_permissions = True
		price.insert(ignore_permissions=True)

	return doc.name


def _group(category: str | None) -> str:
	"""The shop's own shelf label, kept as the item group it already is.

	48 of the 50 labels on this sheet are groups on the site already; the two
	that are not are made rather than swept into Uncategorised, because the
	group is how the counter finds anything on the Sell screen.
	"""
	name = (category or "").strip()
	if not name:
		return "Uncategorised" if frappe.db.exists("Item Group", "Uncategorised") \
			else _root_group()
	if frappe.db.exists("Item Group", name):
		return name
	doc = frappe.new_doc("Item Group")
	doc.item_group_name = name
	doc.parent_item_group = _root_group()
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _root_group() -> str:
	return frappe.db.get_value(
		"Item Group", {"is_group": 1, "parent_item_group": ""}, "name") \
		or "All Item Groups"


def _hsn(group: str) -> str:
	"""The code this group's own items already carry.

	An HSN is a tax answer, not a guess worth inventing: the siblings on the
	shelf were coded by somebody who knew, so a new line takes the commonest
	code among them.
	"""
	cached = _hsn.cache.get(group)
	if cached:
		return cached
	found = frappe.db.sql(
		"""select gst_hsn_code from tabItem
		   where item_group = %s and ifnull(gst_hsn_code, '') <> ''
		   group by gst_hsn_code order by count(*) desc limit 1""", group)
	code = (found[0][0] if found else "") or FALLBACK_HSN
	if not frappe.db.exists("GST HSN Code", code):
		code = FALLBACK_HSN if frappe.db.exists("GST HSN Code", FALLBACK_HSN) else ""
	_hsn.cache[group] = code
	return code


_hsn.cache = {}


def _rate(item: str, row: dict) -> float:
	"""What one piece is worth, for the ledger.

	A buying rate the site already holds is a real figure from a real purchase
	and always wins. Everything else falls back to what the shop sells it for,
	scaled by COST_RATIO.
	"""
	bought = frappe.db.get_value(
		"Item Price", {"item_code": item, "price_list": "Standard Buying", "buying": 1},
		"price_list_rate")
	if flt(bought) > 0:
		return flt(bought)
	sell = flt(row.get("sell")) or flt(row.get("mrp"))
	return flt(sell * COST_RATIO, 2)


def _open_stock(shelf: list[dict], matched: dict[str, str],
                company: str) -> tuple[str | None, int, float]:
	"""One count for the shelf, in batches, for the lines that still need it.

	A reconciliation *sets* a figure rather than adding to it, so a line is
	counted in only where the branch holds none of it and none has ever been
	opened in this store. The three August counts were cancelled, which leaves
	them out of that test — cancelled stock is not stock. Stock Reconciliation
	carries no remarks field to leave a marker in, so the ledger itself is the
	record, which is sturdier than a marker anyway.
	"""
	lines = []
	for row in shelf:
		qty = flt(row.get("qty"))
		item = matched.get(row["name"])
		if qty <= 0 or not item:
			continue
		rate = _rate(item, row)
		if rate <= 0:
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
		return None, 0, 0.0

	abbr = frappe.get_cached_value("Company", company, "abbr")
	# An opening entry books the other side against an asset account, not an
	# expense — ERPNext refuses the document otherwise.
	account = f"Temporary Opening - {abbr}"
	if not frappe.db.exists("Account", account):
		account = f"Stock Adjustment - {abbr}"

	posted = getdate(COUNTED_ON)
	if posted > getdate(nowdate()):
		# A site whose clock is behind the count: post it today instead of
		# asking ERPNext to accept a date that has not happened.
		posted = getdate(nowdate())

	made = []
	for start in range(0, len(lines), BATCH):
		reco = frappe.new_doc("Stock Reconciliation")
		reco.company = company
		reco.posting_date = posted
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
				f"{reco.name} did not submit — the shelf has not been counted in.")
		reco.add_comment("Comment", NOTE)
		made.append(reco.name)

	value = sum(line["qty"] * line["valuation_rate"] for line in lines)
	return ", ".join(made), len(lines), value
