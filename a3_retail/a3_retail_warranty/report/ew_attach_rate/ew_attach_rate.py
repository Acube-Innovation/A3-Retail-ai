# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EW Attach Rate — scope 12.5 report #24."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 140, "Branch"),
	col("Devices Sold", "devices", "Float", 120),
	col("Plans Sold", "plans", "Float", 110),
	col("Attach Rate %", "attach_rate", "Percent", 130),
	col("Plan Revenue", "plan_revenue", "Currency", 130),
]

SQL = """
select si.branch,
		       sum(case when ifnull(i.a3_is_device, 0) = 1 then sii.qty else 0 end) as devices,
		       sum(case when ifnull(i.a3_is_ew_plan, 0) = 1 then sii.qty else 0 end) as plans,
		       sum(case when ifnull(i.a3_is_ew_plan, 0) = 1 then sii.base_net_amount else 0 end)
		           as plan_revenue
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabItem` i on i.name = sii.item_code
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by si.branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="si", date_field="si.posting_date")
	for row in data:
		row["attach_rate"] = percent(row.get("plans"), row.get("devices"))
	return columns, data
