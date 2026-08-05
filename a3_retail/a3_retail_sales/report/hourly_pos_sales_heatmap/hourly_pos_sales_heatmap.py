# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Hourly POS Sales Heatmap — scope 12.5 report #17."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Hour", "hour", "Data", 100),
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Invoices", "invoices", "Int", 100),
	col("Sales", "sales", "Currency", 130),
	col("Average Ticket", "avg_ticket", "Currency", 130),
]

SQL = """
select lpad(hour(si.posting_time), 2, '0') as hour, si.branch,
		       count(*) as invoices, sum(si.base_grand_total) as sales,
		       round(avg(si.base_grand_total), 2) as avg_ticket
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by hour, si.branch
		order by hour
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='si', branch_field='branch',
	                 date_field='si.posting_date')
