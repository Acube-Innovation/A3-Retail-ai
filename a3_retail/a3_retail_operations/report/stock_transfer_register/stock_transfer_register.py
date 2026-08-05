# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stock Transfer Register — scope 12.5 report #28."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Request", "name", "Link", 140, "Stock Request"),
	col("Date", "request_date", "Date", 100),
	col("From", "source_branch", "Link", 120, "Branch"),
	col("To", "requesting_branch", "Link", 120, "Branch"),
	col("Status", "status", "Data", 130),
	col("Value", "total_value", "Currency", 120),
	col("Dispatched", "dispatched_on", "Datetime", 140),
	col("Received", "received_on", "Datetime", 140),
	col("Transit Days", "transit_days", "Int", 110),
]

SQL = """
select s.name, s.request_date, s.source_branch, s.requesting_branch, s.status,
		       s.total_value, s.dispatched_on, s.received_on, s.transit_days
		from `tabStock Request` s
		where s.docstatus = 1 {conditions}
		order by s.request_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='s', branch_field='requesting_branch',
	                 date_field='s.request_date')
