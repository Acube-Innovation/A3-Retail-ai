# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""IMEI Sales Register — scope 12.5 report #13."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("IMEI / Serial", "serial_no", "Link", 150, "Serial No"),
	col("Item", "item_code", "Link", 170, "Item"),
	col("Invoice", "parent", "Link", 140, "Sales Invoice"),
	col("Date", "posting_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 160),
	col("Rate", "rate", "Currency", 110),
]

SQL = """
select sbe.serial_no, sii.item_code, si.name as parent, si.posting_date, si.branch,
		       si.customer_name, sii.rate
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		join `tabSerial and Batch Bundle` sbb on sbb.name = sii.serial_and_batch_bundle
		join `tabSerial and Batch Entry` sbe on sbe.parent = sbb.name
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		union all
		select sii.serial_no, sii.item_code, si.name as parent, si.posting_date, si.branch,
		       si.customer_name, sii.rate
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.is_return = 0 and ifnull(sii.serial_no, '') != ''
		  {conditions}
		order by 4 desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='si', branch_field='branch',
	                 date_field='si.posting_date')
