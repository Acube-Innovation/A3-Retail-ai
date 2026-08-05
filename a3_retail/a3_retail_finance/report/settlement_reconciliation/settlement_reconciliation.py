# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Settlement Reconciliation — scope 12.5 report #21."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Settlement", "name", "Link", 150, "Financier Settlement"),
	col("Partner", "finance_partner", "Link", 150, "Finance Partner"),
	col("Period", "period", "Data", 170),
	col("Gross", "gross_amount", "Currency", 120),
	col("MDR", "mdr_amount", "Currency", 110),
	col("Subvention", "subvention_amount", "Currency", 120),
	col("Expected", "net_expected", "Currency", 120),
	col("Received", "net_received", "Currency", 120),
	col("Variance", "variance", "Currency", 110),
]

SQL = """
select s.name, s.finance_partner,
		       concat(s.from_date, ' to ', s.to_date) as period,
		       s.gross_amount, s.mdr_amount, s.subvention_amount, s.net_expected,
		       s.net_received, s.variance
		from `tabFinancier Settlement` s
		where s.docstatus < 2
		order by s.from_date desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='s', branch_field='branch',
	                 date_field=None)
