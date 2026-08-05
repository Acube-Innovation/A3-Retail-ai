# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Telecalling Productivity — scope 12.5 report #34."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Telecaller", "assigned_to", "Link", 150, "Employee"),
	col("Assigned", "assigned", "Int", 100),
	col("Called", "called", "Int", 90),
	col("Connected", "connected", "Int", 100),
	col("Converted", "converted", "Int", 100),
	col("Connect %", "connect_rate", "Percent", 110),
	col("Conversion %", "conversion_rate", "Percent", 120),
	col("Talk Time (min)", "talk_minutes", "Float", 130),
]

SQL = """
select c.assigned_to, count(*) as assigned,
		       sum(case when c.call_status != 'Not Called' then 1 else 0 end) as called,
		       sum(case when c.call_status = 'Connected' then 1 else 0 end) as connected,
		       sum(case when c.outcome = 'Converted' then 1 else 0 end) as converted,
		       round(sum(ifnull(c.duration_seconds, 0)) / 60, 1) as talk_minutes
		from `tabCall Task` c
		where 1 = 1 {conditions}
		group by c.assigned_to
		order by converted desc
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c", date_field="c.scheduled_date")
	for row in data:
		row["connect_rate"] = percent(row.get("connected"), row.get("called"))
		row["conversion_rate"] = percent(row.get("converted"), row.get("connected"))
	return columns, data
