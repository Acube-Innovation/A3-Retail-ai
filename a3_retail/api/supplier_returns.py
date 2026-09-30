# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Debit notes — goods going back to a supplier (`/retail/debit-notes`).

A distributor's rep takes back a handset that would not sell, or a box that
arrived damaged. The shop raises a debit note: the stock leaves, and what the
supplier is owed drops by the same amount.

Standalone by design, the way the shop already works. myBillBook's debit notes
carry no link to the purchase they came from — the counter names the supplier and
types what is going back — and there is no purchase history here to link to
either. A Purchase Invoice with `is_return = 1` and no `return_against` is
exactly that document in ERPNext.

The value-only case — a supplier allowing a rate difference with no goods moving
— is deliberately not folded in here. That is a credit against the account with
no stock behind it, and mixing the two on one screen is how stock and payables
drift apart.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.pos import _profile
from a3_retail.api.staff import _me

LINE_LIMIT = 100


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the screen needs before the counter types anything."""
	employee = _me()
	profile = _profile(employee.branch)
	return {
		"branch": employee.branch,
		"warehouse": profile.default_warehouse,
		"can_create": bool(frappe.has_permission("Purchase Invoice", "create")),
		"modes": frappe.get_all(
			"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name"),
	}


@frappe.whitelist()
def stock_items(query: str = "", limit: int = 10) -> list[dict]:
	"""Items this branch actually holds — only stock it has can go back."""
	employee = _me()
	require_permission("Item", "read")

	profile = _profile(employee.branch)
	if not profile.default_warehouse:
		return []

	like = f"%{(query or '').strip()}%"
	rows = frappe.db.sql(
		"""
		select i.name as item_code, i.item_name, i.gst_hsn_code,
		       ifnull(b.actual_qty, 0) as qty, ifnull(b.valuation_rate, 0) as rate,
		       ifnull(i.has_serial_no, 0) as has_serial
		from `tabItem` i
		join `tabBin` b on b.item_code = i.name and b.warehouse = %(warehouse)s
		where ifnull(i.disabled, 0) = 0 and b.actual_qty > 0
		  and (i.name like %(q)s or i.item_name like %(q)s)
		order by i.item_name
		limit %(limit)s
		""",
		{"warehouse": profile.default_warehouse, "q": like,
		 "limit": min(cint(limit) or 10, 50)},
		as_dict=True,
	)
	return rows


@frappe.whitelist()
def recent(limit: int = 30) -> dict:
	"""Debit notes this branch has raised, newest first."""
	employee = _me()
	require_permission("Purchase Invoice", "read")

	profile = _profile(employee.branch)
	if not profile.default_warehouse:
		return {"branch": employee.branch, "rows": []}

	rows = frappe.db.sql(
		"""
		select pi.name, pi.supplier, pi.posting_date, pi.grand_total,
		       pi.outstanding_amount, pi.docstatus,
		       (select count(*) from `tabPurchase Invoice Item` it
		         where it.parent = pi.name) as line_count
		from `tabPurchase Invoice` pi
		where pi.is_return = 1 and pi.docstatus < 2 and exists (
		      select 1 from `tabPurchase Invoice Item` it
		       where it.parent = pi.name and it.warehouse = %(warehouse)s)
		order by pi.posting_date desc, pi.creation desc
		limit %(limit)s
		""",
		{"warehouse": profile.default_warehouse, "limit": min(cint(limit) or 30, 100)},
		as_dict=True,
	)
	for row in rows:
		row["supplier_name"] = frappe.db.get_value("Supplier", row.supplier, "supplier_name")
		row["amount"] = abs(flt(row.grand_total))
	return {"branch": employee.branch, "rows": rows}


@frappe.whitelist()
def create(payload) -> dict:
	"""Send the goods back and raise the debit note."""
	employee = _me()
	require_permission("Purchase Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})

	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Choose which supplier the goods are going back to."),
		             title=_("Supplier"))

	items = [row for row in (data.get("items") or [])
	         if row.get("item_code") and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Say what is going back."), title=_("Nothing to return"))
	if len(items) > LINE_LIMIT:
		frappe.throw(_("That is more lines than one note should carry."), title=_("Items"))

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A debit note cannot be dated in the future."), title=_("Date"))

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		frappe.throw(_("This branch has no store to send stock back from."),
		             title=_("Warehouse"))
	cost_center = profile.sales_cost_center or profile.cost_center

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.is_return = 1
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.bill_no = (data.get("bill_no") or "").strip() or None
	doc.bill_date = posting
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch

	for row in items:
		code = row["item_code"]
		held = flt(frappe.db.get_value(
			"Bin", {"item_code": code, "warehouse": warehouse}, "actual_qty"))
		qty = flt(row["qty"])
		if qty > held + 0.0001:
			frappe.throw(
				_("Only {0} of {1} is in this branch — that is all that can go back.")
				.format(held, frappe.db.get_value("Item", code, "item_name") or code),
				title=_("Not that many"),
			)

		# A return carries negative quantities; that is what sends the stock out.
		line = doc.append("items", {
			"item_code": code,
			"qty": -qty,
			"rate": flt(row.get("rate")),
			"warehouse": warehouse,
		})
		if cost_center:
			line.cost_center = cost_center
		serials = [s for s in (row.get("serials") or []) if s]
		if serials:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serials)

	if cost_center and doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center
	if data.get("reason"):
		doc.remarks = str(data["reason"])[:500]

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	value = abs(flt(doc.rounded_total) or flt(doc.grand_total))
	return {
		"debit_note": doc.name,
		"supplier": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"amount": value,
		"outstanding": flt(doc.outstanding_amount),
		"print_url": f"/printview?doctype=Purchase%20Invoice&name={doc.name}",
	}
