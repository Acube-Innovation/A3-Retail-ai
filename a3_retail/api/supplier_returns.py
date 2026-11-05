# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Debit notes — what a supplier owes the shop (`/retail/debit-notes`).

Two kinds, and they are not the same document.

**Against purchase.** A distributor's rep takes back a handset that would not
sell, or a box that arrived damaged. The stock leaves, and what the supplier is
owed drops by the same amount.

**Scheme.** A brand settles a monthly slab offer. Nothing moves off a shelf —
the whole document is a figure the shop and the distributor have agreed, raised
against a line named after the scheme: "Month Slab Offer - 1st to 31st August
2026". The payable drops by the total, and the counter makes the item on the
spot, because every scheme has a different name and nobody can set them up in
advance.

Both reduce what the supplier is owed, which is why they share a screen. What
separates them is stock: the first moves it, the second never touches it.

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

from a3_retail.api import (date_window, require_permission, stamp_posting,
                           stock_expense_account)
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
		# The rates a scheme line can be put on, named the way the shop names
		# them, so the counter picks 18% rather than a template id.
		"gst_rates": _gst_rates(),
	}


def _gst_rates() -> list[dict]:
	from a3_retail.utils import tax

	return [{"rate": row["rate"], "template": row["name"]}
	        for row in tax.templates() if row["rate"]]


@frappe.whitelist()
def stock_items(query: str = "", limit: int = 10, kind: str = "purchase") -> list[dict]:
	"""What can go on a line, which depends on which kind of note it is.

	For goods, only what this branch actually holds. For a scheme, any item at
	all — a scheme line is the name of an offer and was never on a shelf.
	"""
	employee = _me()
	require_permission("Item", "read")

	profile = _profile(employee.branch)
	if not profile.default_warehouse and kind != "scheme":
		return []

	like = f"%{(query or '').strip()}%"
	limit = min(cint(limit) or 10, 50)

	# A scheme line is an offer's name, not a box, so it is never on a shelf and
	# the stock join would hide it. Asked for by kind so the goods search stays
	# exactly as it was: what this branch actually holds, and nothing else.
	if (kind or "purchase") == "scheme":
		return _with_gst(frappe.db.sql(
			"""
			select i.name as item_code, i.item_name, i.gst_hsn_code,
			       0 as qty, 0 as rate, 0 as has_serial
			from `tabItem` i
			where ifnull(i.disabled, 0) = 0
			  and (i.name like %(q)s or i.item_name like %(q)s)
			order by i.modified desc
			limit %(limit)s
			""",
			{"q": like, "limit": limit}, as_dict=True))

	rows = frappe.db.sql(
		"""
		select i.name as item_code, i.item_name, i.gst_hsn_code,
		       ifnull(b.actual_qty, 0) as qty, ifnull(b.valuation_rate, 0) as rate,
		       ifnull(i.has_serial_no, 0) as has_serial
		from `tabItem` i
		join `tabBin` b on b.item_code = i.name and b.warehouse = %(warehouse)s
		where ifnull(i.disabled, 0) = 0 and b.actual_qty > 0
		  and (i.name like %(q)s or i.item_name like %(q)s
		       or exists (select 1 from `tabItem Barcode` a3bc
		                  where a3bc.parent = i.name and a3bc.barcode like %(q)s))
		order by i.item_name
		limit %(limit)s
		""",
		{"warehouse": profile.default_warehouse, "q": like, "limit": limit},
		as_dict=True,
	)
	return _with_gst(rows)


def _with_gst(rows: list[dict]) -> list[dict]:
	"""Each hit's own GST rate, so the screen can total a note before saving it.

	A scheme is agreed at the figure *with* tax on it, so a counter who cannot
	see the tax cannot tell whether they have typed the right number.
	"""
	from a3_retail.utils import tax

	for row in rows:
		row["gst_rate"] = tax.item_rate(row["item_code"])
	return rows


@frappe.whitelist()
def create_scheme_item(payload) -> dict:
	"""Set up the item a scheme is billed under, from the debit note screen.

	Every slab offer has a different name — "Month Slab Offer - 1st to 31st
	August 2026" — so these cannot be set up in advance and the counter makes
	each one as it raises the note. Non-stock, because it is a figure the brand
	has agreed and not a thing on a shelf; `create_item` is the same call the
	purchase screen makes, so an item made here behaves like any other.
	"""
	from a3_retail.api.stock_control import create_item

	_me()
	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	name = (data.get("item_name") or "").strip()
	if not name:
		frappe.throw(_("Name the scheme — the offer and the month it covers."),
		             title=_("Scheme"))

	return create_item({
		"item_name": name,
		"item_group": data.get("item_group") or _scheme_group(),
		"hsn_code": (data.get("hsn_code") or "").strip(),
		"uom": data.get("uom") or "Nos",
		"tax_template": data.get("tax_template") or "",
		"description": (data.get("description") or "").strip(),
		# Never counted, so never on a shelf, so ERPNext keeps it away from
		# every warehouse — which is exactly what is wanted.
		"is_service": 1,
		"is_scheme": 1,
	})


def _scheme_group() -> str:
	"""Where scheme items are filed, made once and reused after that."""
	name = "Supplier Schemes"
	if frappe.db.exists("Item Group", name):
		return name
	parent = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))},
	                             "name") or "All Item Groups"
	doc = frappe.new_doc("Item Group")
	doc.item_group_name = name
	doc.parent_item_group = parent
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def recent(limit: int = 30, filters=None) -> dict:
	"""Debit notes this branch has raised, within the window asked for."""
	employee = _me()
	require_permission("Purchase Invoice", "read")

	profile = _profile(employee.branch)
	if not profile.default_warehouse:
		return {"branch": employee.branch, "rows": []}

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	values = {"warehouse": profile.default_warehouse,
	          "limit": min(cint(limit) or 30, 100)}
	where = ["pi.is_return = 1", "pi.docstatus < 2",
	         "exists (select 1 from `tabPurchase Invoice Item` it"
	         " where it.parent = pi.name and it.warehouse = %(warehouse)s)"]
	where += date_window(data, "pi.posting_date", values)
	query = (data.get("query") or "").strip()
	if query:
		where.append("(pi.name like %(q)s or pi.supplier_name like %(q)s"
		             " or pi.return_against like %(q)s)")
		values["q"] = f"%{query}%"

	rows = frappe.db.sql(
		f"""
		select pi.name, pi.supplier, pi.posting_date, pi.grand_total,
		       pi.outstanding_amount, pi.docstatus,
		       (select count(*) from `tabPurchase Invoice Item` it
		         where it.parent = pi.name) as line_count
		from `tabPurchase Invoice` pi
		where {" and ".join(where)}
		order by pi.posting_date desc, pi.creation desc
		limit %(limit)s
		""",
		values, as_dict=True,
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

	kind = (data.get("kind") or "purchase").strip()
	if kind not in ("purchase", "scheme"):
		frappe.throw(_("A debit note is either against a purchase or for a scheme."),
		             title=_("Type"))
	scheme = kind == "scheme"

	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(
			_("Say which brand is settling the scheme.") if scheme
			else _("Choose which supplier the goods are going back to."),
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
	# This note stands on its own — there is no one invoice it reverses — so
	# only the time of day needs sorting out: midnight on a back-dated note
	# lands before everything that happened that day.
	stamp_posting(doc, posting)
	doc.bill_no = (data.get("bill_no") or "").strip() or None
	doc.bill_date = posting
	# The whole difference between the two kinds, in one flag. A scheme is a
	# figure, not a box: nothing leaves a shelf, so nothing is counted out.
	doc.update_stock = 0 if scheme else 1
	if not scheme:
		doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch

	for row in items:
		code = row["item_code"]
		qty = flt(row["qty"])

		# Only goods going back have to be on the shelf first. A scheme line is
		# the name of an offer, and there was never one of it to count.
		if not scheme:
			held = flt(frappe.db.get_value(
				"Bin", {"item_code": code, "warehouse": warehouse}, "actual_qty"))
			if qty > held + 0.0001:
				frappe.throw(
					_("Only {0} of {1} is in this branch — that is all that can go back.")
					.format(held, frappe.db.get_value("Item", code, "item_name") or code),
					title=_("Not that many"),
				)

		# A return carries negative quantities; that is what sends the stock out,
		# and on a scheme it is what makes the payable drop instead.
		line = doc.append("items", {
			"item_code": code,
			"qty": -qty,
			"rate": flt(row.get("rate")),
		})
		if not scheme:
			line.warehouse = warehouse
		if cost_center:
			line.cost_center = cost_center
		serials = [s for s in (row.get("serials") or []) if s]
		if serials and not scheme:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serials)

	if cost_center and doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center
	if data.get("reason"):
		doc.remarks = str(data["reason"])[:500]

	stock_expense_account(doc)
	_apply_gst(doc, employee.branch)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	value = abs(flt(doc.rounded_total) or flt(doc.grand_total))
	return {
		"debit_note": doc.name,
		"kind": kind,
		"supplier": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"amount": value,
		"tax": abs(flt(doc.total_taxes_and_charges)),
		"outstanding": flt(doc.outstanding_amount),
		# What this took off the supplier's account, which is the number the
		# counter is actually watching.
		"supplier_outstanding": _owed(supplier),
		"print_url": f"/printview?doctype=Purchase%20Invoice&name={doc.name}",
	}


def _owed(supplier: str) -> float:
	"""What the shop still owes this supplier, across every branch."""
	return flt(frappe.db.sql("""
		select ifnull(sum(gle.credit - gle.debit), 0)
		from `tabGL Entry` gle
		where gle.party_type = 'Supplier' and gle.party = %s
		  and gle.is_cancelled = 0
	""", supplier)[0][0])


def _apply_gst(doc, branch: str) -> None:
	"""Input GST on the note, the way the supplier's own bill carried it.

	Both kinds need it and neither had it. Goods going back must reverse the
	credit taken when they came in, and a scheme is settled on a tax document —
	the distributor's copy shows CGST and SGST on the face of it. Without this
	the note went out at the bare amount and the two sides never agreed.

	Nothing is applied when no line is taxable, which is how a note made only of
	zero-rated adjustments stays at its face value.
	"""
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

	# A note that mixes rates needs each line to carry its own, or ERPNext taxes
	# the whole document at the highest one on it.
	for line in doc.get("items") or []:
		line_rate = tax.item_rate(line.item_code)
		if line_rate and int(line_rate) != int(rate):
			per_line = tax.template_for_rate(line_rate)
			if per_line:
				line.item_tax_template = per_line
