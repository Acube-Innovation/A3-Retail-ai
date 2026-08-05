"""Seed 16 — Sales and POS invoices over the last 60 days (scope 14.2, 14.3).

Weekend-weighted, spread across the three branches, with serialised devices,
accessories and extended-warranty plans so the attach-rate and IMEI reports have
something real to read.
"""

import frappe
from frappe.utils import add_days, cint, getdate, nowdate

from a3_retail.utils.imei import luhn_check_digit

INVOICE_COUNT = 45
POS_COUNT = 20

# item, rate, weight — devices first so most baskets carry one
BASKET = [
	("MOB-XIA-N13-6-128", 16999, 5),
	("MOB-SAM-A55-8-128-BLU", 39999, 4),
	("MOB-VIV-T3-8-128", 21499, 3),
	("MOB-APL-15-128-BLK", 69900, 1),
	("TAB-SAM-S9FE", 34999, 1),
]
ACCESSORIES = [("ACC-TGL-A55", 299), ("ACC-CHG-25W-TC", 1499), ("ACC-BUD-XIA", 2199)]
PLANS = [("EW-PLAN-12M", 1999), ("EW-SCR-12M", 2499)]

BRANCHES = ["Kochi", "Kochi", "Kochi", "Thiruvananthapuram", "Kozhikode"]
STOCK_REMARK = "A3 demo sales seed stock"

_imei_sequence = {"next": 6000000}


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if frappe.db.count("Sales Invoice", {"remarks": ["like", "A3 demo %"], "docstatus": 1}) >= INVOICE_COUNT:
		return

	customers = frappe.get_all("Customer", filters={"a3_mobile_no": ["is", "set"]}, pluck="name")
	if not customers:
		return

	_prepare_stock(company)

	for index in range(INVOICE_COUNT):
		_invoice(index, company, customers, is_pos=False)

	for index in range(POS_COUNT):
		_invoice(INVOICE_COUNT + index, company, customers, is_pos=True)


def _prepare_stock(company: str):
	"""One receipt, dated before the oldest demo sale, holding everything it sells.

	Opening stock (seed 07) lands 30 days ago while these invoices go back 60, so
	topping up per invoice would still leave the ledger negative in the past.
	"""
	if frappe.db.exists("Stock Entry", {"remarks": STOCK_REMARK, "docstatus": 1}):
		return

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.company = company
	entry.posting_date = add_days(nowdate(), -70)
	entry.set_posting_time = 1
	entry.remarks = STOCK_REMARK

	for branch in set(BRANCHES):
		warehouse = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
		if not warehouse:
			continue
		for item_code, _rate, _weight in BASKET:
			_receipt_row(entry, item_code, warehouse, 20)
		for item_code, _rate in ACCESSORIES:
			_receipt_row(entry, item_code, warehouse, 150)

	if not entry.get("items"):
		return

	entry.flags.ignore_permissions = True
	try:
		entry.insert(ignore_permissions=True)
		entry.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 demo: sales seed stock")


def _receipt_row(entry, item_code: str, warehouse: str, qty: int):
	if not frappe.db.exists("Item", item_code):
		return
	row = entry.append("items", {"item_code": item_code, "qty": qty, "t_warehouse": warehouse,
	                             "basic_rate": _cost(item_code)})
	if frappe.get_cached_value("Item", item_code, "has_serial_no"):
		row.use_serial_batch_fields = 1
		row.serial_no = "\n".join(_next_imei() for _ in range(qty))


def _posting_date(index: int) -> str:
	"""Spread over 60 days, with weekends carrying more of the volume."""
	day = add_days(getdate(nowdate()), -((index * 7 + index // 5) % 58) - 1)
	if day.weekday() in (5, 6) or index % 3 == 0:
		return str(day)
	return str(add_days(day, -1))


def _invoice(index: int, company: str, customers: list[str], is_pos: bool):
	branch = BRANCHES[index % len(BRANCHES)]
	warehouse = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
	if not warehouse:
		return

	device, rate, _weight = BASKET[index % len(BASKET)]
	accessory, accessory_rate = ACCESSORIES[index % len(ACCESSORIES)]
	posting_date = _posting_date(index)

	doc = frappe.new_doc("Sales Invoice")
	doc.customer = customers[index % len(customers)]
	doc.company = company
	doc.posting_date = posting_date
	doc.set_posting_time = 1
	doc.posting_time = f"{10 + (index % 10)}:{(index * 7) % 60:02d}:00"
	doc.due_date = posting_date
	doc.branch = branch
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	doc.is_pos = 1 if is_pos else 0
	doc.remarks = "A3 demo POS" if is_pos else "A3 demo sales"

	person = _sales_person(branch)
	if person:
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})

	_add_item(doc, device, 1, rate, warehouse)
	# One accessory line only — POS refuses the same item twice on a bill.
	if accessory != device:
		_add_item(doc, accessory, 1 + index % 2, accessory_rate, warehouse)

	if index % 3 == 0:
		plan, plan_rate = PLANS[index % len(PLANS)]
		_add_item(doc, plan, 1, plan_rate, None)

	if is_pos:
		profile = frappe.db.get_value("Branch Profile", {"branch": branch}, "pos_profile")
		if profile:
			doc.pos_profile = profile
		mode = frappe.db.get_value("Mode of Payment", {"name": "Cash"}, "name") or "Cash"
		doc.append("payments", {"mode_of_payment": mode, "amount": 0})

	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
		if is_pos and doc.get("payments"):
			doc.payments[0].amount = doc.grand_total
			doc.save(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: sales invoice {index}")


def _add_item(doc, item_code: str, qty: int, rate: float, warehouse: str | None):
	if not frappe.db.exists("Item", item_code):
		return
	row = doc.append("items", {"item_code": item_code, "qty": qty, "rate": rate})
	if frappe.get_cached_value("Item", item_code, "is_stock_item"):
		row.warehouse = warehouse
	if frappe.get_cached_value("Item", item_code, "has_serial_no"):
		row.use_serial_batch_fields = 1
		row.serial_no = "\n".join(_serials(item_code, warehouse, qty))


def _serials(item_code: str, warehouse: str, qty: int) -> list[str]:
	available = frappe.get_all(
		"Serial No", filters={"item_code": item_code, "warehouse": warehouse, "status": "Active"},
		pluck="name", limit=qty,
	)
	if len(available) >= qty:
		return available
	return available + _receive(item_code, warehouse, qty - len(available))


def _receive(item_code: str, warehouse: str, qty: int) -> list[str]:
	qty = cint(qty)
	serials = [_next_imei() for _ in range(qty)] \
		if frappe.get_cached_value("Item", item_code, "has_serial_no") else []
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.company = frappe.db.get_value("Warehouse", warehouse, "company")
	entry.posting_date = add_days(nowdate(), -70)
	entry.set_posting_time = 1
	entry.remarks = "A3 demo replenishment"
	row = entry.append("items", {"item_code": item_code, "qty": qty, "t_warehouse": warehouse,
	                             "basic_rate": _cost(item_code)})
	if serials:
		row.use_serial_batch_fields = 1
		row.serial_no = "\n".join(serials)

	entry.flags.ignore_permissions = True
	try:
		entry.insert(ignore_permissions=True)
		entry.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: replenish {item_code}")
		return []
	return serials


def _cost(item_code: str) -> float:
	rate = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": "Standard Buying"}, "price_list_rate"
	)
	return rate or frappe.get_cached_value("Item", item_code, "valuation_rate") or 1000


def _sales_person(branch: str) -> str | None:
	"""Every invoice needs one — the app refuses a POS sale without attribution."""
	employee = frappe.db.get_value(
		"Employee", {"branch": branch, "status": "Active", "designation": ["like", "%Sales%"]},
		["name", "employee_name"], as_dict=True,
	) or frappe.db.get_value(
		"Employee", {"branch": branch, "status": "Active"}, ["name", "employee_name"],
		as_dict=True,
	)
	if not employee:
		return None

	existing = frappe.db.get_value("Sales Person", {"employee": employee.name}, "name")
	if existing:
		return existing

	doc = frappe.new_doc("Sales Person")
	doc.sales_person_name = employee.employee_name
	doc.employee = employee.name
	doc.parent_sales_person = _sales_person_root()
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		return None
	return doc.name


def _sales_person_root() -> str | None:
	root = frappe.db.get_value(
		"Sales Person", {"is_group": 1, "parent_sales_person": ["is", "not set"]}, "name"
	)
	if root:
		return root
	doc = frappe.new_doc("Sales Person")
	doc.sales_person_name = "All Sales Persons"
	doc.is_group = 1
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _next_imei() -> str:
	while True:
		body = f"3591260{_imei_sequence['next']:07d}"[:14]
		_imei_sequence["next"] += 1
		imei = body + str(luhn_check_digit(body))
		if not frappe.db.exists("Serial No", imei):
			return imei
