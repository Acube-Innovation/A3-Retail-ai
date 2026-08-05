# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Margin Scheme Register — scope 12.5 report #40."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Invoice", "name", "Link", 140, "Sales Invoice"),
	col("Date", "posting_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Item", "item_code", "Link", 170, "Item"),
	col("Serial / IMEI", "serial_no", "Data", 140),
	col("Sale Value", "amount", "Currency", 120),
	col("Purchase Value", "purchase_value", "Currency", 130),
	col("Margin", "margin", "Currency", 110),
]

SQL = """
select si.name, si.posting_date, si.branch, sii.item_code, sii.serial_no,
		       sii.base_net_amount as amount,
		       ifnull(sii.incoming_rate, 0) * sii.stock_qty as purchase_value
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabItem` i on i.name = sii.item_code
		where si.docstatus = 1 and si.is_return = 0 and ifnull(i.a3_is_margin_scheme, 0) = 1
		  {conditions}
		order by si.posting_date desc
"""


def execute(filters=None):
	columns, data = run_query(COLUMNS, SQL, filters, alias="si", date_field="si.posting_date")
	for row in data:
		row["margin"] = (row.get("amount") or 0) - (row.get("purchase_value") or 0)
	return columns, data
