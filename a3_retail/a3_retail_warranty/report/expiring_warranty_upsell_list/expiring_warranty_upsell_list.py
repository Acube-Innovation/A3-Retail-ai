# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Expiring Warranty Upsell List — scope 12.5 report #23."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Registration", "name", "Link", 140, "Warranty Registration"),
	col("Customer", "customer", "Link", 150, "Customer"),
	col("Mobile", "customer_mobile", "Data", 120),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Device", "item_name", "Data", 160),
	col("Expires", "expiry", "Date", 110),
	col("Days Left", "days_left", "Int", 100),
	col("Plan", "ew_plan", "Link", 150, "Extended Warranty Plan"),
]

SQL = """
select w.name, w.customer, w.customer_mobile, w.branch, w.item_name, w.ew_plan,
		       coalesce(w.ew_expiry_date, w.brand_warranty_expiry) as expiry,
		       datediff(coalesce(w.ew_expiry_date, w.brand_warranty_expiry), curdate()) as days_left
		from `tabWarranty Registration` w
		where w.docstatus = 1 and w.status in ('In Warranty', 'In Extended Warranty')
		  {conditions}
		having days_left between 0 and 60
		order by days_left
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='w', branch_field='branch',
	                 date_field=None)
