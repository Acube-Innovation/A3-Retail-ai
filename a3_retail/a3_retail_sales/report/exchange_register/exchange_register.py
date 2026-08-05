# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Exchange Register — scope 12.5 report #16."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Exchange", "name", "Link", 140, "Device Exchange"),
	col("Date", "exchange_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer", "Link", 150, "Customer"),
	col("Old Device", "old_model", "Data", 150),
	col("IMEI", "old_imei", "Data", 130),
	col("Grade", "grade", "Data", 80),
	col("Value", "final_exchange_value", "Currency", 120),
	col("Resale Status", "resale_status", "Data", 130),
]

SQL = """
select x.name, x.exchange_date, x.branch, x.customer, x.old_model, x.old_imei,
		       x.grade, x.final_exchange_value, x.resale_status
		from `tabDevice Exchange` x
		where x.docstatus = 1 {conditions}
		order by x.exchange_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='x', branch_field='branch',
	                 date_field='x.exchange_date')
