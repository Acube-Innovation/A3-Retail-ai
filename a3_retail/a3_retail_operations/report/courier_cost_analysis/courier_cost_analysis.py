# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Courier Cost Analysis — scope 12.5 report #42."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Partner", "courier_partner", "Link", 160, "Courier Partner"),
	col("Branch", "branch", "Link", 120, "Branch"),
	col("Dispatches", "dispatches", "Int", 110),
	col("Freight", "freight", "Currency", 120),
	col("Total Cost", "total_cost", "Currency", 120),
	col("Average Cost", "avg_cost", "Currency", 130),
	col("Delayed", "delayed_count", "Int", 90),
	col("On-time %", "on_time_rate", "Percent", 110),
]

SQL = """
select c.courier_partner, c.branch, count(*) as dispatches,
		       sum(c.freight_amount) as freight, sum(c.total_cost) as total_cost,
		       round(avg(c.total_cost), 2) as avg_cost,
		       sum(case when ifnull(c.delay_days, 0) > 0 then 1 else 0 end) as delayed_count
		from `tabCourier Dispatch` c
		where c.docstatus = 1 {conditions}
		group by c.courier_partner, c.branch
		order by total_cost desc
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c", date_field="c.dispatch_date")
	for row in data:
		row["on_time_rate"] = percent((row.get("dispatches") or 0) - (row.get("delayed_count") or 0),
		                              row.get("dispatches"))
	return columns, data
