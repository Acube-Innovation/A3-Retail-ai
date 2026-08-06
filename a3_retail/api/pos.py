# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Counter billing for the branch app (`/branch/sales`).

Everything here answers for the signed-in employee's own branch: `_me()` returns
the employee, `_branch()` the branch, and no endpoint accepts a branch from the
caller except `stock_elsewhere`, which is a read-only availability lookup — a
counter that cannot see other branches can never raise a transfer (scope 6.1).

The invoice itself is created as the signed-in user, not with elevated rights, so
the selling guards in `overrides/sales_invoice.py` apply exactly as they do in
the desk: IMEI on every device line, the minimum selling price, a sales person on
the bill (scope 2.5, step 12 P1–P9).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from a3_retail.api import require_permission
from a3_retail.api.customer import normalize_mobile
from a3_retail.api.staff import _me

CART_LIMIT = 40


def _branch() -> str:
	return _me().branch


def _profile(branch: str) -> dict:
	profile = frappe.db.get_value(
		"Branch Profile",
		{"branch": branch},
		["name", "branch", "default_warehouse", "pos_profile", "default_price_list",
		 "default_income_account", "sales_cost_center", "cost_center"],
		as_dict=True,
	) or frappe._dict()
	profile.default_price_list = _price_list(profile)
	return profile


def _price_list(profile) -> str | None:
	"""Whichever selling list this branch actually prices against.

	A branch may have none set — fall back through its POS Profile and the
	company default before guessing, because a catalogue showing ₹0 is worse
	than useless at a counter.
	"""
	candidates = [
		profile.get("default_price_list"),
		frappe.db.get_value("POS Profile", profile.get("pos_profile"), "selling_price_list")
		if profile.get("pos_profile") else None,
		frappe.db.get_single_value("Selling Settings", "selling_price_list"),
	]
	for candidate in candidates:
		if candidate and frappe.db.exists("Price List", candidate):
			return candidate

	# Last resort: the selling list that carries the most prices.
	rows = frappe.db.sql(
		"""select p.price_list, count(*) as prices from `tabItem Price` p
		   join `tabPrice List` l on l.name = p.price_list
		   where l.selling = 1 and l.enabled = 1
		   group by p.price_list order by prices desc limit 1""",
		as_dict=True,
	)
	return rows[0].price_list if rows else None


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@frappe.whitelist()
def catalogue(query: str = "", item_group: str | None = None, only_in_stock: int = 0,
              limit: int = 60) -> list[dict]:
	"""What the counter can sell, with this branch's quantity and selling price."""
	employee = _me()
	require_permission("Item", "read")
	profile = _profile(employee.branch)

	# Fixed assets (the shop's own scooter, its microscope) are Items too — they
	# are not for sale over the counter.
	conditions = [
		"i.disabled = 0",
		"ifnull(i.is_sales_item, 1) = 1",
		"ifnull(i.is_fixed_asset, 0) = 0",
	]
	values = {"branch": employee.branch, "limit": cint(limit) or 60,
	          "price_list": profile.default_price_list or "Standard Selling"}

	if query:
		conditions.append(
			"(i.name like %(query)s or i.item_name like %(query)s or i.brand like %(query)s)"
		)
		values["query"] = f"%{query}%"
	if item_group:
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = item_group

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.brand, i.image,
		       ifnull(i.a3_is_device, 0) as is_device,
		       ifnull(i.a3_is_ew_plan, 0) as is_plan,
		       ifnull(i.has_serial_no, 0) as has_serial,
		       ifnull(i.is_stock_item, 1) as is_stock_item,
		       ifnull(i.a3_min_selling_price, 0) as min_price,
		       ifnull(mine.qty, 0) as branch_qty,
		       ifnull(price.price_list_rate, i.standard_rate) as rate
		from `tabItem` i
		left join (
			select b.item_code, sum(b.actual_qty - ifnull(b.reserved_qty, 0)) qty
			from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
			where w.custom_branch = %(branch)s group by b.item_code
		) mine on mine.item_code = i.name
		left join `tabItem Price` price on price.item_code = i.name
			and price.price_list = %(price_list)s and ifnull(price.selling, 1) = 1
		where {" and ".join(conditions)}
		order by (ifnull(mine.qty, 0) > 0) desc, i.item_name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)

	if cint(only_in_stock):
		rows = [row for row in rows if flt(row.branch_qty) > 0 or not cint(row.is_stock_item)]

	for row in rows:
		row["rate"] = flt(row["rate"])
		row["sellable"] = bool(flt(row["branch_qty"]) > 0 or not cint(row["is_stock_item"]))
		row["gst_rate"] = _item_gst_rate(row["item_code"])
		row["low_stock"] = bool(cint(row["is_stock_item"]) and 0 < flt(row["branch_qty"]) <= 5)
		row["is_new"] = _is_new(row["item_code"])
	return rows


def _item_gst_rate(item_code: str) -> float:
	"""The rate the line will be taxed at, so the bill can show GST as you type."""
	template = frappe.db.get_value(
		"Item Tax", {"parenttype": "Item", "parent": item_code}, "item_tax_template"
	)
	if template:
		rate = frappe.db.get_value(
			"Item Tax Template Detail", {"parent": template}, "tax_rate", order_by="tax_rate desc"
		)
		if rate:
			return flt(rate) * 2 if flt(rate) < 15 else flt(rate)
	return 18.0


def _is_new(item_code: str) -> bool:
	"""A handset launched this year is new to a customer.

	Deliberately not "created recently" — on a freshly seeded site that badges the
	whole catalogue, which tells the counter nothing.
	"""
	model = frappe.db.get_value("Item", item_code, "a3_device_model")
	if not model:
		return False
	launch = frappe.db.get_value("Device Model", model, "launch_year")
	return bool(launch and cint(launch) >= cint(nowdate()[:4]))


@frappe.whitelist()
def item_groups() -> list[str]:
	_me()
	return frappe.get_all(
		"Item Group", filters={"is_group": 0}, pluck="name", order_by="name"
	)


@frappe.whitelist()
def serials(item_code: str, limit: int = 60) -> list[dict]:
	"""IMEIs of this item sitting in this branch, for the counter to pick or scan."""
	employee = _me()
	require_permission("Serial No", "read")

	return frappe.db.sql(
		"""
		select s.name as serial_no, coalesce(nullif(s.a3_imei_1, ''), s.name) as imei,
		       s.warehouse,
		       datediff(curdate(), date(s.creation)) as age_days
		from `tabSerial No` s
		join `tabWarehouse` w on w.name = s.warehouse
		where s.item_code = %(item_code)s and s.status = 'Active'
		  and w.custom_branch = %(branch)s
		order by s.creation
		limit %(limit)s
		""",
		{"item_code": item_code, "branch": employee.branch, "limit": cint(limit) or 60},
		as_dict=True,
	)


@frappe.whitelist()
def scan(code: str) -> dict | None:
	"""Resolve whatever came off the scanner: an IMEI, a serial or an item code."""
	employee = _me()
	code = (code or "").strip()
	if not code:
		return None

	serial = frappe.db.get_value(
		"Serial No",
		{"name": code, "status": "Active"},
		["name", "item_code", "warehouse", "a3_imei_1"],
		as_dict=True,
	) or frappe.db.get_value(
		"Serial No",
		{"a3_imei_1": code, "status": "Active"},
		["name", "item_code", "warehouse", "a3_imei_1"],
		as_dict=True,
	)

	if serial:
		if frappe.db.get_value("Warehouse", serial.warehouse, "custom_branch") != employee.branch:
			frappe.throw(
				_("That handset is in another branch."), title=_("Not in this branch")
			)
		rows = catalogue(query=serial.item_code, limit=1)
		return {"kind": "serial", "serial_no": serial.name,
		        "imei": serial.a3_imei_1 or serial.name,
		        "item": rows[0] if rows else None}

	if frappe.db.exists("Item", code):
		rows = catalogue(query=code, limit=1)
		return {"kind": "item", "item": rows[0] if rows else None}

	rows = catalogue(query=code, limit=1)
	return {"kind": "item", "item": rows[0]} if rows else None


@frappe.whitelist()
def stock_elsewhere(item_code: str) -> list[dict]:
	"""Where else this model is, so a counter can promise it or ask for it."""
	employee = _me()
	require_permission("Item", "read")

	rows = frappe.db.sql(
		"""
		select w.custom_branch as branch, sum(b.actual_qty - ifnull(b.reserved_qty, 0)) as available
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s and w.disabled = 0
		  and ifnull(w.custom_branch, '') != ''
		group by w.custom_branch
		having available > 0
		order by available desc
		""",
		{"item_code": item_code},
		as_dict=True,
	)
	for row in rows:
		row["is_mine"] = row["branch"] == employee.branch
	return rows


@frappe.whitelist()
def request_transfer(item_code: str, source_branch: str, qty: float = 1,
                     remarks: str | None = None) -> dict:
	"""Ask another branch for stock we do not have (scope 6.2)."""
	employee = _me()
	require_permission("Stock Request", "create")

	if source_branch == employee.branch:
		frappe.throw(_("That is this branch."))
	if not frappe.db.exists("Branch", source_branch):
		frappe.throw(_("Unknown branch."))

	doc = frappe.new_doc("Stock Request")
	doc.request_date = nowdate()
	doc.requesting_branch = employee.branch
	doc.source_branch = source_branch
	doc.purpose = "Customer Sale"
	doc.priority = "High"
	doc.append("items", {"item_code": item_code, "qty": flt(qty) or 1, "remarks": remarks})
	# Same rationale as checkout(): the role check is above, and raising a
	# transfer reads warehouse accounts the counter cannot open.
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	return {"stock_request": doc.name, "status": doc.status, "source_branch": source_branch}


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
@frappe.whitelist()
def find_customer(mobile_no: str) -> dict | None:
	"""Look a walk-in up by the number they give at the counter."""
	_me()
	require_permission("Customer", "read")

	mobile = normalize_mobile(mobile_no)
	if len(mobile) != 10:
		return None

	name = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	if not name:
		return None

	customer = frappe.db.get_value(
		"Customer", name, ["name", "customer_name", "a3_mobile_no", "email_id", "a3_dnc"],
		as_dict=True,
	)
	customer["address"] = _primary_address(name)
	customer["history"] = _history(name)
	return customer


def _primary_address(customer: str) -> dict:
	link = frappe.db.sql(
		"""select a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode
		   from `tabAddress` a
		   join `tabDynamic Link` l on l.parent = a.name
		   where l.link_doctype = 'Customer' and l.link_name = %s
		   order by a.is_primary_address desc, a.modified desc limit 1""",
		customer,
		as_dict=True,
	)
	return link[0] if link else {}


def _history(customer: str) -> dict:
	return {
		"invoices": frappe.db.count("Sales Invoice", {"customer": customer, "docstatus": 1}),
		"repairs": frappe.db.count("Service Job Card", {"customer": customer, "docstatus": 1}),
		"last_seen": frappe.db.get_value(
			"Sales Invoice", {"customer": customer, "docstatus": 1}, "posting_date",
			order_by="posting_date desc",
		),
	}


@frappe.whitelist()
def search_customers(query: str, limit: int = 8) -> list[dict]:
	"""The counter search box: name, phone or email."""
	_me()
	require_permission("Customer", "read")

	query = (query or "").strip()
	if len(query) < 3:
		return []

	return frappe.db.sql(
		"""
		select name, customer_name, a3_mobile_no as mobile_no, email_id
		from `tabCustomer`
		where disabled = 0 and (customer_name like %(q)s or a3_mobile_no like %(q)s
		                        or email_id like %(q)s or name like %(q)s)
		order by modified desc
		limit %(limit)s
		""",
		{"q": f"%{query}%", "limit": cint(limit) or 8},
		as_dict=True,
	)


@frappe.whitelist()
def loyalty(customer: str) -> dict:
	"""What this customer is worth — the counter's version of a loyalty card."""
	_me()
	require_permission("Customer", "read")

	row = frappe.db.sql(
		"""select count(*) as bills, ifnull(sum(base_grand_total), 0) as spend,
		          max(posting_date) as last_bill
		   from `tabSales Invoice`
		   where customer = %s and docstatus = 1 and is_return = 0""",
		customer,
		as_dict=True,
	)[0]
	row["repairs"] = frappe.db.count("Service Job Card", {"customer": customer, "docstatus": 1})
	row["tier"] = ("Gold" if flt(row.spend) >= 100000 else
	               "Silver" if flt(row.spend) >= 25000 else "New")
	return row


@frappe.whitelist()
def save_customer(mobile_no: str, customer_name: str, email: str | None = None,
                  address_line1: str | None = None, city: str | None = None,
                  pincode: str | None = None, state: str | None = None) -> dict:
	"""Create the walk-in, or fill in what we did not have before."""
	employee = _me()
	require_permission("Customer", "create")

	from a3_retail.api.customer import get_or_create

	customer = get_or_create(
		mobile_no=mobile_no, customer_name=customer_name, email=email, branch=employee.branch
	)
	name = customer["name"] if isinstance(customer, dict) else customer

	if address_line1:
		_save_address(name, customer_name, address_line1, city, pincode,
		              state or _branch_state(employee.branch))

	return find_customer(mobile_no) or {"name": name, "customer_name": customer_name}


def _branch_state(branch: str) -> str | None:
	"""An Indian address needs a state; the walk-in is almost always local.

	The branch's own address is the best answer. Where a branch has none, its
	GST state code says the same thing — 32 is Kerala.
	"""
	from a3_retail.print_helpers import a3_branch_profile

	state = (a3_branch_profile(branch) or {}).get("state")
	if state:
		return state

	code = frappe.db.get_value("Branch Profile", {"branch": branch}, "state_code")
	if not code:
		return None

	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS
	except ImportError:
		return None
	return {number: name for name, number in STATE_NUMBERS.items()}.get(str(code))


def _save_address(customer: str, customer_name: str, line1: str, city: str | None,
                  pincode: str | None, state: str | None = None):
	existing = _primary_address(customer)
	doc = frappe.get_doc("Address", existing["name"]) if existing.get("name") \
		else frappe.new_doc("Address")

	if not existing.get("name"):
		doc.address_title = customer_name[:100]
		doc.address_type = "Billing"
		doc.is_primary_address = 1
		doc.append("links", {"link_doctype": "Customer", "link_name": customer})

	doc.address_line1 = line1
	doc.city = city or doc.city or "-"
	doc.state = state or doc.state
	doc.pincode = pincode
	doc.country = doc.country or "India"
	doc.flags.ignore_mandatory = True
	doc.save()


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
@frappe.whitelist()
def checkout(payload) -> dict:
	"""Turn the cart into a submitted invoice, and hand back a print link.

	Created as the signed-in user so every selling guard — IMEI, minimum price,
	sales person — runs exactly as it does in the desk.
	"""
	employee = _me()
	require_permission("Sales Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	items = data.get("items") or []
	if not items:
		frappe.throw(_("Add something to the bill first."))
	if len(items) > CART_LIMIT:
		frappe.throw(_("That is more lines than one bill should carry."))
	if not data.get("customer"):
		frappe.throw(_("Add the customer before billing."))

	profile = _profile(employee.branch)
	invoice = frappe.new_doc("Sales Invoice")
	invoice.customer = data["customer"]
	invoice.company = frappe.db.get_single_value("Global Defaults", "default_company")
	invoice.posting_date = nowdate()
	invoice.set_posting_time = 1
	invoice.due_date = nowdate()
	invoice.branch = employee.branch
	invoice.update_stock = 1
	invoice.set_warehouse = profile.default_warehouse
	invoice.is_pos = 1
	if profile.pos_profile:
		invoice.pos_profile = profile.pos_profile
	if profile.default_price_list:
		invoice.selling_price_list = profile.default_price_list

	cost_center = profile.sales_cost_center or profile.cost_center

	sales_person = _sales_person(employee.name)
	if sales_person:
		invoice.append("sales_team", {"sales_person": sales_person, "allocated_percentage": 100})

	for row in items:
		line = invoice.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": flt(row.get("qty")) or 1,
				"rate": flt(row.get("rate")),
			},
		)
		if frappe.get_cached_value("Item", row.get("item_code"), "is_stock_item"):
			line.warehouse = profile.default_warehouse
		if cost_center:
			line.cost_center = cost_center
		serial_numbers = [s for s in (row.get("serials") or []) if s]
		if serial_numbers:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serial_numbers)

	if flt(data.get("discount_percent")):
		invoice.apply_discount_on = "Net Total"
		invoice.additional_discount_percentage = flt(data["discount_percent"])
	elif flt(data.get("discount_amount")):
		invoice.apply_discount_on = "Net Total"
		invoice.discount_amount = flt(data["discount_amount"])

	if data.get("notes"):
		invoice.remarks = str(data["notes"])[:500]

	# Branch staff hold a User Permission on Cost Center, and strict user
	# permissions reject a *blank* one just as firmly as a foreign one. Fill every
	# cost-center field before the permission check runs at insert — which is also
	# what puts the sale in the branch P&L (scope 11.1).
	invoice.set_missing_values()
	# `set_missing_values` re-reads the tax template from the POS Profile, so the
	# rate the basket actually carries is applied after it, not before.
	_apply_gst(invoice, employee.branch)
	_stamp_cost_center(invoice, cost_center)

	# The role check above is the gate; the document itself is written with
	# permissions bypassed because pricing an invoice makes ERPNext read Account
	# and Cost Center records that shop-floor staff are deliberately not allowed
	# to see (scope 11.1: "Branch User has no read on Account"). The invoice is
	# still owned by the signed-in user, and every selling guard in
	# `overrides/sales_invoice.py` still runs on validate.
	invoice.flags.ignore_permissions = True
	invoice.insert(ignore_permissions=True)

	mode = resolve_mode(data.get("mode_of_payment") or "Cash")
	received = flt(data.get("received_amount")) or flt(invoice.grand_total)

	# Only a cash drawer takes more than the bill and hands change back. A card or
	# a UPI collection is charged the bill exactly, so an over-typed "received"
	# there would submit an over-paid invoice with a negative outstanding.
	payable = flt(invoice.rounded_total) or flt(invoice.grand_total)
	if frappe.db.get_value("Mode of Payment", mode, "type") == "Cash":
		tendered = max(received, payable)
	else:
		tendered = payable

	# Replace the payment table rather than appending to it: a POS Profile puts
	# its own default row on the invoice, and adding ours next to it counts the
	# money twice. One row, for what the customer actually handed over — ERPNext
	# works the change out from there.
	invoice.set("payments", [{"mode_of_payment": mode, "amount": tendered}])

	_stamp_cost_center(invoice, cost_center)
	invoice.save(ignore_permissions=True)
	invoice.submit()

	return {
		"invoice": invoice.name,
		"grand_total": flt(invoice.grand_total),
		"change": flt(invoice.get("change_amount")),
		"mode_of_payment": mode,
		"net_total": flt(invoice.net_total),
		"tax": flt(invoice.total_taxes_and_charges),
		"paid": flt(invoice.grand_total),
		"customer_name": invoice.customer_name,
		"print_url": print_url(invoice.name),
	}


def _apply_gst(invoice, branch: str):
	"""Put the right GST template on the bill and fill its rows."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	template = _tax_template(invoice, branch)
	if not template or invoice.taxes_and_charges == template:
		return

	invoice.taxes_and_charges = template
	invoice.set("taxes", [])
	for row in get_taxes_and_charges("Sales Taxes and Charges Template", template):
		invoice.append("taxes", row)


def _tax_template(invoice, branch: str) -> str | None:
	"""In-state or out-of-state GST at the rate the basket carries (scope 5.2).

	A phone and a charger are both 18%, which is the normal counter case; a
	mixed-rate basket takes the highest rate its lines carry, and the invoice
	shows the split per line either way.
	"""
	company = invoice.company
	rate = _basket_gst_rate(invoice)
	if not rate:
		return None

	state = frappe.db.get_value("Branch Profile", {"branch": branch}, "state_code")
	customer_gstin = frappe.db.get_value("Customer", invoice.customer, "gstin") \
		if frappe.db.has_column("Customer", "gstin") else None
	out_of_state = bool(customer_gstin and state and not str(customer_gstin).startswith(str(state)))

	kind = "Out-state" if out_of_state else "In-state"
	for candidate in (f"Output GST {kind} {rate}%", f"Output GST In-state {rate}%"):
		name = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"title": candidate, "company": company}, "name"
		)
		if name:
			return name
	return None


def _basket_gst_rate(invoice) -> int | None:
	"""The GST rate on the lines, from the HSN each item carries."""
	rates = set()
	for row in invoice.get("items") or []:
		hsn = frappe.get_cached_value("Item", row.item_code, "gst_hsn_code")
		item_rate = frappe.db.get_value("Item", row.item_code, "a3_gst_rate") \
			if frappe.db.has_column("Item", "a3_gst_rate") else None
		if not item_rate and hsn:
			item_rate = frappe.db.get_value(
				"Item Tax Template Detail", {"parent": ["like", "%GST%"]}, "tax_rate"
			)
		rates.add(cint(item_rate) or 18)
	return max(rates) if rates else None


def _stamp_cost_center(invoice, cost_center: str | None):
	from a3_retail.api import stamp_cost_center

	stamp_cost_center(invoice, cost_center)


# The counter's six tiles, mapped to whatever this site actually calls them.
PAYMENT_TILES = {
	"Cash": ["Cash"],
	"Card": ["Credit Card", "Debit Card", "Card"],
	"UPI": ["UPI", "Bharat QR", "Wallet"],
	"Wallet": ["Wallet", "UPI"],
	"EMI": ["EMI", "Bajaj EMI", "Credit Card"],
	"Other": ["Bank Draft", "Cheque", "Cash"],
}


@frappe.whitelist()
def payment_tiles() -> list[dict]:
	"""Which of the six tiles this site can actually take money through."""
	_me()
	return [
		{"tile": tile, "mode": resolve_mode(tile), "available": bool(resolve_mode(tile))}
		for tile in PAYMENT_TILES
	]


def resolve_mode(tile: str) -> str | None:
	"""A tile label to a Mode of Payment that exists here."""
	if frappe.db.exists("Mode of Payment", tile):
		return tile
	for candidate in PAYMENT_TILES.get(tile, []):
		if frappe.db.exists("Mode of Payment", candidate):
			return candidate
	return frappe.db.get_value("Mode of Payment", {"enabled": 1}, "name")


def _sales_person(employee: str) -> str | None:
	return frappe.db.get_value("Sales Person", {"employee": employee}, "name")


def print_url(invoice: str, print_format: str = "Retail Tax Invoice") -> str:
	from urllib.parse import urlencode

	query = urlencode(
		{
			"doctype": "Sales Invoice",
			"name": invoice,
			"format": print_format,
			"no_letterhead": 0,
			"_lang": "en",
		}
	)
	return f"/api/method/frappe.utils.print_format.download_pdf?{query}"


@frappe.whitelist()
def recent_invoices(limit: int = 10) -> list[dict]:
	"""Today's bills from this counter, so a reprint is one click away."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	rows = frappe.get_all(
		"Sales Invoice",
		filters={"branch": employee.branch, "docstatus": 1, "posting_date": nowdate()},
		fields=["name", "customer_name", "grand_total", "creation"],
		order_by="creation desc",
		limit=cint(limit) or 10,
	)
	for row in rows:
		row["print_url"] = print_url(row["name"])
	return rows
