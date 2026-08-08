# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Pending Approval — what is sitting with a financier, and for how long."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Application", "name", "Link", 140, "EMI Application"),
	col("Submitted", "submitted_on", "Datetime", 150),
	col("Waiting (days)", "waiting_days", "Int", 120),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 160),
	col("Financier", "finance_partner", "Link", 150, "Finance Partner"),
	col("Financed", "loan_amount", "Currency", 120),
	col("Status", "status", "Data", 150),
	col("Coordinator", "coordinator", "Link", 140, "Employee"),
]

SQL = """
select e.name, e.submitted_on, datediff(curdate(), e.submitted_on) as waiting_days,
       e.branch, e.customer_name, e.finance_partner, e.loan_amount, e.status, e.coordinator
from `tabEMI Application` e
where e.docstatus = 1 and e.status in ('Submitted to Financier', 'Under Review') {conditions}
order by e.submitted_on
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.application_date")
