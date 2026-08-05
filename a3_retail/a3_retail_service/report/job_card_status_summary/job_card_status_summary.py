# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Job Card Status Summary — scope 12.5 report #2."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Status", "status", "Data", 180),
	col("Job Cards", "count", "Int", 100),
	col("Value", "value", "Currency", 130),
	col("Oldest (days)", "oldest_days", "Int", 120),
]

SQL = """
select jc.status, count(*) as count, sum(jc.grand_total) as value,
		       max(datediff(curdate(), date(jc.received_on))) as oldest_days
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		group by jc.status
		order by count desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
