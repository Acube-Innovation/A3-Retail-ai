# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Revenue and GP — scope 12.5 report #9."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Jobs", "jobs", "Int", 90),
	col("Parts Revenue", "parts_total", "Currency", 130),
	col("Labour Revenue", "labour_total", "Currency", 130),
	col("Parts Cost", "parts_cost", "Currency", 130),
	col("Gross Profit", "gross_profit", "Currency", 130),
	col("GP %", "gp_percent", "Percent", 100),
]

SQL = """
select jc.branch, count(*) as jobs,
		       sum(jc.parts_total) as parts_total, sum(jc.labour_total) as labour_total,
		       (select ifnull(sum(p.qty * p.valuation_rate), 0) from `tabJob Card Part` p
		        where p.parent = jc.name) as parts_cost
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status in ('Delivered', 'Closed') {conditions}
		group by jc.branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="jc", date_field="jc.delivered_on")
	for row in data:
		revenue = (row.get("parts_total") or 0) + (row.get("labour_total") or 0)
		row["gross_profit"] = revenue - (row.get("parts_cost") or 0)
		row["gp_percent"] = percent(row["gross_profit"], revenue)
	return columns, data
