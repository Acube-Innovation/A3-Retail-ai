# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Sales by Branch — what each branch financed, and with whom."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 130, "Branch"),
	col("Financier", "finance_partner", "Link", 150, "Finance Partner"),
	col("Sales", "sales", "Int", 80),
	col("Invoiced", "invoiced", "Currency", 130),
	col("Down payment", "down_payment", "Currency", 130),
	col("Financed", "financed", "Currency", 130),
	col("Average ticket", "average_ticket", "Currency", 130),
]

SQL = """
select e.branch, e.finance_partner, count(e.name) as sales,
       sum(e.invoice_total) as invoiced, sum(e.down_payment) as down_payment,
       sum(e.loan_amount) as financed,
       round(avg(e.invoice_total), 2) as average_ticket
from `tabEMI Application` e
where e.docstatus = 1 and e.status in ('Disbursed', 'Settled') {conditions}
group by e.branch, e.finance_partner
order by financed desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.disbursement_date")
