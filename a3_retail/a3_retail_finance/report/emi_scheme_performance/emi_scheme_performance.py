# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Scheme Performance — which schemes the counter actually sells."""

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Scheme", "emi_scheme", "Link", 190, "EMI Scheme"),
	col("Financier", "finance_partner", "Link", 150, "Finance Partner"),
	col("Tenure", "tenure_months", "Int", 80),
	col("Applications", "applications", "Int", 110),
	col("Disbursed", "disbursed", "Int", 100),
	col("Financed", "financed", "Currency", 130),
	col("Merchant subvention", "subvention", "Currency", 150),
	col("MDR", "mdr", "Currency", 110),
]

SQL = """
select e.emi_scheme, e.finance_partner, e.tenure_months, count(e.name) as applications,
       sum(case when e.status in ('Disbursed', 'Settled') then 1 else 0 end) as disbursed,
       sum(e.loan_amount) as financed,
       sum(e.merchant_subvention_cost) as subvention,
       sum(e.mdr_amount) as mdr
from `tabEMI Application` e
where e.docstatus < 2 and e.emi_scheme is not null {conditions}
group by e.emi_scheme, e.finance_partner, e.tenure_months
order by financed desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.application_date")
