# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""TAT Compliance — scope 12.5 report #4."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Delivered", "delivered", "Int", 100),
	col("On Time", "on_time", "Int", 100),
	col("Breached", "breached", "Int", 100),
	col("Compliance %", "compliance", "Percent", 120),
	col("Average TAT (h)", "avg_hours", "Float", 130),
]

SQL = """
select jc.branch,
		       count(*) as delivered,
		       sum(case when jc.sla_due_on is null or jc.delivered_on <= jc.sla_due_on
		                then 1 else 0 end) as on_time,
		       sum(case when jc.sla_due_on is not null and jc.delivered_on > jc.sla_due_on
		                then 1 else 0 end) as breached,
		       avg(timestampdiff(hour, jc.received_on, jc.delivered_on)
		           - ifnull(jc.paused_hours, 0)) as avg_hours
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.delivered_on is not null {conditions}
		group by jc.branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="jc", date_field="jc.delivered_on")
	for row in data:
		row["compliance"] = percent(row.get("on_time"), row.get("delivered"))
		row["avg_hours"] = round(row.get("avg_hours") or 0, 1)
	return columns, data
