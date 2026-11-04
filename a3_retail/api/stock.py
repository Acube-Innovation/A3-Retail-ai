"""A3 Retail — stock API (scope 6.1).

Cross-branch availability is deliberately readable by every branch user: the
whole point of requirement 8 is that a counter can answer "do you have it in
Kochi?" without leaving POS. Writes stay restricted by User Permission.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, nowdate

from a3_retail.api import require_permission, require_role
from a3_retail.api.staff import _me
from a3_retail.utils.branch import get_user_branch

MANAGER_ROLES = {"Branch Manager", "A3 Retail Admin", "Accounts Manager", "System Manager", "Auditor"}

# Faulty goods waiting for the dealer. On hand, but not for sale and not
# anybody's to request, so availability never counts them.
WARRANTY_SHELVES = ("select bp.warranty_returns_warehouse from `tabBranch Profile` bp"
                    " where ifnull(bp.warranty_returns_warehouse, '') != ''")


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
		f"""
		select w.custom_branch as branch, b.warehouse, b.actual_qty, b.reserved_qty,
		       b.indented_qty, b.ordered_qty, b.projected_qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s and w.disabled = 0 and b.actual_qty != 0
		  and w.name not in ({WARRANTY_SHELVES})
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
		"on_hand": on_hand(item_code),
		"can_serialise": can_serialise(item_code),
		"can_delete": can_delete_item(item_code),
	}


def on_hand(item_code: str) -> float:
	"""Everything this item holds, across every branch's shelves."""
	return flt(frappe.db.sql(
		"select ifnull(sum(actual_qty), 0) from `tabBin` where item_code = %s",
		item_code)[0][0])


def can_serialise(item_code: str) -> bool:
	"""Whether this item's serial setting may still be turned around.

	`has_serial_no` decides how *future* movements are recorded, so the only
	thing that makes changing it dangerous is stock already on a shelf: those
	pieces were counted in without IMEIs and could never produce one. With
	nothing on hand there is nothing to re-interpret.

	ERPNext's own rule is blunter — any submitted document that ever named the
	item refuses the change (`Item.cant_change`), including a reconciliation
	that moved zero. That is why this is decided here and written round it.
	"""
	if on_hand(item_code) != 0:
		return False
	# A bundle still holds serial numbers for the item; turning serialisation
	# off underneath one would strand them.
	return not frappe.db.count(
		"Serial and Batch Bundle", {"item_code": item_code, "docstatus": ("<", 2)})


def can_delete_item(item_code: str) -> bool:
	"""An item may go only if nothing anywhere has ever named it.

	Two checks, because they answer different questions. `_item_is_used` knows
	the handful of doctypes a shop cares about and can name the one that is in
	the way — "5 Stock Ledger Entry records" means something to a person.
	Frappe's own link scan is exhaustive but says only that *something* exists,
	so it goes second, as the backstop.
	"""
	if not frappe.db.get_value("Has Role", {"parent": frappe.session.user,
	                                        "role": "A3 Retail Admin"}):
		return False
	if _item_is_used(item_code):
		return False
	return not _linked_elsewhere(item_code)


def _linked_elsewhere(item_code: str) -> str | None:
	"""Would the real delete go through? Answered by trying it and undoing it.

	Scanning the link table directly was the obvious way and it was wrong:
	`delete_doc` runs the Item's own `on_trash` *before* the link check, and
	that clears the item's Bin and Item Price rows — so those two never block a
	deletion, while a scan sees them and reports every item in the shop as
	undeletable.

	Rather than keep a second copy of which links count, the delete is simply
	run inside a savepoint and rolled back. It cannot drift from the real
	behaviour, because it is the real behaviour.

	Returns the reason it would fail, or None if it would succeed.
	"""
	frappe.db.savepoint("a3_try_delete")
	try:
		frappe.delete_doc("Item", item_code)
	except Exception as error:
		return str(error) or _("Something else still names it.")
	finally:
		frappe.db.rollback(save_point="a3_try_delete")
	return None


# Everywhere an item can leave a mark that a deletion would orphan. The stock
# side comes first because it is the one a branch is most likely to hit.
USED_BY = (
	("Stock Ledger Entry", "item_code"),
	("Bin", "item_code"),
	("Sales Invoice Item", "item_code"),
	("POS Invoice Item", "item_code"),
	("Purchase Invoice Item", "item_code"),
	("Delivery Note Item", "item_code"),
	("Purchase Receipt Item", "item_code"),
	("Stock Entry Detail", "item_code"),
	("Stock Reconciliation Item", "item_code"),
	("Sales Order Item", "item_code"),
	("Purchase Order Item", "item_code"),
	("Material Request Item", "item_code"),
	("Serial No", "item_code"),
)


def _item_is_used(item_code: str) -> tuple[str, int] | None:
	for doctype, field in USED_BY:
		if not frappe.db.table_exists(doctype):
			continue
		count = frappe.db.count(doctype, {field: item_code})
		if count:
			return (doctype, count)
	return None


@frappe.whitelist()
def save_item(item_code: str, item_name: str = "", brand: str | None = None,
              gst_hsn_code: str | None = None, barcode: str | None = None,
              selling_rate=None, disabled: int = 0, has_serial=None) -> dict:
	"""Correct an item from the shop floor.

	A typo in a name, a missing HSN or a barcode that never got scanned in are
	all things the branch finds and head office does not. What cannot be changed
	here is anything that would rewrite history: the item code or its UOM —
	those decide how existing stock is valued and counted.

	Serial numbers are the one of that set that can still move, and only while
	the item holds nothing: handsets are routinely set up unserialised by
	mistake and found weeks later, and making a second item for the same phone
	is worse than turning the flag over on an empty shelf. `can_serialise` is
	the gate.
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
	rows = doc.get("barcodes") or []
	if barcode and barcode not in [row.barcode for row in rows]:
		owner = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
		if owner and owner != item_code:
			frappe.throw(_("{0} is already the barcode of {1}.").format(barcode, owner),
			             title=_("Barcode"))
		# The screen shows the first barcode in a box. Typing over it means
		# correcting that one — appending instead would leave the wrong number
		# still scanning to the same item, which is the fault being fixed. Any
		# further barcodes the item carries are left alone.
		if rows:
			rows[0].barcode = barcode
		else:
			doc.append("barcodes", {"barcode": barcode})

	doc.flags.ignore_mandatory = True
	doc.save()

	if has_serial is not None:
		_set_serialisation(item_code, cint(has_serial))

	if selling_rate not in (None, ""):
		_set_selling_rate(item_code, flt(selling_rate))
	return item_details(item_code)


def _set_serialisation(item_code: str, wanted: int):
	"""Turn serial numbers on or off for an item that holds nothing.

	Written with `db_set` rather than through `save()` on purpose. ERPNext
	refuses the change outright whenever any submitted document has ever named
	the item — a reconciliation that moved zero quantity is enough — and that
	rule exists to protect stock on a shelf, which `can_serialise` has already
	confirmed there is none of. Nothing else on the document is touched.
	"""
	current = cint(frappe.db.get_value("Item", item_code, "has_serial_no"))
	if current == cint(wanted):
		return

	if not can_serialise(item_code):
		frappe.throw(
			_("{0} still holds stock, so how it is counted cannot change. Clear the "
			  "shelf first, or set up a new item.").format(item_code),
			title=_("Stock on hand"),
		)

	frappe.db.set_value("Item", item_code, "has_serial_no", cint(wanted),
	                    update_modified=False)
	# No series: a handset's IMEI is printed on the box, not ours to invent, so
	# the counter is asked for it at the point the piece comes in.
	if not cint(wanted):
		frappe.db.set_value("Item", item_code, "serial_no_series", None,
		                    update_modified=False)
	frappe.clear_document_cache("Item", item_code)


@frappe.whitelist()
def delete_item(item_code: str) -> dict:
	"""Remove an item nothing in the books has ever named.

	Head office only, and only for the genuine mistakes: the duplicate typed in
	twice, the test row, the item a barcode was scanned into by accident. One
	that has ever moved is disabled instead — deleting it would leave the ledger
	pointing at nothing.
	"""
	_me()
	require_role("A3 Retail Admin")
	require_permission("Item", "delete")

	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("No such item."), title=_("Item"))

	instead = _("Tick \u201cStop selling this item\u201d instead: that hides it from "
	            "the counter and leaves the books intact.")

	used = _item_is_used(item_code)
	if used:
		doctype, count = used
		frappe.throw(
			_("{0} cannot be deleted — {1} {2} record(s) still name it. {3}")
			.format(item_code, count, _(doctype), instead),
			title=_("Still in use"),
		)

	frappe.delete_doc("Item", item_code)
	return {"deleted": item_code}


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
