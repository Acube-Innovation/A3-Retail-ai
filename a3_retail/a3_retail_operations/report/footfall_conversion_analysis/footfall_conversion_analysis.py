# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Footfall Conversion Analysis — scope 12.5 report #32."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Visits", "visits", "Int", 90),
	col("Converted", "converted", "Int", 100),
	col("Lost", "lost", "Int", 90),
	col("Leads", "leads", "Int", 90),
	col("Conversion %", "conversion", "Percent", 120),
	col("Sale Value", "sale_value", "Currency", 130),
	col("Average Ticket", "avg_ticket", "Currency", 130),
]

SQL = """
select v.branch, count(*) as visits,
		       sum(case when v.outcome like 'Converted%%' then 1 else 0 end) as converted,
		       sum(case when v.outcome like 'Lost%%' then 1 else 0 end) as lost,
		       sum(case when v.lead is not null then 1 else 0 end) as leads,
		       sum(v.sale_value) as sale_value
		from `tabBranch Visit Log` v
		where 1 = 1 {conditions}
		group by v.branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="v", date_field="v.visit_datetime")
	for row in data:
		row["conversion"] = percent(row.get("converted"), row.get("visits"))
		row["avg_ticket"] = round((row.get("sale_value") or 0) / (row.get("converted") or 1), 2)
	return columns, data
