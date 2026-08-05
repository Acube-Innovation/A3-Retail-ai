# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Warranty Register — scope 12.5 report #22."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Registration", "name", "Link", 140, "Warranty Registration"),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer", "Link", 150, "Customer"),
	col("IMEI", "imei_1", "Data", 130),
	col("Item", "item_name", "Data", 160),
	col("Purchased", "purchase_date", "Date", 100),
	col("Brand Expiry", "brand_warranty_expiry", "Date", 110),
	col("Plan", "ew_plan", "Link", 150, "Extended Warranty Plan"),
	col("Plan Expiry", "ew_expiry_date", "Date", 110),
	col("Status", "status", "Data", 130),
]

SQL = """
select w.name, w.branch, w.customer, w.imei_1, w.item_name, w.purchase_date,
		       w.brand_warranty_expiry, w.ew_plan, w.ew_expiry_date, w.status
		from `tabWarranty Registration` w
		where w.docstatus = 1 {conditions}
		order by w.purchase_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='w', branch_field='branch',
	                 date_field='w.purchase_date')
