# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""RCM Liability and ITC Register — scope 12.5 report #39."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Invoice", "name", "Link", 150, "Purchase Invoice"),
	col("Date", "posting_date", "Date", 100),
	col("Supplier", "supplier_name", "Data", 180),
	col("Taxable Value", "base_net_total", "Currency", 130),
	col("RCM Tax", "rcm_tax", "Currency", 120),
	col("Grand Total", "base_grand_total", "Currency", 130),
]

SQL = """
select pi.name, pi.posting_date, pi.supplier_name, pi.base_net_total, pi.base_grand_total,
		       (select ifnull(sum(t.base_tax_amount), 0) from `tabPurchase Taxes and Charges` t
		        where t.parent = pi.name and t.add_deduct_tax = 'Add') as rcm_tax
		from `tabPurchase Invoice` pi
		where pi.docstatus = 1 and ifnull(pi.is_reverse_charge, 0) = 1 {conditions}
		order by pi.posting_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='pi', branch_field='branch',
	                 date_field='pi.posting_date')
