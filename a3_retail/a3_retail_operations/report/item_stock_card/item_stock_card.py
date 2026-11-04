# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Item Stock Card — one item, in full, from a scan.

What the counter wants when they pick a box up and wonder about it: what it
costs, what it sells for, how many are left and where, and — for a handset —
every individual piece by its IMEI, with the bill it went out on.

Three pieces, because that is how the question is asked:

  * the number cards        what it is worth and what it is priced at
  * the summary table       the item's own particulars, the ones that are words
  * the main table          every piece, by serial number

Entry is by scan. The gun types a barcode and presses Enter, so the filter is a
plain Data field and `_resolve` works out whether it was handed a barcode, an
item code, a serial number or part of a name.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from a3_retail.reporting import col
from a3_retail.utils.permissions import get_permitted_branches

COLUMNS = [
	col("Serial Number", "serial_no", "Link", 180, "Serial No"),
	col("Branch", "branch", "Data", 150),
	col("Warehouse", "warehouse", "Link", 190, "Warehouse"),
	col("Date Created", "creation_date", "Date", 110),
	col("Came In On", "purchase_document_no", "Data", 150),
	col("Invoice Number", "invoice", "Data", 150),
	col("Status", "status", "Data", 110),
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	item = _resolve(filters.get("item"))
	if not item:
		# A report that answers an empty question with an empty table tells the
		# counter nothing. Say which word found nothing.
		frappe.throw(
			_("Nothing matches {0}. Scan the barcode, or type part of the item's "
			  "name.").format(frappe.bold(filters.get("item") or "—")),
			title=_("No such item"))

	rows = _serials(item, filters)
	return COLUMNS, rows, None, None, _cards(item, filters)


# ---------------------------------------------------------------------------
# Finding the item
# ---------------------------------------------------------------------------
def _resolve(given) -> str | None:
	"""Barcode, item code, serial number or part of a name — whichever it was."""
	text = (str(given or "")).strip()
	if not text:
		return None

	if frappe.db.exists("Item", text):
		return text

	barcode = frappe.db.get_value("Item Barcode", {"barcode": text}, "parent")
	if barcode:
		return barcode

	# A counter who scans the handset itself rather than its box is asking
	# about the same item, so answer rather than refusing.
	serial = frappe.db.get_value("Serial No", text, "item_code")
	if serial:
		return serial

	hit = frappe.get_all("Item", filters={"item_name": ("like", f"%{text}%")},
	                     pluck="name", order_by="length(item_name)", limit=1)
	return hit[0] if hit else None


def _permitted() -> list[str]:
	return get_permitted_branches() or []


# ---------------------------------------------------------------------------
# The three pieces
# ---------------------------------------------------------------------------
def _serials(item: str, filters) -> list[dict]:
	"""Every piece of this item, by serial number.

	An unserialised item has none, and the table is empty — which is itself the
	answer: this is something counted by the handful, not by the piece.
	"""
	if not frappe.db.get_value("Item", item, "has_serial_no"):
		return []

	conditions, values = ["sn.item_code = %(item)s"], {"item": item}

	branches = [filters.branch] if filters.get("branch") else _permitted()
	if branches:
		values["branches"] = branches
		# A sold piece has no warehouse left on it, so it would vanish from a
		# branch filter that only looked at where it is sitting.
		conditions.append("(w.custom_branch in %(branches)s or sn.warehouse is null)")

	if not cint(filters.get("sold", 1)):
		conditions.append("ifnull(sn.status, '') != 'Delivered'")

	rows = frappe.db.sql(f"""
		select sn.name as serial_no, sn.warehouse, w.custom_branch as branch,
		       date(sn.creation) as creation_date,
		       sn.purchase_document_no, sn.status
		from `tabSerial No` sn
		left join `tabWarehouse` w on w.name = sn.warehouse
		where {' and '.join(conditions)}
		order by sn.creation desc
	""", values, as_dict=True)

	for row in rows:
		row["invoice"] = _sold_on(row["serial_no"])
		if not row.get("branch") and row.get("status") == "Delivered":
			row["branch"] = _("sold")
	return rows


def _sold_on(serial_no: str) -> str:
	"""The bill this piece went out on, through the bundle that recorded it."""
	hit = frappe.db.sql("""
		select b.voucher_no
		from `tabSerial and Batch Entry` e
		join `tabSerial and Batch Bundle` b on b.name = e.parent
		where e.serial_no = %s and b.docstatus = 1
		  and b.type_of_transaction = 'Outward'
		  and b.voucher_type in ('Sales Invoice', 'POS Invoice', 'Delivery Note')
		order by b.posting_datetime desc limit 1
	""", serial_no)
	return hit[0][0] if hit else ""


def _cards(item: str, filters) -> list[dict]:
	"""The numbers, above the table: what it holds and what it is priced at."""
	doc = frappe.get_cached_doc("Item", item)
	qty, value = _on_hand(item, filters)

	return [
		{"label": _("Current Stock"), "value": qty, "datatype": "Float"},
		{"label": _("Stock Value"), "value": value, "datatype": "Currency"},
		{"label": _("Sales Price"), "value": _price(item, selling=True),
		 "datatype": "Currency"},
		{"label": _("Purchase Price"), "value": _price(item, selling=False),
		 "datatype": "Currency"},
		{"label": _("GST Rate"), "value": _gst_rate(doc), "datatype": "Percent"},
	]


def _on_hand(item: str, filters) -> tuple[float, float]:
	conditions, values = ["b.item_code = %(item)s"], {"item": item}
	branches = [filters.branch] if filters.get("branch") else _permitted()
	if branches:
		values["branches"] = branches
		conditions.append("w.custom_branch in %(branches)s")

	row = frappe.db.sql(f"""
		select ifnull(sum(b.actual_qty), 0), ifnull(sum(b.stock_value), 0)
		from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
		where {' and '.join(conditions)}
	""", values)
	return (flt(row[0][0]), flt(row[0][1])) if row else (0.0, 0.0)


def _price(item: str, selling: bool) -> float:
	field = "selling" if selling else "buying"
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": item, field: 1},
		fields=["price_list_rate"], order_by="modified desc", limit=1)
	return flt(rows[0].price_list_rate) if rows else 0.0


def _gst_rate(doc) -> float:
	"""The rate the item actually bills at, from its tax template."""
	for row in doc.get("taxes") or []:
		rate = frappe.db.get_value("Item Tax Template", row.item_tax_template, "name")
		if not rate:
			continue
		total = frappe.db.sql("""
			select ifnull(sum(tax_rate), 0) from `tabItem Tax Template Detail`
			where parent = %s""", row.item_tax_template)
		if total and flt(total[0][0]):
			return flt(total[0][0])
	return 18.0


def summary(filters, rows):
	"""The item's own particulars — the parts of the answer that are words."""
	item = _resolve(filters.get("item"))
	if not item:
		return None

	doc = frappe.get_cached_doc("Item", item)
	qty, _value = _on_hand(item, filters)
	barcodes = ", ".join(row.barcode for row in (doc.get("barcodes") or []))

	particulars = [
		(_("Item Name"), doc.item_name or doc.name),
		(_("Item Code"), doc.name),
		(_("Barcode"), barcodes or "—"),
		(_("Category"), doc.item_group or "—"),
		(_("HSN Code"), doc.get("gst_hsn_code") or "—"),
		(_("Unit"), doc.stock_uom or "—"),
		(_("Tracked by serial number"), _("Yes") if doc.get("has_serial_no") else _("No")),
		(_("Low Stock Quantity"),
		 flt(doc.get("safety_stock")) or _("—")),
		(_("Low Stock Warning"),
		 _("On") if flt(doc.get("safety_stock")) and qty <= flt(doc.get("safety_stock"))
		 else (_("Set") if flt(doc.get("safety_stock")) else _("Disabled"))),
		(_("Selling"), _("Stopped") if doc.disabled else _("Yes")),
		(_("Description"), frappe.utils.strip_html(doc.description or "").strip() or "—"),
	]

	return {
		"title": _("Item details"),
		"detail_title": _("Serial numbers"),
		"columns": [col(_("Field"), "field", "Data", 220),
		            col(_("Value"), "value", "Data", 420)],
		"rows": [{"field": label, "value": value} for label, value in particulars],
		"totals": {},
	}
