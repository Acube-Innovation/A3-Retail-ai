# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""What PhoneXpert spends on, as their old billing software had it.

Read out of all six businesses there and kept here so another site gets the
same list by running one command rather than by somebody retyping sixty rows:

    bench --site <site> execute a3_retail.setup.expense_catalogue.run

It only adds. Anything already on file under that name is left exactly as it
is, so a second run does nothing — which makes it safe to re-run after they
invent a few more and this list is refreshed.
"""

import frappe
from frappe.utils import flt

from a3_retail.api.expenses import _expense_item_group, _expense_parent

# Where the shop files its spending: one expense Account each, under the
# company's indirect expenses. Written the way they write it, case and all,
# except that spellings differing only in case have been folded together.
CATEGORIES = [
	'A4 SHEET',
	'AC SERVICE',
	'AC SERVICE Charge',
	'Bank Fee and Charges',
	'Bike Maintanance',
	'BLADE',
	'buds',
	'BUS',
	'CARRY BAG AUTO CHARGE',
	'CHAAKK',
	'CITU',
	'DONATION',
	'Employee Salaries & Advances',
	'Jibin Chitty',
	'KSEB',
	'KSFE',
	'KSFE CHITTY',
	'KSFE CHITTY UK',
	'New Shop At Udiyankulangara',
	'OTHER',
	'OTHERS',
	'Printing and Stationery',
	'Raw Material',
	'Rent Expense',
	'Repair & Maintenance',
	'Route',
	'Route petrol',
	'SADHASIVAN CHITTY',
	'Second Hand Phone Purchase',
	'SECOND PURCHASE',
	'SHOP BALANCE',
	'SHOP EXPENCE',
	'SHOP MAINTENANCE',
	'sundar bhai',
	'SUNDAR BHAI CHiTTi',
	'SUNDHER CHITTI',
	'Tea',
	'Tea Expense',
	'Telephone & Internet Expense',
	'Transportation & Travel Expense',
	'WASTE',
	'Water',
	'Water Bill',
]

# What the shop buys but does not stock. `rate` is what it last paid, which the
# picker shows so the counter recognises the line, and `no_itc` marks the two
# the department does not allow the input credit on.
ITEMS = [
	{"name": 'A4 PAPER / MASK TAP', "kind": 'Product', "rate": 340.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'A4 SHEET', "kind": 'Product', "rate": 150.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Abhijith advance', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Abhijith Petrol', "kind": 'Service', "rate": 150.0, "uom": 'Litre', "hsn": None, "gst": 0.0, "no_itc": True},
	{"name": 'Abinu Locker cracking work', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'AC REPAIR', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'AC SERVICE Charge', "kind": 'Product', "rate": 2650.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BATTERY', "kind": 'Product', "rate": 50.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Bike Maintance', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BLADE', "kind": 'Product', "rate": 45.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Brand cover printing', "kind": 'Product', "rate": 10340.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BROOM', "kind": 'Product', "rate": 170.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BUDS', "kind": 'Product', "rate": 20.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BULB', "kind": 'Product', "rate": 100.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BULB HOLDER AND BULB', "kind": 'Product', "rate": 105.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'BULBE', "kind": 'Product', "rate": 100.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Carry bag auto', "kind": 'Product', "rate": 500.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'CEMENT', "kind": 'Product', "rate": 10.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'CHAAK', "kind": 'Product', "rate": 10.0, "uom": 'Box', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'CHITTI', "kind": 'Product', "rate": 1200.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Chitty 24500/-', "kind": 'Product', "rate": 24500.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'CITU MEMBERSHIP', "kind": 'Product', "rate": 100.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'COLACTION', "kind": 'Product', "rate": 50.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'CUTEX', "kind": 'Product', "rate": 70.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'DONATION', "kind": 'Product', "rate": 20.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'FILE', "kind": 'Product', "rate": 90.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'FOOD', "kind": 'Product', "rate": 130.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Gayathri', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'GLOUS', "kind": 'Product', "rate": 20.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'HANDWASH', "kind": 'Product', "rate": 10.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'HARITHASENA', "kind": 'Service', "rate": 50.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'HARPIC', "kind": 'Product', "rate": 80.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'KNIFE', "kind": 'Product', "rate": 70.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'KSEB', "kind": 'Product', "rate": 270.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'KSFE CHITTI', "kind": 'Product', "rate": 4000.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'KSFE CHITTY', "kind": 'Service', "rate": 2000.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'KSFE CHITTY UK', "kind": 'Service', "rate": 2000.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'LOCK /FUND', "kind": 'Product', "rate": 140.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'PAINT', "kind": 'Product', "rate": 500.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'PEN &BOOK', "kind": 'Product', "rate": 40.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Petrol 150', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'ROOM FRESHNER', "kind": 'Product', "rate": 250.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'ROOM maintenance', "kind": 'Product', "rate": 4000.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'ROPE', "kind": 'Product', "rate": 60.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'RUBBER BAND', "kind": 'Product', "rate": 160.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'SANITIZER', "kind": 'Product', "rate": 30.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'SCALE', "kind": 'Product', "rate": 20.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'SHAMPOO', "kind": 'Product', "rate": 10.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'SHOP BALANCE', "kind": 'Product', "rate": 500.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'STAPLER', "kind": 'Product', "rate": 75.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'TAPE', "kind": 'Product', "rate": 40.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'TEMPLE DONATION', "kind": 'Product', "rate": 200.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'TICKET FARE', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'TISSUE', "kind": 'Product', "rate": 35.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Vishnu Advance', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Vishnu Petrol', "kind": 'Product', "rate": 150.0, "uom": 'Litre', "hsn": None, "gst": 0.0, "no_itc": True},
	{"name": 'VYAPARI', "kind": 'Product', "rate": 100.0, "uom": 'Box', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'Water Bill', "kind": 'Product', "rate": 0.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'WATER MOTOR', "kind": 'Product', "rate": 300.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'WHITNER', "kind": 'Product', "rate": 90.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
	{"name": 'WIPER', "kind": 'Product', "rate": 250.0, "uom": 'Nos', "hsn": None, "gst": 0.0, "no_itc": False},
]


def run(verbose: bool = True) -> dict:
	"""Create whatever is missing. Says what it did; changes nothing it finds."""
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	made = {"categories": [], "items": [], "skipped_categories": 0, "skipped_items": 0}

	parent = _expense_parent(company)
	if not parent:
		frappe.throw("This company has no expenses group to file categories under.")

	have = {(a or "").strip().lower() for a in frappe.get_all(
		"Account", filters={"company": company, "root_type": "Expense", "is_group": 0},
		pluck="account_name")}
	for label in CATEGORIES:
		if label.lower() in have:
			made["skipped_categories"] += 1
			continue
		acc = frappe.new_doc("Account")
		acc.account_name = label
		acc.parent_account = parent
		acc.company = company
		acc.is_group = 0
		acc.root_type = "Expense"
		acc.account_type = "Expense Account"
		acc.flags.ignore_permissions = True
		acc.insert(ignore_permissions=True)
		made["categories"].append(acc.name)

	group = _expense_item_group()
	for row in ITEMS:
		if frappe.db.exists("Item", {"item_name": row["name"], "is_stock_item": 0}):
			made["skipped_items"] += 1
			continue
		doc = frappe.new_doc("Item")
		doc.item_code = row["name"]
		doc.item_name = row["name"]
		doc.item_group = group
		doc.stock_uom = row["uom"] if frappe.db.exists("UOM", row["uom"]) else "Nos"
		doc.is_stock_item = 0
		# Bought, never sold: it has no business in the till's search.
		doc.is_purchase_item = 1
		doc.is_sales_item = 0
		doc.valuation_rate = flt(row["rate"])
		if row["hsn"] and doc.meta.has_field("gst_hsn_code") \
				and frappe.db.exists("GST HSN Code", row["hsn"]):
			doc.gst_hsn_code = row["hsn"]
		if row["no_itc"] and doc.meta.has_field("is_ineligible_for_itc"):
			doc.is_ineligible_for_itc = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		made["items"].append(doc.name)

	frappe.db.commit()
	if verbose:
		print(f"categories: {len(made['categories'])} added,"
		      f" {made['skipped_categories']} already there")
		print(f"items:      {len(made['items'])} added,"
		      f" {made['skipped_items']} already there")
		for name in made["items"]:
			print(f"   + {name}")
	return made
