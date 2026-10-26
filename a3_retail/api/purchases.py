# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch purchase entry (`/retail/purchases`).

The shop buys from distributors at the counter — a rep walks in with stock and a
bill. Until now that had to go to head office, which is why five weeks of stock
arrived in the old system with no inward document at all and the books could only
be corrected by counting.

One document does the job: a Purchase Invoice with `update_stock = 1`. It records
what the supplier is owed and brings the goods into the branch warehouse at the
price actually paid, so valuation follows real cost instead of a guess. A
Purchase Order is not required — the goods are already here.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission, stamp_cost_center
from a3_retail.api.customer import validate_pan
from a3_retail.api.pos import _profile
from a3_retail.api.staff import _me

LINE_LIMIT = 100


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the screen needs before the first keystroke."""
	employee = _me()
	profile = _profile(employee.branch)
	return {
		"branch": employee.branch,
		"warehouse": profile.default_warehouse,
		"can_create": bool(frappe.has_permission("Purchase Invoice", "create")),
		"modes": frappe.get_all(
			"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name"
		),
		# Whether the distributor's own bill number has to be on the document.
		# It is a GST setting, so the screen asks rather than assumes.
		"bill_no_required": bool(
			frappe.db.get_single_value("GST Settings", "require_supplier_invoice_no")),
	}


@frappe.whitelist()
def catalogue(query: str = "", item_group: str | None = None, limit: int = 40) -> list[dict]:
	"""The catalogue as the buyer needs to see it, for the add-items picker.

	Buying asks a different question of the same item master than selling does.
	At the till you want the price and whether there is one left; with a rep at
	the counter you want what it costs, what it sells for and how many are on the
	shelf, all three at once — that is the comparison that decides whether this
	line goes on the bill. So the row carries both prices rather than one.

	The search is the one the rep's own paperwork uses: a name, the code on the
	box, an HSN, or an IMEI off a carton.
	"""
	employee = _me()
	require_permission("Item", "read")
	profile = _profile(employee.branch)

	conditions = ["i.disabled = 0", "ifnull(i.is_purchase_item, 1) = 1",
	              "ifnull(i.is_fixed_asset, 0) = 0"]
	values = {"branch": employee.branch, "limit": min(cint(limit) or 40, 100),
	          "selling": profile.default_price_list or "Standard Selling"}

	if query:
		from a3_retail.utils.compatibility import serial_clause

		conditions.append(
			"(i.name like %(query)s or i.item_name like %(query)s or i.brand like %(query)s"
			" or i.gst_hsn_code like %(query)s"
			" or exists (select 1 from `tabItem Barcode` bc"
			"            where bc.parent = i.name and bc.barcode like %(query)s)"
			f" or {serial_clause('i', 'query', 'branch')})"
		)
		values["query"] = f"%{query}%"
	if item_group:
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = item_group

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.gst_hsn_code as hsn,
		       ifnull(i.has_serial_no, 0) as has_serial, i.stock_uom as uom,
		       ifnull(mine.qty, 0) as stock,
		       ifnull(sell.price_list_rate, i.standard_rate) as sales_price,
		       ifnull(buy.price_list_rate, i.last_purchase_rate) as purchase_price,
		       (select bc.barcode from `tabItem Barcode` bc
		        where bc.parent = i.name order by bc.idx limit 1) as barcode
		from `tabItem` i
		left join (
			select b.item_code, sum(b.actual_qty) qty
			from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
			where w.custom_branch = %(branch)s group by b.item_code
		) mine on mine.item_code = i.name
		left join `tabItem Price` sell on sell.item_code = i.name
			and sell.price_list = %(selling)s and ifnull(sell.selling, 1) = 1
		left join `tabItem Price` buy on buy.item_code = i.name
			and buy.price_list = 'Standard Buying' and ifnull(buy.buying, 1) = 1
		where {" and ".join(conditions)}
		order by (ifnull(mine.qty, 0) > 0) desc, i.item_name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)
	from a3_retail.utils import tax

	for row in rows:
		row["stock"] = flt(row.stock)
		row["sales_price"] = flt(row.sales_price)
		row["purchase_price"] = flt(row.purchase_price)
		# The rate the bill will be taxed at, so the screen can show the figure
		# the rep is reading off their own invoice rather than the net.
		row["gst_rate"] = flt(tax.item_rate(row.item_code))
	return rows


@frappe.whitelist()
def search_suppliers(query: str = "", limit: int = 10) -> list[dict]:
	"""Find the distributor by name or phone."""
	_me()
	require_permission("Supplier", "read")

	like = f"%{(query or '').strip()}%"
	rows = frappe.db.sql(
		"""
		select name, supplier_name, mobile_no, gstin
		from `tabSupplier`
		where disabled = 0 and (supplier_name like %(q)s or name like %(q)s
		      or ifnull(mobile_no,'') like %(q)s)
		order by supplier_name limit %(limit)s
		""",
		{"q": like, "limit": min(cint(limit) or 10, 50)},
		as_dict=True,
	)
	# Whether they are registered decides whether the bill carries GST at all,
	# so the screen is told up front rather than finding out on save.
	return [{"name": r.name, "supplier_name": r.supplier_name,
	         "mobile_no": r.mobile_no, "registered": bool(r.gstin)}
	        for r in rows]


@frappe.whitelist()
def gstin_info(gstin: str) -> dict:
	"""Look a GSTIN up so the counter does not retype the distributor's details.

	india_compliance's own endpoint refuses anyone without desk access, and
	branch staff are Website Users by design — so the caller is guarded here and
	the lookup itself is shared with the customer screen, since a GST number
	means the same thing on either side of the counter.
	"""
	_me()
	require_permission("Supplier", "create")

	from a3_retail.api.customer import gstin_details

	out = gstin_details(gstin)
	if out.get("party_name"):
		out["supplier_name"] = out["party_name"]
	return out


@frappe.whitelist()
def create_supplier(supplier_name: str, mobile_no: str | None = None,
                    gstin: str | None = None, address_line1: str | None = None,
                    city: str | None = None, state: str | None = None,
                    pincode: str | None = None, pan: str | None = None) -> dict:
	"""A rep the shop has not bought from before."""
	_me()
	require_permission("Supplier", "create")

	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw(_("Give the supplier a name."), title=_("Supplier"))

	gstin = (gstin or "").strip().upper() or None
	if gstin:
		from india_compliance.gst_india.utils import validate_gstin

		validate_gstin(gstin)
		held = frappe.db.get_value("Supplier", {"gstin": gstin},
		                           ["name", "supplier_name"], as_dict=True) \
			if frappe.db.has_column("Supplier", "gstin") else None
		if held:
			return {"name": held.name, "supplier_name": held.supplier_name, "created": False}

	existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
	if existing:
		return {"name": existing, "supplier_name": supplier_name, "created": False}

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = supplier_name
	if mobile_no and doc.meta.has_field("mobile_no"):
		doc.mobile_no = str(mobile_no).strip()
	if gstin and doc.meta.has_field("gstin"):
		doc.gstin = gstin
	if doc.meta.has_field("pan"):
		# A GSTIN carries the PAN as characters three to twelve, so a registered
		# dealer never has to be asked for it twice.
		doc.pan = validate_pan(pan) or (gstin[2:12] if gstin else "") or None
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)

	if address_line1 or city or pincode:
		_supplier_address(doc.name, supplier_name, gstin, address_line1, city, state, pincode)

	return {"name": doc.name, "supplier_name": supplier_name, "created": True}


def _supplier_address(supplier, title, gstin, line1, city, state, pincode) -> None:
	"""Where the distributor bills from — needed for the GST place of supply."""
	addr = frappe.new_doc("Address")
	addr.address_title = title[:100]
	addr.address_type = "Billing"
	addr.address_line1 = (line1 or "-")[:240]
	addr.city = (city or "-")[:100]
	if state:
		addr.state = state
	if pincode:
		addr.pincode = str(pincode)[:10]
	addr.country = "India"
	if gstin and addr.meta.has_field("gstin"):
		addr.gstin = gstin
	addr.append("links", {"link_doctype": "Supplier", "link_name": supplier})
	addr.flags.ignore_permissions = True
	addr.flags.ignore_mandatory = True
	try:
		addr.insert(ignore_permissions=True)
	except Exception:
		# An address that will not save must not lose the supplier with it.
		frappe.clear_last_message()
		frappe.log_error(frappe.get_traceback(), "A3 Retail: supplier address")


@frappe.whitelist()
def recent(limit: int = 30) -> dict:
	"""What this branch has bought, newest first."""
	employee = _me()
	require_permission("Purchase Invoice", "read")

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		return {"branch": employee.branch, "rows": []}

	rows = frappe.db.sql(
		"""
		select pi.name, pi.posting_date, pi.supplier, pi.bill_no, pi.grand_total,
		       pi.outstanding_amount, pi.status, pi.docstatus,
		       (select count(*) from `tabPurchase Invoice Item` it
		         where it.parent = pi.name) as line_count
		from `tabPurchase Invoice` pi
		where pi.docstatus < 2 and exists (
		      select 1 from `tabPurchase Invoice Item` it
		       where it.parent = pi.name and it.warehouse = %(warehouse)s)
		order by pi.posting_date desc, pi.creation desc
		limit %(limit)s
		""",
		{"warehouse": warehouse, "limit": min(cint(limit) or 30, 100)},
		as_dict=True,
	)
	for r in rows:
		r["supplier_name"] = frappe.db.get_value("Supplier", r["supplier"], "supplier_name")
		r["grand_total"] = flt(r["grand_total"])
		r["outstanding_amount"] = flt(r["outstanding_amount"])
	return {"branch": employee.branch, "rows": rows}


@frappe.whitelist()
def create(payload) -> dict:
	"""Record a supplier bill and take the goods into stock."""
	employee = _me()
	require_permission("Purchase Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})

	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Choose who the stock was bought from."), title=_("Supplier"))

	items = [row for row in (data.get("items") or [])
	         if row.get("item_code") and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Add at least one item, with how many came in."), title=_("Items"))
	if len(items) > LINE_LIMIT:
		frappe.throw(_("That is more lines than one bill should carry."), title=_("Items"))

	bill_no = (data.get("bill_no") or "").strip()
	# The supplier's own invoice number is what the input credit is claimed
	# against, so GST Settings makes it compulsory for a registered dealer.
	# Saying so here beats the document refusing it afterwards in the compliance
	# app's words. An unregistered dealer is exempt — there is no credit to claim
	# and the slip they hand over often has no number on it at all.
	if not bill_no and _bill_no_required(supplier):
		frappe.throw(
			_("Put the number from the distributor's own bill in — the input GST "
			  "is claimed against it."),
			title=_("Supplier bill number"),
		)

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A purchase cannot be dated in the future."), title=_("Date"))

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		frappe.throw(_("This branch has no store to receive stock into."), title=_("Warehouse"))
	cost_center = profile.sales_cost_center or profile.cost_center

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.bill_no = bill_no or None
	doc.bill_date = posting
	# One document, not three: the goods are standing in the shop, so the bill
	# brings them into stock as it is entered.
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch

	stock_account = _stock_account(doc.company, warehouse)
	priced: dict[str, float] = {}
	for row in items:
		code = row["item_code"]
		if not frappe.db.exists("Item", code):
			frappe.throw(_("{0} is not an item we stock.").format(code), title=_("Items"))
		line = doc.append("items", {
			"item_code": code,
			"qty": flt(row["qty"]),
			"rate": flt(row.get("rate")),
			"warehouse": warehouse,
		})
		if cost_center:
			line.cost_center = cost_center
		# The goods come straight into stock on this document, so the other side
		# is the stock account. Left alone, ERPNext fills in "Stock Received But
		# Not Billed", corrects itself on save and tells the counter about it in
		# a sentence nobody at a counter can act on.
		if stock_account:
			line.expense_account = stock_account
		serials = [s for s in (row.get("serials") or []) if s]
		if serials:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serials)
		priced[code] = flt(row.get("selling_rate"))

	if cost_center and doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center
	if data.get("notes"):
		doc.remarks = str(data["notes"])[:500]

	_apply_tax(doc, employee)

	# After the taxes, not before: get_taxes_and_charges copies the template's
	# rows verbatim and they carry the company's main cost center. Left there,
	# the GST misses the branch's own P&L — and, because a cost center outside
	# the counter's allowed set makes the whole document unreadable to them,
	# the bill they just raised cannot be read back or printed.
	stamp_cost_center(doc, cost_center)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	# What the shop last paid, kept on the item so the next purchase of it opens
	# with the right figure instead of a blank box.
	from a3_retail.api.stock_control import set_buying_rate, set_selling_rate

	for row in doc.items:
		set_buying_rate(row.item_code, flt(row.rate))
		if flt(priced.get(row.item_code)) > 0:
			set_selling_rate(row.item_code, flt(priced[row.item_code]), employee.branch)

	_stamp_serials(doc, priced)

	# Paid on the spot, or left on the supplier's account to settle later.
	paid = flt(data.get("paid_amount"))
	if paid > 0:
		_settle(doc, paid, data.get("mode_of_payment") or "Cash", employee)

	doc.reload()
	return {
		"purchase": doc.name,
		"supplier": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"grand_total": flt(doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		# Named, or the browser falls back to ERPNext's standard sheet rather
		# than the one the shop files.
		"print_url": f"/printview?doctype=Purchase%20Invoice&name={doc.name}"
		             f"&format=A3%20Purchase%20Invoice&no_letterhead=0",
	}


def _bill_no_required(supplier: str) -> bool:
	"""Whether this supplier's own bill number has to be recorded."""
	if not frappe.db.get_single_value("GST Settings", "require_supplier_invoice_no"):
		return False
	return frappe.db.get_value("Supplier", supplier, "gst_category") != "Unregistered"


def _stock_account(company: str, warehouse: str) -> str | None:
	"""Where the value of the goods lands when they come in.

	The warehouse's own account if it has one, otherwise the company's — which
	is the same account here, since this chain keeps one Stock In Hand.
	"""
	if not frappe.get_cached_value("Company", company, "enable_perpetual_inventory"):
		return None
	return frappe.db.get_value("Warehouse", warehouse, "account") \
		or frappe.get_cached_value("Company", company, "default_inventory_account")


def _apply_tax(doc, employee) -> None:
	"""Put GST on the bill, the way the distributor's own bill carries it.

	A purchase rate is quoted before tax — the rep's invoice reads 81,271.19 a
	handset and 95,900 to pay — so a bill entered without GST understates what
	the supplier is owed and claims no input credit at all. Both halves of that
	matter: the first is money, the second is money too, later.

	In-state buying splits into CGST and SGST; from another state it is one
	IGST line. Which it is comes off the supplier's own GSTIN, since that is
	where the goods are being billed from.
	"""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	from a3_retail.utils import tax

	rate = tax.bill_rate(doc.get("items"))
	if not rate:
		return

	template = tax.input_gst_template(doc.company, employee.branch, doc.supplier, rate)
	if not template:
		return

	doc.taxes_and_charges = template
	doc.set("taxes", [])
	for row in get_taxes_and_charges("Purchase Taxes and Charges Template", template):
		doc.append("taxes", row)


def _settle(invoice, paid: float, mode: str, employee) -> None:
	"""Pay the rep now — a Payment Entry against the bill just recorded."""
	from a3_retail.utils.payments import settle_bill

	settle_bill(invoice, paid, mode, invoice.get("cost_center"))


def _stamp_serials(invoice, priced: dict) -> None:
	"""Write what each piece cost, what it is priced at, and when it arrived.

	A shop buys the same handset at several costs through the year and prices
	each intake differently, so the figures belong on the piece. Without them the
	counter picking an IMEI is choosing blind between stock that is not worth the
	same money.
	"""
	for row in invoice.items:
		serials = [s.strip() for s in (row.serial_no or "").splitlines() if s.strip()]
		if not serials:
			continue
		selling = flt(priced.get(row.item_code)) or _current_selling(row.item_code)
		# Only the columns the site actually has. A deploy can land before its
		# migration, and a purchase that will not save because a field has not
		# been added yet is a worse outcome than one recorded without the
		# per-piece figures — the stock still comes in either way.
		wanted = {
			"a3_purchase_cost": flt(row.rate),
			"a3_selling_price": selling,
			"a3_received_on": invoice.posting_date,
		}
		stamp = {field: value for field, value in wanted.items()
		         if frappe.db.has_column("Serial No", field)}
		if not stamp:
			continue
		for serial in serials:
			if not frappe.db.exists("Serial No", serial):
				continue
			frappe.db.set_value("Serial No", serial, stamp, update_modified=False)


def _current_selling(item_code: str) -> float:
	return flt(frappe.db.get_value(
		"Item Price", {"item_code": item_code, "selling": 1}, "price_list_rate"))
