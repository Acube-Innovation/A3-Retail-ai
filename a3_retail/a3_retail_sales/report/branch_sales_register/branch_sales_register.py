# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Sales Register — scope 12.5 report #12."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Invoice", "name", "Link", 140, "Sales Invoice"),
	col("Date", "posting_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 160),
	col("Net Total", "base_net_total", "Currency", 120),
	col("Tax", "base_total_taxes_and_charges", "Currency", 110),
	col("Grand Total", "base_grand_total", "Currency", 130),
	col("Outstanding", "outstanding_amount", "Currency", 120),
]

SQL = """
select si.name, si.posting_date, si.branch, si.customer_name, si.base_net_total,
		       si.base_total_taxes_and_charges, si.base_grand_total, si.outstanding_amount
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		order by si.posting_date desc, si.name desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='si', branch_field='branch',
	                 date_field='si.posting_date')
