# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Warranty Claim Cost — scope 12.5 report #25."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Warranty Type", "warranty_type", "Data", 170),
	col("Claims", "claims", "Int", 90),
	col("Parts Cost", "parts_cost", "Currency", 130),
	col("Labour Cost", "labour_cost", "Currency", 130),
	col("Borne by Us", "warranty_borne", "Currency", 130),
]

SQL = """
select jc.branch, ifnull(jc.warranty_type, 'Not Recorded') as warranty_type,
		       count(*) as claims,
		       sum(jc.parts_total) as parts_cost, sum(jc.labour_total) as labour_cost,
		       sum(jc.warranty_borne_amount) as warranty_borne
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.warranty_borne_amount, 0) > 0 {conditions}
		group by jc.branch, jc.warranty_type
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
