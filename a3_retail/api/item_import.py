# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Bringing a catalogue in from a spreadsheet (`/retail/stock`).

A shop that is changing systems, or taking on a new brand, has its items in a
spreadsheet — a file from the distributor, or a sheet the owner keeps. Typing
four hundred of them into a form one at a time is how a migration stalls.

The rule here is that nothing is written until the person has seen what would
happen. The file is read, every row is checked against the same rules the New
Item form uses, and the result comes back as a list: these are ready, these have
problems, and here is what is wrong with each one. Only then does anything post,
and only the rows that passed — a bad row holds up itself and nothing else,
because a delivery of four hundred items will always have a few.

The items themselves are made by `stock_control.create_item`, not here. One way
into the catalogue, so an item typed at the counter and an item imported from a
sheet are the same kind of record.
"""

import re
from urllib.parse import parse_qs, urlparse

import frappe
from frappe import _
from frappe.utils import cint, flt

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

#: More than this in one go is a job for head office, not a counter.
ROW_LIMIT = 2000

#: What a column may be called. The shop's own sheets say "Model" and the
#: distributor's say "Description"; both mean the name on the shelf.
COLUMNS = (
	{
		"field": "item_type",
		"label": "Item Type",
		"help": "Product for anything counted on a shelf, Service for labour",
		"example": "Product",
		"aliases": ("item type", "type", "kind", "product or service", "goods or service"),
	},
	{
		"field": "item_name",
		"label": "Item Name",
		"required": True,
		"help": "What it is called on the shelf",
		"example": "REDMI 13C 5G STARLIGHT BLACK 4/128",
		"aliases": ("item name", "name", "item", "product", "product name",
		            "description", "model", "item description"),
	},
	{
		"field": "item_code",
		"label": "Item Code",
		"help": "The barcode on the box. Left blank, the name is used",
		"example": "8906129036208",
		"aliases": ("item code", "code", "sku", "sku code", "barcode",
		            "bar code", "ean", "part number", "part no"),
	},
	{
		"field": "item_group",
		"label": "Category",
		"help": "Must be one of the categories on the Reference sheet",
		"example": "REDMI",
		"aliases": ("category", "item group", "group", "item category", "type"),
	},
	{
		"field": "brand",
		"label": "Brand",
		"help": "Optional",
		"example": "REDMI",
		"aliases": ("brand", "make", "manufacturer", "company"),
	},
	{
		"field": "hsn_code",
		"label": "HSN Code",
		"help": "4, 6 or 8 digits",
		"example": "85171300",
		"aliases": ("hsn code", "hsn", "hsn/sac", "hsn sac", "sac", "identification code"),
	},
	{
		"field": "uom",
		"label": "Unit",
		"help": "Pieces unless the shop sells it another way",
		"example": "Nos",
		"aliases": ("unit", "uom", "measuring unit", "unit of measure", "units"),
	},
	{
		"field": "purchase_rate",
		"label": "Purchase Price",
		"help": "What it costs, before tax",
		"example": "9200",
		"aliases": ("purchase price", "purchase rate", "cost", "cost price",
		            "buying price", "rate", "purchase"),
	},
	{
		"field": "selling_rate",
		"label": "Sales Price",
		"help": "What the shop asks for it, tax included",
		"example": "11999",
		"aliases": ("sales price", "selling price", "sale price", "mrp", "price",
		            "retail price", "sales rate", "selling rate"),
	},
	{
		"field": "opening_qty",
		"label": "Opening Stock",
		"help": "How many are on the shelf now. Leave blank if none",
		"example": "6",
		"aliases": ("opening stock", "opening qty", "opening quantity", "qty",
		            "quantity", "stock", "stock qty", "available qty", "balance"),
	},
	{
		"field": "has_serial",
		"label": "Has IMEI",
		"help": "Yes for handsets that carry an IMEI, otherwise No",
		"example": "Yes",
		"aliases": ("has imei", "imei", "serialised", "serialized", "serial",
		            "has serial", "imei enabled", "serial number"),
	},
	{
		"field": "reorder_level",
		"label": "Low Stock Alert",
		"help": "Warn when the count falls below this. Optional",
		"example": "3",
		"aliases": ("low stock alert", "reorder level", "reorder", "minimum stock",
		            "min qty", "safety stock", "low stock"),
	},
)

TRUE_WORDS = {"yes", "y", "true", "1", "serialised", "serialized", "imei"}
FALSE_WORDS = {"no", "n", "false", "0", "", "-", "none"}


def _norm(value) -> str:
	"""A header reduced to the letters and digits in it, lowercased."""
	return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------
def _rows_from_file(file_url: str) -> list[list]:
	"""Whatever the person attached, as a list of rows."""
	doc = frappe.get_doc("File", {"file_url": file_url})
	name = (doc.file_name or file_url).lower()
	content = doc.get_content()

	if name.endswith(".xlsx"):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

		return read_xlsx_file_from_attached_file(fcontent=content)
	if name.endswith(".xls"):
		from frappe.utils.xlsxutils import read_xls_file_from_attached_file

		return read_xls_file_from_attached_file(content)
	if name.endswith((".csv", ".txt", ".tsv")):
		from frappe.utils.csvutils import read_csv_content

		return read_csv_content(content)

	frappe.throw(
		_("That file type cannot be read. Save the sheet as .xlsx or .csv and attach it again."),
		title=_("Wrong kind of file"),
	)


def _rows_from_sheet(sheet_url: str) -> list[list]:
	"""A Google Sheet, read through its own CSV export.

	Only Google's own address is ever fetched, and only over https: this runs on
	the server, so a URL typed into the box must not be able to make it open
	something on the inside of the network.
	"""
	parsed = urlparse((sheet_url or "").strip())
	if parsed.scheme != "https" or parsed.netloc.lower() != "docs.google.com":
		frappe.throw(
			_("Paste the address of a Google Sheet — it should begin "
			  "https://docs.google.com/spreadsheets/."),
			title=_("Not a Google Sheet"),
		)
	match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", parsed.path)
	if not match:
		frappe.throw(_("That address has no sheet in it."), title=_("Not a Google Sheet"))

	gid = (parse_qs(parsed.fragment).get("gid") or parse_qs(parsed.query).get("gid") or ["0"])[0]
	export = (f"https://docs.google.com/spreadsheets/d/{match.group(1)}"
	          f"/export?format=csv&gid={re.sub(r'[^0-9]', '', gid) or '0'}")

	import requests

	try:
		answer = requests.get(export, timeout=30)
	except Exception:
		frappe.throw(_("Could not reach Google to read that sheet."), title=_("No answer"))

	if answer.status_code != 200 or answer.content.lstrip()[:1] == b"<":
		# Google hands back its sign-in page rather than a refusal.
		frappe.throw(
			_("That sheet is not readable. In Google Sheets choose Share → General access → "
			  "Anyone with the link, then paste the address again."),
			title=_("Sheet is private"),
		)

	from frappe.utils.csvutils import read_csv_content

	return read_csv_content(answer.content)


def _read(file_url: str | None, sheet_url: str | None) -> list[list]:
	if sheet_url:
		rows = _rows_from_sheet(sheet_url)
	elif file_url:
		rows = _rows_from_file(file_url)
	else:
		frappe.throw(_("Attach a file or paste a Google Sheet address."), title=_("Nothing to read"))

	rows = [row for row in (rows or []) if any(str(cell or "").strip() for cell in row)]
	if not rows:
		frappe.throw(_("That sheet is empty."), title=_("Nothing in it"))
	if len(rows) - 1 > ROW_LIMIT:
		frappe.throw(
			_("That sheet has more than {0} items. Split it and bring it in a few thousand "
			  "at a time.").format(ROW_LIMIT),
			title=_("Too much at once"),
		)
	return rows


# ---------------------------------------------------------------------------
# Working out which column is which
# ---------------------------------------------------------------------------
def _map_columns(header: list) -> tuple[dict, list]:
	"""Match the sheet's headings to the fields, and say what was ignored.

	Nobody relabels their columns to suit us. A heading is matched on the
	letters in it, so "Sales Price", "sales price" and "SALES  PRICE." are the
	same heading, and the common other names for each are accepted too.
	"""
	taken: dict[str, int] = {}
	unknown = []
	for index, cell in enumerate(header):
		name = _norm(cell)
		if not name:
			continue
		for column in COLUMNS:
			if column["field"] in taken:
				continue
			if name == _norm(column["label"]) or name in column["aliases"]:
				taken[column["field"]] = index
				break
		else:
			unknown.append(str(cell).strip())
	return taken, unknown


def _cell(row: list, mapping: dict, field: str) -> str:
	index = mapping.get(field)
	if index is None or index >= len(row):
		return ""
	return str(row[index] if row[index] is not None else "").strip()


def _truthy(value: str, default: int = 0) -> int | None:
	word = value.strip().lower()
	if word in TRUE_WORDS:
		return 1
	if word in FALSE_WORDS:
		return default
	return None


def _number(value: str):
	"""A figure as a sheet writes it: 1,299.00 or ₹1299 or 1299.

	An empty cell is nothing, which is a legitimate answer. A cell with
	something in it that is not a figure is a mistake, and saying so beats
	quietly importing the item priced at zero.
	"""
	raw = (value or "").strip()
	if not raw:
		return 0.0
	cleaned = re.sub(r"[^0-9.\-]", "", raw)
	if not cleaned or cleaned.strip("-.") == "":
		return None
	try:
		return float(cleaned)
	except ValueError:
		return None


# ---------------------------------------------------------------------------
# Checking, without writing anything
# ---------------------------------------------------------------------------
def _known() -> dict:
	"""The lists a row is checked against, read once rather than per row."""
	return {
		"groups": {_norm(g): g for g in frappe.get_all(
			"Item Group", filters={"is_group": 0}, pluck="name")},
		"brands": {_norm(b): b for b in frappe.get_all("Brand", pluck="name")},
		"uoms": {_norm(u): u for u in frappe.get_all(
			"UOM", filters={"enabled": 1}, pluck="name", limit_page_length=0)},
	}


def _check_row(row, mapping, lists, seen, needs_hsn, line_no) -> dict:
	"""One row, as the person will see it in the preview."""
	problems = []
	item = {}

	item["item_name"] = _cell(row, mapping, "item_name")
	if not item["item_name"]:
		problems.append("No item name")

	code = _cell(row, mapping, "item_code")
	item["item_code"] = code
	item["barcode"] = code
	# A sheet built by copying rows about repeats itself, and the second one
	# would otherwise be refused later as a duplicate with no hint why.
	key = _norm(code) or _norm(item["item_name"])
	if key and key in seen:
		problems.append(f"Same item as row {seen[key]} of this sheet")
	elif key:
		seen[key] = line_no

	group = _cell(row, mapping, "item_group")
	if not group:
		problems.append("No category")
	elif _norm(group) in lists["groups"]:
		item["item_group"] = lists["groups"][_norm(group)]
	else:
		problems.append(f"“{group}” is not a category on this site")

	brand = _cell(row, mapping, "brand")
	if brand and _norm(brand) in lists["brands"]:
		item["brand"] = lists["brands"][_norm(brand)]
	elif brand:
		# Not worth refusing a row over: the brand is a label, and the item is
		# still sellable without it.
		item["brand"] = ""

	unit = _cell(row, mapping, "uom") or "Nos"
	if _norm(unit) in lists["uoms"]:
		item["uom"] = lists["uoms"][_norm(unit)]
	else:
		problems.append(f"“{unit}” is not a unit on this site")

	hsn = re.sub(r"\D", "", _cell(row, mapping, "hsn_code"))
	if hsn and len(hsn) not in (4, 6, 8):
		problems.append("HSN must be 4, 6 or 8 digits")
	elif not hsn and needs_hsn:
		problems.append("No HSN code, and this site needs one to sell")
	item["hsn_code"] = hsn

	for field, label in (("purchase_rate", "Purchase price"),
	                     ("selling_rate", "Sales price"),
	                     ("opening_qty", "Opening stock"),
	                     ("reorder_level", "Low stock alert")):
		figure = _number(_cell(row, mapping, field))
		if figure is None:
			problems.append(f"{label} is not a number")
			figure = 0.0
		elif figure < 0:
			problems.append(f"{label} cannot be less than zero")
			figure = 0.0
		item[field] = figure

	# A labour charge is bought and sold but never counted, and ERPNext will not
	# let a non-stock item near a warehouse — which is exactly right.
	kind = _norm(_cell(row, mapping, "item_type"))
	if kind in ("service", "services", "labour", "labor", "charge"):
		item["is_service"] = 1
	elif kind in ("", "product", "goods", "item", "stock"):
		item["is_service"] = 0
	else:
		problems.append(f"\u201c{_cell(row, mapping, 'item_type')}\u201d is not "
		                "Product or Service")
		item["is_service"] = 0

	serial_cell = _cell(row, mapping, "has_serial")
	serial = _truthy(serial_cell)
	if serial is None:
		problems.append(f"“{serial_cell}” is not a Yes or a No for Has IMEI")
		serial = 0
	item["has_serial"] = serial

	if item["is_service"] and (serial or item["opening_qty"]):
		problems.append("A service is not counted — leave Has IMEI and Opening Stock empty")

	# A handset's own number comes in on a purchase, not here: an opening count
	# of six would need six IMEIs, and a spreadsheet column has nowhere to put
	# them.
	if serial and item["opening_qty"]:
		problems.append("An IMEI item cannot carry opening stock — bring those in on a purchase")

	if item["opening_qty"] and not item["purchase_rate"] and not item["selling_rate"]:
		problems.append("Opening stock needs a price, so the stock has a value")

	existing = None
	if item["item_name"]:
		existing = frappe.db.exists("Item", item["item_code"] or item["item_name"].upper()[:120])
	if existing:
		problems.append("Already in the catalogue")
	if code and frappe.db.exists("Item Barcode", {"barcode": code}) and not existing:
		problems.append(f"The code {code} is already on another item")

	return {"item": item, "problems": problems, "existing": bool(existing)}


def _reason(error: Exception) -> str:
	"""Why a row was refused, in the words the refusal used.

	`frappe.throw` raises with an empty exception and leaves the sentence it
	wrote in the message log, so reading only the exception gave every failed
	row the same useless "Could not be added".
	"""
	message = (str(error) or "").strip()
	if not message and frappe.message_log:
		last = frappe.message_log[-1]
		message = last.get("message", "") if isinstance(last, dict) else str(last)
	message = frappe.utils.strip_html(message or "").strip()
	return message[:300] or _("Could not be added")


def _can_open_stock() -> bool:
	"""Opening stock posts a Stock Reconciliation, which not every counter can.

	Worth knowing before the import rather than after: the items would go in and
	every opening count would be refused, four hundred times.
	"""
	return bool(frappe.has_permission("Stock Reconciliation", "create")
	            and frappe.has_permission("Stock Reconciliation", "submit"))


# ---------------------------------------------------------------------------
# What the screen calls
# ---------------------------------------------------------------------------
@frappe.whitelist()
def spec() -> dict:
	"""The columns the sheet may carry, for the screen to explain them."""
	_me()
	require_permission("Item", "create")
	return {
		"columns": [{k: v for k, v in c.items() if k != "aliases"} for c in COLUMNS],
		"row_limit": ROW_LIMIT,
		"needs_hsn": bool(frappe.db.get_single_value("GST Settings", "validate_hsn_code")),
		"can_open_stock": _can_open_stock(),
	}


@frappe.whitelist()
def preview(file_url: str | None = None, sheet_url: str | None = None) -> dict:
	"""Read the sheet and say what would happen. Nothing is written.

	The whole point of this screen: four hundred rows always contain a few that
	cannot be made, and finding that out one refusal at a time is worse than not
	having the import at all.
	"""
	_me()
	require_permission("Item", "create")

	rows = _read(file_url, sheet_url)
	header, body = rows[0], rows[1:]
	mapping, unknown = _map_columns(header)

	missing = [c["label"] for c in COLUMNS
	           if c.get("required") and c["field"] not in mapping]
	if missing:
		frappe.throw(
			_("This sheet has no {0} column. The first row has to be the headings — "
			  "download the template if it helps.").format(", ".join(missing)),
			title=_("Headings not found"),
		)

	lists = _known()
	needs_hsn = bool(frappe.db.get_single_value("GST Settings", "validate_hsn_code"))
	may_open = _can_open_stock()
	seen: dict = {}
	out = []
	for offset, row in enumerate(body):
		line_no = offset + 2          # the row number the person sees in the sheet
		checked = _check_row(row, mapping, lists, seen, needs_hsn, line_no)
		out.append({
			"row": line_no,
			"item_name": checked["item"].get("item_name") or "",
			"item_code": checked["item"].get("item_code") or "",
			"item_group": checked["item"].get("item_group") or "",
			"purchase_rate": checked["item"].get("purchase_rate") or 0,
			"selling_rate": checked["item"].get("selling_rate") or 0,
			"opening_qty": checked["item"].get("opening_qty") or 0,
			"has_serial": checked["item"].get("has_serial") or 0,
			"is_service": checked["item"].get("is_service") or 0,
			"problems": checked["problems"],
			"ok": not checked["problems"],
		})

	ready = [r for r in out if r["ok"]]
	counted = sum(1 for r in ready if r["opening_qty"])
	return {
		"rows": out,
		"ready": len(ready),
		"blocked": len(out) - len(ready),
		"opening": counted,
		"can_open_stock": may_open,
		# Said once, at the top, rather than as a problem on every row: the
		# items themselves still go in, it is only the counts that cannot.
		"opening_note": (
			_("{0} rows carry an opening count. Your role cannot post opening stock, so "
			  "those items will be added with none — ask a manager to count them in."
			  ).format(counted)
			if counted and not may_open else ""),
		"matched": {c["label"]: (c["field"] in mapping) for c in COLUMNS},
		"ignored": unknown,
	}


@frappe.whitelist()
def commit(file_url: str | None = None, sheet_url: str | None = None,
           warehouse: str | None = None) -> dict:
	"""Make the items that pass, and report the ones that did not.

	The file is read and checked again rather than taking the preview's word for
	it — the catalogue may have moved on between looking and pressing, and a
	row's own savepoint means one bad item cannot take the other three hundred
	and ninety-nine down with it.
	"""
	employee = _me()
	require_permission("Item", "create")

	from a3_retail.api.stock_control import create_item

	rows = _read(file_url, sheet_url)
	header, body = rows[0], rows[1:]
	mapping, _ignored = _map_columns(header)
	lists = _known()
	needs_hsn = bool(frappe.db.get_single_value("GST Settings", "validate_hsn_code"))
	may_open = _can_open_stock()

	if warehouse and warehouse not in set(
			frappe.get_all("Warehouse", filters={"custom_branch": employee.branch,
			                                     "is_group": 0}, pluck="name")):
		frappe.throw(_("That store does not belong to {0}.").format(employee.branch))

	seen: dict = {}
	made, failed = [], []
	for offset, row in enumerate(body):
		line_no = offset + 2
		checked = _check_row(row, mapping, lists, seen, needs_hsn, line_no)
		if checked["problems"]:
			failed.append({"row": line_no, "item_name": checked["item"].get("item_name", ""),
			               "problems": checked["problems"]})
			continue

		payload = dict(checked["item"])
		if payload.get("opening_qty") and warehouse and may_open:
			payload["warehouse"] = warehouse
		elif payload.get("opening_qty"):
			# No store chosen, or not this person's to post: the item is still
			# worth having in the catalogue, so it goes in without the count.
			payload["opening_qty"] = 0

		# An HSN the shop floor typed may be missing from ERPNext's list, which
		# ships incomplete; the same registration the New Item form does.
		if payload.get("hsn_code"):
			from a3_retail.api.stock import _hsn

			payload["hsn_code"] = _hsn(payload["hsn_code"]) or ""

		# Cleared per row so the message read back belongs to this row.
		frappe.clear_messages()
		try:
			result = create_item(payload)
			made.append({"row": line_no, "item_code": result["item_code"],
			             "item_name": result["item_name"]})
		except Exception as error:
			failed.append({"row": line_no, "item_name": payload.get("item_name", ""),
			               "problems": [_reason(error)]})

	return {"made": len(made), "failed": len(failed), "items": made[:200],
	        "problems": failed[:200]}


def _as_file(name: str, rows: list[list], sheets: dict | None = None) -> str:
	"""An xlsx on disk, returned as a link the browser can download.

	Built with openpyxl rather than `make_xlsx`, which hands back a saved
	stream and so cannot be given a second sheet — and the sheet of valid
	categories is half the value of the template.
	"""
	from io import BytesIO

	import openpyxl
	from openpyxl.styles import Font

	book = openpyxl.Workbook()
	book.remove(book.active)
	for title, body in [("Items", rows)] + list((sheets or {}).items()):
		page = book.create_sheet(title)
		for line in body:
			page.append([("" if cell is None else cell) for cell in line])
		for cell in page[1]:
			cell.font = Font(bold=True)
		# Wide enough to read without dragging every column out by hand.
		for column in range(1, (max((len(r) for r in body), default=1)) + 1):
			longest = max((len(str(r[column - 1])) for r in body
			               if len(r) >= column and r[column - 1] is not None), default=10)
			page.column_dimensions[
				openpyxl.utils.get_column_letter(column)].width = min(max(longest + 2, 12), 48)

	buffer = BytesIO()
	book.save(buffer)

	saved = frappe.get_doc({
		"doctype": "File",
		"file_name": name,
		"is_private": 1,
		"content": buffer.getvalue(),
	})
	saved.flags.ignore_permissions = True
	saved.save()
	return saved.file_url


@frappe.whitelist()
def template() -> str:
	"""A sheet with the right headings, an example row, and the lists to pick from.

	Half of what goes wrong in an import is a category spelled a way the site
	does not know. Shipping the valid ones in the file beats finding out a row
	at a time.
	"""
	employee = _me()
	require_permission("Item", "create")

	header = [c["label"] for c in COLUMNS]
	hint = [c["help"] for c in COLUMNS]
	example = [c.get("example", "") for c in COLUMNS]

	groups = frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", order_by="name")
	brands = [b for b in frappe.get_all("Brand", pluck="name", order_by="name")
	          if not b.startswith("_Test")]
	uoms = frappe.get_all("UOM", filters={"enabled": 1}, pluck="name", order_by="name",
	                      limit_page_length=0)

	reference = [["Categories", "Brands", "Units"]]
	for index in range(max(len(groups), len(brands), len(uoms))):
		reference.append([
			groups[index] if index < len(groups) else "",
			brands[index] if index < len(brands) else "",
			uoms[index] if index < len(uoms) else "",
		])

	notes = [
		["How this sheet is read"],
		[""],
		["Keep the first row exactly as it is — those headings are how each column is found."],
		["Fill one item per row underneath. Delete the example row before importing."],
		["Category, Brand and Unit have to be spelled as they appear on the Reference sheet."],
		["Has IMEI: Yes for a handset that carries one, No for everything else."],
		["An IMEI item cannot carry opening stock here — those numbers come in on a purchase."],
		["Opening Stock goes into the store you choose on the import screen."],
		[f"Up to {ROW_LIMIT} items at a time."],
		[""],
		[f"Prepared for {employee.branch}."],
	]

	return _as_file(
		"A3 Item Import Template.xlsx",
		[header, hint, example],
		{"Reference": reference, "Notes": notes},
	)


@frappe.whitelist()
def problem_sheet(file_url: str | None = None, sheet_url: str | None = None) -> str:
	"""Just the rows that cannot go in, with the reason beside each.

	So the correction happens in the spreadsheet the person already has open,
	and what comes back is a short file rather than the original four hundred
	rows with a dozen problems hidden in them.
	"""
	_me()
	require_permission("Item", "create")

	rows = _read(file_url, sheet_url)
	header, body = rows[0], rows[1:]
	mapping, _ignored = _map_columns(header)
	lists = _known()
	needs_hsn = bool(frappe.db.get_single_value("GST Settings", "validate_hsn_code"))

	seen: dict = {}
	out = [["Row in your sheet", "What is wrong"] + [str(h or "") for h in header]]
	for offset, row in enumerate(body):
		line_no = offset + 2
		checked = _check_row(row, mapping, lists, seen, needs_hsn, line_no)
		if not checked["problems"]:
			continue
		out.append([line_no, "; ".join(checked["problems"])]
		           + [str(cell if cell is not None else "") for cell in row])

	if len(out) == 1:
		frappe.throw(_("Every row in that sheet is ready — nothing to correct."),
		             title=_("No problems"))

	return _as_file("A3 Items To Correct.xlsx", out)
