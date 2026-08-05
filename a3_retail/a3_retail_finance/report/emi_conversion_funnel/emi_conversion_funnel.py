# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Conversion Funnel — scope 12.5 report #19."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Status", "status", "Data", 180),
	col("Applications", "applications", "Int", 120),
	col("Loan Value", "loan_value", "Currency", 140),
	col("Share %", "share", "Percent", 100),
]

SQL = """
select e.status, count(*) as applications, sum(e.loan_amount) as loan_value
		from `tabEMI Application` e
		where e.docstatus < 2 {conditions}
		group by e.status
		order by applications desc
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="e", date_field="e.application_date")
	total = sum(row.get("applications") or 0 for row in data)
	for row in data:
		row["share"] = percent(row.get("applications"), total)
	return columns, data
