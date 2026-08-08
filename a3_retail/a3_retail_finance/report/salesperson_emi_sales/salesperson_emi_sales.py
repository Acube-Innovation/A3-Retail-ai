# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Salesperson EMI Sales — who is actually selling finance."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Sales person", "sales_person", "Link", 170, "Sales Person"),
	col("Branch", "branch", "Link", 120, "Branch"),
	col("Applications", "applications", "Int", 110),
	col("Disbursed", "disbursed", "Int", 100),
	col("Invoiced", "invoiced", "Currency", 130),
	col("Financed", "financed", "Currency", 130),
]

SQL = """
select e.sales_person, e.branch, count(e.name) as applications,
       sum(case when e.status in ('Disbursed', 'Settled') then 1 else 0 end) as disbursed,
       sum(e.invoice_total) as invoiced, sum(e.loan_amount) as financed
from `tabEMI Application` e
where e.docstatus < 2 {conditions}
group by e.sales_person, e.branch
order by financed desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.application_date")
