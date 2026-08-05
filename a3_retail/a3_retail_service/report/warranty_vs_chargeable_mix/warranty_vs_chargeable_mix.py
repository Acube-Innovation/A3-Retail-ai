# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Warranty vs Chargeable Mix — scope 12.5 report #8."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Warranty Type", "warranty_type", "Data", 160),
	col("Job Cards", "jobs", "Int", 100),
	col("Customer Payable", "customer_payable", "Currency", 140),
	col("Warranty Borne", "warranty_borne", "Currency", 140),
]

SQL = """
select jc.branch, ifnull(jc.warranty_type, 'Not Recorded') as warranty_type,
		       count(*) as jobs, sum(jc.customer_payable) as customer_payable,
		       sum(jc.warranty_borne_amount) as warranty_borne
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		group by jc.branch, jc.warranty_type
		order by jc.branch, jobs desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
