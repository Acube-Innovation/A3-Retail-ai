# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Name the stock account on every warehouse.

Not one of the eleven warehouses carried an `account`, so ERPNext worked it out
from the company default on every single purchase document and said so each
time, in its own words, in the middle of whatever dialog the counter was in:

    Row 1: Expense Head changed to Stock In Hand - PT because account Stock
    Received But Not Billed - PT is not linked to warehouse PhoneXpert Sales
    PSLA - PT or it is not the default inventory account

The account it chose is `Stock In Hand - PT`, the company's own
`default_inventory_account` and the account all 628 existing stock postings
already sit in. Writing it onto each warehouse changes no posting that has
happened or will happen; it only stops ERPNext guessing out loud.

Only warehouses with nothing set are touched, so a warehouse someone has
deliberately pointed at its own account keeps it.
"""

import frappe


def execute():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		print("  no default company, skipped")
		return

	account = frappe.db.get_value("Company", company, "default_inventory_account")
	if not account:
		print(f"  {company} has no default inventory account, skipped")
		return

	names = frappe.get_all("Warehouse",
		filters={"company": company, "is_group": 0, "account": ("in", ("", None))},
		pluck="name")
	for name in names:
		frappe.db.set_value("Warehouse", name, "account", account,
		                    update_modified=False)

	print(f"  {len(names)} warehouse(s) pointed at {account}")
