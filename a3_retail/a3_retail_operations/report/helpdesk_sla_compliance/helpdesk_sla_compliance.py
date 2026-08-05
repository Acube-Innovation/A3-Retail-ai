# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Helpdesk SLA Compliance — scope 12.5 report #33."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Tickets", "tickets", "Int", 90),
	col("Resolved", "resolved", "Int", 100),
	col("SLA Failed", "failed", "Int", 100),
	col("Compliance %", "compliance", "Percent", 120),
	col("Average Resolution (h)", "avg_hours", "Float", 170),
]

SQL = """
select i.a3_branch as branch, count(*) as tickets,
		       sum(case when i.status in ('Resolved', 'Closed') then 1 else 0 end) as resolved,
		       sum(case when i.agreement_status = 'Failed' then 1 else 0 end) as failed,
		       round(avg(timestampdiff(hour, i.opening_date, i.sla_resolution_date)), 1) as avg_hours
		from `tabIssue` i
		where 1 = 1 {conditions}
		group by i.a3_branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="i", branch_field="a3_branch",
	                          date_field="i.opening_date")
	for row in data:
		row["compliance"] = percent((row.get("tickets") or 0) - (row.get("failed") or 0),
		                            row.get("tickets"))
	return columns, data
