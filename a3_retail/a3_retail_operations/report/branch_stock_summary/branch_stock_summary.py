# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Stock Summary — scope 12.5 report #26."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Warehouse", "warehouse", "Link", 180, "Warehouse"),
	col("Items", "items", "Int", 90),
	col("Quantity", "qty", "Float", 110),
	col("Stock Value", "stock_value", "Currency", 140),
]

SQL = """
select w.custom_branch as branch, b.warehouse, count(distinct b.item_code) as items,
		       sum(b.actual_qty) as qty, sum(b.stock_value) as stock_value
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.actual_qty != 0 {conditions}
		group by w.custom_branch, b.warehouse
		order by stock_value desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='w', branch_field='custom_branch',
	                 date_field=None)
