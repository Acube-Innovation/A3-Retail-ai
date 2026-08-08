# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Outstanding Financier Settlement — money the financiers still owe."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Application", "name", "Link", 140, "EMI Application"),
	col("Disbursed", "disbursement_date", "Date", 110),
	col("Days outstanding", "days_outstanding", "Int", 130),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Financier", "finance_partner", "Link", 150, "Finance Partner"),
	col("Invoice", "sales_invoice", "Link", 140, "Sales Invoice"),
	col("Financed", "loan_amount", "Currency", 120),
	col("Expected net", "expected_net", "Currency", 130),
]

SQL = """
select e.name, e.disbursement_date,
       datediff(curdate(), e.disbursement_date) as days_outstanding,
       e.branch, e.finance_partner, e.sales_invoice, e.loan_amount,
       (e.loan_amount - ifnull(e.mdr_amount, 0) - ifnull(e.merchant_subvention_cost, 0))
         as expected_net
from `tabEMI Application` e
where e.docstatus = 1 and e.status = 'Disbursed' {conditions}
order by e.disbursement_date
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.disbursement_date")
