# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Application Register — scope 12.5 report #18."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Application", "name", "Link", 140, "EMI Application"),
	col("Date", "application_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 150),
	col("Partner", "finance_partner", "Link", 130, "Finance Partner"),
	col("Scheme", "emi_scheme", "Link", 150, "EMI Scheme"),
	col("Loan", "loan_amount", "Currency", 120),
	col("Status", "status", "Data", 150),
	col("Coordinator", "coordinator", "Link", 130, "Employee"),
]

SQL = """
select e.name, e.application_date, e.branch, e.customer_name, e.finance_partner,
		       e.emi_scheme, e.loan_amount, e.status, e.coordinator
		from `tabEMI Application` e
		where e.docstatus < 2 {conditions}
		order by e.application_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='e', branch_field='branch',
	                 date_field='e.application_date')
