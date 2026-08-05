# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Cross-Branch Availability — scope 12.5 report #27."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Item", "item_code", "Link", 180, "Item"),
	col("Item Name", "item_name", "Data", 200),
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Warehouse", "warehouse", "Link", 170, "Warehouse"),
	col("Available", "actual_qty", "Float", 110),
	col("Reserved", "reserved_qty", "Float", 110),
]

SQL = """
select b.item_code, i.item_name, w.custom_branch as branch, b.warehouse,
		       b.actual_qty, b.reserved_qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where b.actual_qty > 0 {conditions}
		order by b.item_code, w.custom_branch
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='w', branch_field='custom_branch',
	                 date_field=None)
