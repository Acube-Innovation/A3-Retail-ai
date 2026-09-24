# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Bill the price the customer was quoted, with GST inside it.

The sales GST templates were created with the tax added *on top of* the rate.
The shop's price list is an all-in price — it came across from myBillBook, where
every line carries `is_tax_included` — so a bill for a phone listed at 39,999
was going out at 47,198.82. This flips the sales templates to treat the rate as
tax-inclusive, which is how the counter quotes and how the old system billed.

Only the outward-supply templates the counter uses are touched. Reverse-charge
templates are left alone: there the tax is genuinely additional, because the
supplier never charged it.
"""

import frappe

PREFIXES = ("Output GST In-state", "Output GST Out-state")


def execute():
	if not frappe.db.has_column("Sales Taxes and Charges", "included_in_print_rate"):
		return

	templates = [
		row.name
		for row in frappe.get_all("Sales Taxes and Charges Template", fields=["name", "title"])
		if row.title and row.title.startswith(PREFIXES) and "RCM" not in row.title
	]
	if not templates:
		return

	frappe.db.sql(
		"""
		update `tabSales Taxes and Charges`
		   set included_in_print_rate = 1
		 where parenttype = 'Sales Taxes and Charges Template'
		   and parent in %(templates)s
		   and ifnull(included_in_print_rate, 0) = 0
		""",
		{"templates": templates},
	)

	for name in templates:
		frappe.clear_document_cache("Sales Taxes and Charges Template", name)
