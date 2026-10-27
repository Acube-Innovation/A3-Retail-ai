# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Goods in before the bill is (`Receive Stock` on the stock screen).

A service counter is sent parts and handsets long before the distributor's
invoice turns up, and the person signing for the box knows two things: how many
came, and what the shop will sell them at. What it cost is on a bill that may
arrive a week later, and making them invent a figure to get the stock onto the
shelf is how wrong cost prices get into the ledger and stay there.

So this writes a Purchase Receipt — goods in, no bill — and takes only the
selling price, which is the number the counter actually knows. The stock is
valued provisionally at what the item last cost, because a nil valuation would
make everything sold before the bill arrives look like pure profit. When the
bill comes, `bill()` raises the Purchase Invoice against the receipt at the
real rate and ERPNext corrects the valuation behind it.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import date_window, require_permission, stamp_cost_center
from a3_retail.api.pos import _profile
from a3_retail.api.staff import _me

LINE_LIMIT = 100


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the Receive Stock sheet needs before the first keystroke."""
	employee = _me()
	profile = _profile(employee.branch)
	return {
		"branch": employee.branch,
		"warehouse": profile.default_warehouse,
		"can_receive": bool(frappe.has_permission("Purchase Receipt", "create")),
		"can_bill": bool(frappe.has_permission("Purchase Invoice", "create")),
	}


@frappe.whitelist()
def provisional_rate(item_code: str) -> dict:
	"""What the shelf will be valued at until the bill says otherwise."""
	employee = _me()
	profile = _profile(employee.branch)
	return {"item_code": item_code,
	        "rate": _provisional(item_code, profile.default_warehouse)}


def _provisional(item_code: str, warehouse: str | None) -> float:
	"""A standing-in cost: what it last cost, else what the shelf holds it at.

	Not nothing. An item received at nil and sold before the bill arrives reads
	as pure profit, and the month it is billed in takes the whole cost at once.
	"""
	last = flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))
	if last > 0:
		return last
	held = flt(frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	return held


@frappe.whitelist()
def receive(payload) -> dict:
	"""Book the goods in against a supplier, with no bill behind them yet."""
	employee = _me()
	require_permission("Purchase Receipt", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Say who sent the goods."), title=_("Supplier"))

	items = [row for row in (data.get("items") or [])
	         if row.get("item_code") and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Say what came in."), title=_("Nothing to receive"))
	if len(items) > LINE_LIMIT:
		frappe.throw(_("That is more lines than one receipt should carry."),
		             title=_("Items"))

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("Stock cannot arrive on a day that has not happened."),
		             title=_("Date"))

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		frappe.throw(_("This branch has no store to receive stock into."),
		             title=_("Warehouse"))

	doc = frappe.new_doc("Purchase Receipt")
	doc.company = _company()
	doc.supplier = supplier
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	if data.get("docket"):
		doc.remarks = _("Docket {0}").format(str(data["docket"])[:120])

	priced = {}
	for row in items:
		code = row["item_code"]
		line = doc.append("items", {
			"item_code": code,
			"qty": flt(row["qty"]),
			"warehouse": warehouse,
			# Standing in until the bill arrives; `bill()` puts the real one on.
			"rate": _provisional(code, warehouse),
		})
		serials = [s for s in (row.get("serials") or []) if s]
		if serials:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serials)
		if flt(row.get("selling_rate")) > 0:
			priced[code] = flt(row["selling_rate"])

	centre = profile.sales_cost_center or profile.cost_center
	if centre:
		stamp_cost_center(doc, centre)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	# What the shop will ask for it — the one price the person signing for the
	# box actually knows.
	from a3_retail.api.stock_control import set_selling_rate

	for code, rate in priced.items():
		set_selling_rate(code, rate, employee.branch)

	doc.reload()
	return {"receipt": doc.name, "supplier": supplier,
	        "lines": len(doc.items), "priced": len(priced),
	        "provisional_value": flt(doc.grand_total)}


@frappe.whitelist()
def pending(filters=None, limit: int = 40) -> dict:
	"""Goods this branch has taken in that no bill has caught up with yet."""
	employee = _me()
	require_permission("Purchase Receipt", "read")

	profile = _profile(employee.branch)
	if not profile.default_warehouse:
		return {"branch": employee.branch, "rows": [], "owed": 0.0}

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	values = {"warehouse": profile.default_warehouse,
	          "limit": min(cint(limit) or 40, 200)}
	# `per_billed` is what ERPNext itself keeps: the share of the receipt that a
	# Purchase Invoice has since claimed. Below 100 means somebody is still owed
	# a bill for it.
	where = ["pr.docstatus = 1", "ifnull(pr.per_billed, 0) < 99.99",
	         "exists (select 1 from `tabPurchase Receipt Item` it"
	         " where it.parent = pr.name and it.warehouse = %(warehouse)s)"]
	where += date_window(data, "pr.posting_date", values)
	query = (data.get("query") or "").strip()
	if query:
		where.append("(pr.name like %(q)s or pr.supplier_name like %(q)s"
		             " or pr.remarks like %(q)s)")
		values["q"] = f"%{query}%"

	rows = frappe.db.sql(
		f"""
		select pr.name, pr.supplier, pr.supplier_name, pr.posting_date,
		       pr.grand_total, pr.per_billed, pr.remarks,
		       (select count(*) from `tabPurchase Receipt Item` it
		         where it.parent = pr.name) as line_count,
		       (select group_concat(it.item_name order by it.idx separator ', ')
		          from `tabPurchase Receipt Item` it where it.parent = pr.name) as items,
		       datediff(curdate(), pr.posting_date) as waiting
		from `tabPurchase Receipt` pr
		where {" and ".join(where)}
		order by pr.posting_date, pr.creation
		limit %(limit)s
		""",
		values, as_dict=True)

	for row in rows:
		row["provisional"] = flt(row.grand_total)
		row["items"] = _shorten(row.get("items"))
	return {"branch": employee.branch, "rows": rows,
	        "owed": sum(flt(r["provisional"]) for r in rows)}


def _shorten(names: str | None, shown: int = 2) -> str:
	parts = [p.strip() for p in (names or "").split(",") if p.strip()]
	if not parts:
		return ""
	rest = len(parts) - shown
	return ", ".join(parts[:shown]) + (f" +{rest} more" if rest > 0 else "")


@frappe.whitelist()
def to_bill(receipt: str) -> dict:
	"""The lines on a receipt, ready for the cost prices off the bill."""
	employee = _me()
	require_permission("Purchase Receipt", "read")

	doc = frappe.get_doc("Purchase Receipt", receipt)
	if doc.get("branch") and doc.branch != employee.branch:
		frappe.throw(_("That receipt belongs to another branch."),
		             title=_("Not this branch"))
	if cint(doc.docstatus) != 1:
		frappe.throw(_("Only a completed receipt can be billed."), title=_("Not received"))
	if flt(doc.per_billed) >= 99.99:
		frappe.throw(_("{0} has already been billed.").format(doc.name),
		             title=_("Already billed"))

	return {
		"receipt": doc.name,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name,
		"posting_date": str(doc.posting_date),
		"lines": [{
			"item_code": row.item_code, "item_name": row.item_name,
			"qty": flt(row.qty),
			# What it was valued at while it waited; the bill replaces it.
			"provisional": flt(row.rate),
			"selling": flt(frappe.db.get_value(
				"Item Price", {"item_code": row.item_code, "selling": 1},
				"price_list_rate", order_by="modified desc")),
		} for row in doc.items],
	}


@frappe.whitelist()
def bill(payload) -> dict:
	"""The distributor's bill has arrived — put the real cost on the goods."""
	employee = _me()
	require_permission("Purchase Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	receipt = (data.get("receipt") or "").strip()
	source = frappe.get_doc("Purchase Receipt", receipt) if receipt and frappe.db.exists(
		"Purchase Receipt", receipt) else None
	if not source:
		frappe.throw(_("Which receipt is the bill for?"), title=_("Receipt"))
	if source.get("branch") and source.branch != employee.branch:
		frappe.throw(_("That receipt belongs to another branch."),
		             title=_("Not this branch"))
	if flt(source.per_billed) >= 99.99:
		frappe.throw(_("{0} has already been billed.").format(source.name),
		             title=_("Already billed"))

	bill_no = (data.get("bill_no") or "").strip()
	if not bill_no:
		frappe.throw(_("Enter the supplier's bill number."), title=_("Bill number"))

	rates = {str(row.get("item_code")): flt(row.get("rate"))
	         for row in (data.get("items") or []) if row.get("item_code")}
	if not rates or all(rate <= 0 for rate in rates.values()):
		frappe.throw(_("Put the cost prices off the bill against the lines."),
		             title=_("Rates"))

	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	# `get_mapped_doc` asks the session user for create rights in its own way;
	# the caller has already been checked above, so the mapping runs elevated.
	actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		doc = make_purchase_invoice(source.name)
	finally:
		frappe.set_user(actor)

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A bill cannot be dated in the future."), title=_("Date"))
	if posting < getdate(source.posting_date):
		frappe.throw(
			_("The goods came in on {0}, so the bill cannot be dated before that.")
			.format(frappe.utils.formatdate(source.posting_date)), title=_("Date"))

	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.bill_no = bill_no
	doc.bill_date = getdate(data.get("bill_date") or posting)
	doc.set("payment_schedule", [])
	for line in doc.items:
		if rates.get(line.item_code) is not None and flt(rates[line.item_code]) > 0:
			line.rate = flt(rates[line.item_code])

	profile = _profile(employee.branch)
	_apply_gst(doc, employee.branch)
	centre = profile.sales_cost_center or profile.cost_center
	if centre:
		stamp_cost_center(doc, centre)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	source.reload()
	return {"invoice": doc.name, "receipt": source.name,
	        "amount": flt(doc.grand_total),
	        "outstanding": flt(doc.outstanding_amount),
	        "receipt_billed": flt(source.per_billed),
	        # What the guess was out by. The stock is still carrying the guess:
	        # a Purchase Receipt's rate *is* its valuation, which is why ERPNext
	        # would rather refuse a bill that disagrees. Until that is settled,
	        # the difference sits in Stock Received But Not Billed where it can
	        # at least be seen and cleared.
	        "rate_difference": flt(doc.grand_total - doc.get("total_taxes_and_charges", 0)
	                               - source.grand_total)}


def _apply_gst(doc, branch: str) -> None:
	"""Input GST on the bill, the way the distributor's own bill carries it."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	from a3_retail.utils import tax

	rate = tax.bill_rate(doc.get("items"))
	if not rate:
		return
	template = tax.input_gst_template(doc.company, branch, doc.supplier, rate)
	if not template:
		return
	doc.taxes_and_charges = template
	doc.set("taxes", [])
	for row in get_taxes_and_charges("Purchase Taxes and Charges Template", template):
		doc.append("taxes", row)
