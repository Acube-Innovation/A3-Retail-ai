# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Financier Performance — how each partner actually behaves."""

from frappe.utils import flt

from a3_retail.reporting import col, percent, run_query

COLUMNS = [
	col("Financier", "finance_partner", "Link", 160, "Finance Partner"),
	col("Applications", "applications", "Int", 110),
	col("Approved", "approved", "Int", 90),
	col("Rejected", "rejected", "Int", 90),
	col("Approval rate %", "approval_rate", "Percent", 120),
	col("Financed", "financed", "Currency", 130),
	col("Average ticket", "average_ticket", "Currency", 130),
	col("Still owed", "outstanding", "Currency", 130),
]

SQL = """
select e.finance_partner, count(e.name) as applications,
       sum(case when e.status in ('Approved', 'Disbursed', 'Settled') then 1 else 0 end) as approved,
       sum(case when e.status = 'Rejected' then 1 else 0 end) as rejected,
       sum(e.loan_amount) as financed,
       round(avg(e.invoice_total), 2) as average_ticket,
       sum(case when e.status = 'Disbursed' then e.loan_amount else 0 end) as outstanding
from `tabEMI Application` e
where e.docstatus < 2 and e.finance_partner is not null {conditions}
group by e.finance_partner
order by financed desc
"""


def _rate(data, filters):
	for row in data:
		decided = flt(row.get("approved")) + flt(row.get("rejected"))
		row["approval_rate"] = percent(row.get("approved"), decided)
	return data


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias="e", branch_field="branch",
	                 date_field="e.application_date", post=_rate)
