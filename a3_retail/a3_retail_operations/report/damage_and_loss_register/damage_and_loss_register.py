# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Damage and Loss Register — scope 12.5 report #30."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Report", "name", "Link", 140, "Stock Damage Report"),
	col("Date", "report_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Damage Type", "damage_type", "Data", 140),
	col("Responsibility", "responsibility", "Data", 140),
	col("Loss Value", "total_value", "Currency", 120),
	col("Recovered", "recovery_amount", "Currency", 120),
	col("Status", "status", "Data", 120),
]

SQL = """
select d.name, d.report_date, d.branch, d.damage_type, d.responsibility,
		       d.total_value, d.recovery_amount, d.status
		from `tabStock Damage Report` d
		where d.docstatus = 1 {conditions}
		order by d.report_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='d', branch_field='branch',
	                 date_field='d.report_date')
