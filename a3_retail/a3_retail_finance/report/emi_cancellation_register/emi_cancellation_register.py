# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Cancellation Register — applications that never became sales."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Application", "name", "Link", 140, "EMI Application"),
	col("Date", "application_date", "Date", 110),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 160),
	col("Financier", "finance_partner", "Link", 150, "Finance Partner"),
	col("Financed", "loan_amount", "Currency", 120),
	col("Status", "status", "Data", 120),
	col("Reason", "rejection_reason", "Data", 170),
	col("Remarks", "rejection_remarks", "Data", 220),
]

SQL = """
select e.name, e.application_date, e.branch, e.customer_name, e.finance_partner,
       e.loan_amount, e.status, e.rejection_reason, e.rejection_remarks
from `tabEMI Application` e
where e.status in ('Cancelled', 'Rejected') {conditions}
order by e.application_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.application_date")
