# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Financier Receivable Ageing — scope 12.5 report #20."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Partner", "finance_partner", "Link", 160, "Finance Partner"),
	col("Applications", "applications", "Int", 120),
	col("Disbursed Value", "disbursed", "Currency", 140),
	col("0-15 days", "bucket_15", "Currency", 120),
	col("16-30 days", "bucket_30", "Currency", 120),
	col("31-60 days", "bucket_60", "Currency", 120),
	col("60+ days", "bucket_older", "Currency", 120),
]

SQL = """
select e.finance_partner, count(*) as applications, sum(e.loan_amount) as disbursed,
		       sum(case when datediff(curdate(), e.disbursement_date) <= 15
		                then e.loan_amount else 0 end) as bucket_15,
		       sum(case when datediff(curdate(), e.disbursement_date) between 16 and 30
		                then e.loan_amount else 0 end) as bucket_30,
		       sum(case when datediff(curdate(), e.disbursement_date) between 31 and 60
		                then e.loan_amount else 0 end) as bucket_60,
		       sum(case when datediff(curdate(), e.disbursement_date) > 60
		                then e.loan_amount else 0 end) as bucket_older
		from `tabEMI Application` e
		where e.docstatus = 1 and e.status = 'Disbursed' {conditions}
		group by e.finance_partner
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='e', branch_field='branch',
	                 date_field=None)
