# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Awaiting Parts Register — scope 12.5 report #6."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Job Card", "name", "Link", 140, "Service Job Card"),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 150),
	col("Part", "item_code", "Link", 160, "Item"),
	col("Qty", "qty", "Float", 80),
	col("Status", "part_status", "Data", 130),
	col("Waiting (days)", "waiting_days", "Int", 120),
	col("Request", "stock_request", "Link", 140, "Stock Request"),
]

SQL = """
select jc.name, jc.branch, jc.customer_name, p.item_code, p.qty, p.part_status,
		       p.stock_request, datediff(curdate(), date(jc.received_on)) as waiting_days
		from `tabJob Card Part` p
		join `tabService Job Card` jc on jc.name = p.parent
		where jc.docstatus = 1 and jc.status = 'Awaiting Parts'
		  and p.part_status in ('Required', 'Awaiting Purchase', 'Awaiting Transfer')
		  {conditions}
		order by waiting_days desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field=None)
