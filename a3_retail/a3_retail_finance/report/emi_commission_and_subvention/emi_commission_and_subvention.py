# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Commission and Subvention — what financing costs the shop."""

from frappe.utils import flt

from a3_retail.reporting import col, percent, run_query

COLUMNS = [
	col("Financier", "finance_partner", "Link", 160, "Finance Partner"),
	col("Branch", "branch", "Link", 120, "Branch"),
	col("Sales", "sales", "Int", 80),
	col("Financed", "financed", "Currency", 130),
	col("MDR", "mdr", "Currency", 120),
	col("Merchant subvention", "subvention", "Currency", 150),
	col("Total cost", "total_cost", "Currency", 130),
	col("Cost %", "cost_percent", "Percent", 100),
	col("Net realisable", "net_realisable", "Currency", 140),
]

SQL = """
select e.finance_partner, e.branch, count(e.name) as sales,
       sum(e.loan_amount) as financed, sum(e.mdr_amount) as mdr,
       sum(e.merchant_subvention_cost) as subvention,
       sum(e.net_realisable) as net_realisable
from `tabEMI Application` e
where e.docstatus = 1 and e.status in ('Disbursed', 'Settled') {conditions}
group by e.finance_partner, e.branch
order by financed desc
"""


def _cost(data, filters):
	for row in data:
		row["total_cost"] = flt(row.get("mdr")) + flt(row.get("subvention"))
		row["cost_percent"] = percent(row["total_cost"], row.get("financed"))
	return data


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.disbursement_date", post=_cost)
