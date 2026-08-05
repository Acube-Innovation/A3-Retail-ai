# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Profitability Statement — scope 12.5 report #38."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Branch", "branch", "Link", 140, "Branch"),
	col("Revenue", "revenue", "Currency", 140),
	col("Expense", "expense", "Currency", 140),
	col("Contribution", "contribution", "Currency", 140),
	col("Margin %", "margin", "Percent", 110),
]

SQL = """
select gl.branch,
		       sum(case when acc.root_type = 'Income' then gl.credit - gl.debit else 0 end) as revenue,
		       sum(case when acc.root_type = 'Expense' then gl.debit - gl.credit else 0 end) as expense
		from `tabGL Entry` gl
		join `tabAccount` acc on acc.name = gl.account
		where gl.is_cancelled = 0 and acc.root_type in ('Income', 'Expense') {conditions}
		group by gl.branch
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="gl", date_field="gl.posting_date")
	for row in data:
		row["contribution"] = (row.get("revenue") or 0) - (row.get("expense") or 0)
		row["margin"] = percent(row["contribution"], row.get("revenue"))
	return columns, data
