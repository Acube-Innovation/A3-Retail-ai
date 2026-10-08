"""A3 Retail — stock API (scope 6.1).

Cross-branch availability is deliberately readable by every branch user: the
whole point of requirement 8 is that a counter can answer "do you have it in
Kochi?" without leaving POS. Writes stay restricted by User Permission.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me
from a3_retail.utils.branch import get_user_branch

MANAGER_ROLES = {"Branch Manager", "A3 Retail Admin", "Accounts Manager", "System Manager", "Auditor"}


def _may_see_valuation(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(MANAGER_ROLES & set(frappe.get_roles(user)))


@frappe.whitelist()
def availability_matrix(item_code: str) -> list[dict]:
	"""Quantity of an item at every branch.

	ignore_permissions rationale (scope 6.1): a branch user's Warehouse User
	Permission restricts *writes* to their own branch. Availability has to be
	visible everywhere or a counter could never raise a cross-branch transfer,
	so this runs as a read-only aggregate over `tabBin` returning quantity
	columns only. Valuation is appended separately, for manager roles alone.
	"""
	require_permission("Item", "read")

	rows = frappe.db.sql(
		"""
		select w.custom_branch as branch, b.warehouse, b.actual_qty, b.reserved_qty,
		       b.indented_qty, b.ordered_qty, b.projected_qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s and w.disabled = 0 and b.actual_qty != 0
		order by w.custom_branch, b.warehouse
		""",
		{"item_code": item_code},
		as_dict=True,
	)

	show_valuation = _may_see_valuation()
	for row in rows:
		row["available"] = flt(row["actual_qty"]) - flt(row["reserved_qty"])
		if show_valuation:
			row["stock_value"] = flt(
				frappe.db.get_value(
					"Bin", {"item_code": item_code, "warehouse": row["warehouse"]}, "stock_value"
				)
			)

	return rows


@frappe.whitelist()
def search_items(query: str = "", filters: dict | str | None = None, branch: str | None = None,
                 limit: int = 40) -> list[dict]:
	"""Item search for the Stock Explorer, with this branch's quantity attached."""
	require_permission("Item", "read")

	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}

	branch = branch or get_user_branch()
	conditions = ["i.disabled = 0"]
	values = {"query": f"%{query}%", "limit": int(limit)}

	if query:
		from a3_retail.utils.compatibility import barcode_clause, serial_clause

		conditions.append("(i.name like %(query)s or i.item_name like %(query)s or "
		                  + barcode_clause("i") + " or "
		                  # An IMEI read off the box finds its phone here too.
		                  + serial_clause("i", "query") + ")")
	if filters.get("item_group"):
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = filters["item_group"]
	if filters.get("brand"):
		conditions.append("i.brand = %(brand)s")
		values["brand"] = filters["brand"]

	branch_join = ""
	qty_column = "0"
	if branch:
		branch_join = """
			left join (
				select b.item_code, sum(b.actual_qty) qty
				from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
				where w.custom_branch = %(branch)s group by b.item_code
			) mine on mine.item_code = i.name"""
		qty_column = "ifnull(mine.qty, 0)"
		values["branch"] = branch

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.brand, i.image,
		       {qty_column} as branch_qty, i.a3_is_device
		from `tabItem` i
		{branch_join}
		where {" and ".join(conditions)}
		order by i.item_name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)

	if filters.get("only_in_stock"):
		rows = [r for r in rows if flt(r["branch_qty"]) > 0]

	return rows


@frappe.whitelist()
def serial_list(item_code: str, warehouse: str | None = None, limit: int = 100) -> list[dict]:
	"""Serial numbers in stock, with their age in days."""
	require_permission("Serial No", "read")

	filters = {"item_code": item_code, "status": "Active"}
	if warehouse:
		filters["warehouse"] = warehouse

	rows = frappe.get_all(
		"Serial No",
		filters=filters,
		fields=["name", "a3_imei_1", "warehouse", "creation", "a3_warranty_state"],
		limit_page_length=int(limit),
		order_by="creation asc",
	)
	for row in rows:
		row["age_days"] = date_diff(nowdate(), row["creation"])
	return rows


@frappe.whitelist()
def item_details(item_code: str) -> dict:
	"""What the edit dialog shows about one item."""
	_me()
	require_permission("Item", "read")

	doc = frappe.get_doc("Item", item_code)
	price = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": "Standard Selling",
		               "selling": 1}, "price_list_rate")
	return {
		"item_code": doc.name,
		"item_name": doc.item_name,
		"item_group": doc.item_group,
		"brand": doc.get("brand"),
		"stock_uom": doc.stock_uom,
		"gst_hsn_code": doc.get("gst_hsn_code"),
		"has_serial_no": cint(doc.get("has_serial_no")),
		"disabled": cint(doc.disabled),
		"barcodes": [row.barcode for row in (doc.get("barcodes") or [])],
		"selling_rate": flt(price),
	}


@frappe.whitelist()
def save_item(item_code: str, item_name: str = "", brand: str | None = None,
              gst_hsn_code: str | None = None, barcode: str | None = None,
              selling_rate=None, disabled: int = 0) -> dict:
	"""Correct an item from the shop floor.

	A typo in a name, a missing HSN or a barcode that never got scanned in are
	all things the branch finds and head office does not. What cannot be changed
	here is anything that would rewrite history: the item code, its UOM, or
	whether it carries serial numbers — those decide how existing stock is
	valued and counted.
	"""
	_me()
	require_permission("Item", "write")

	doc = frappe.get_doc("Item", item_code)
	item_name = (item_name or "").strip()
	if not item_name:
		frappe.throw(_("The item needs a name."), title=_("Item"))

	doc.item_name = item_name[:140]
	if brand is not None:
		doc.brand = brand.strip() or None
	if gst_hsn_code is not None:
		hsn = _hsn(gst_hsn_code)
		if hsn:
			doc.gst_hsn_code = hsn
	doc.disabled = 1 if cint(disabled) else 0

	barcode = (barcode or "").strip()
	if barcode and barcode not in [row.barcode for row in (doc.get("barcodes") or [])]:
		owner = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
		if owner and owner != item_code:
			frappe.throw(_("{0} is already the barcode of {1}.").format(barcode, owner),
			             title=_("Barcode"))
		doc.append("barcodes", {"barcode": barcode})

	doc.flags.ignore_mandatory = True
	doc.save()

	if selling_rate not in (None, ""):
		_set_selling_rate(item_code, flt(selling_rate))
	return item_details(item_code)


def _set_selling_rate(item_code: str, rate: float):
	"""One selling price per item on the standard list, replaced rather than stacked."""
	if rate <= 0:
		return
	existing = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": "Standard Selling",
		               "selling": 1}, "name")
	if existing:
		frappe.db.set_value("Item Price", existing, "price_list_rate", rate)
		return
	price = frappe.new_doc("Item Price")
	price.item_code = item_code
	price.price_list = "Standard Selling"
	price.selling = 1
	price.price_list_rate = rate
	price.flags.ignore_permissions = True
	price.insert(ignore_permissions=True)


def _hsn(code) -> str | None:
	"""An HSN the shop floor typed, registered here if ERPNext's list lacks it.

	`gst_hsn_code` is a link and ERPNext ships an incomplete master, so a
	well-formed code that is simply missing would otherwise be refused — and an
	item with no HSN cannot be billed under GST at all.
	"""
	import re

	code = re.sub(r"\D", "", str(code or ""))
	if len(code) not in (4, 6, 8):
		return None
	if not frappe.db.exists("GST HSN Code", code):
		doc = frappe.new_doc("GST HSN Code")
		doc.hsn_code = code
		doc.description = "Added from the branch app"
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	return code
