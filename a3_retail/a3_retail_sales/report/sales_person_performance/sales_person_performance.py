# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Sales Person Performance — scope 12.5 report #15."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Sales Person", "sales_person", "Link", 160, "Sales Person"),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Invoices", "invoices", "Int", 90),
	col("Net Sales", "net_sales", "Currency", 130),
	col("Average Ticket", "avg_ticket", "Currency", 130),
	col("Returns", "returns", "Currency", 120),
]

SQL = """
select st.sales_person, si.branch, count(distinct si.name) as invoices,
		       sum(si.base_net_total * st.allocated_percentage / 100) as net_sales,
		       round(avg(si.base_net_total), 2) as avg_ticket,
		       (select ifnull(sum(abs(r.base_net_total)), 0) from `tabSales Invoice` r
		        join `tabSales Team` rst on rst.parent = r.name
		        where r.docstatus = 1 and r.is_return = 1
		          and rst.sales_person = st.sales_person
		          and r.posting_date between %(from_date)s and %(to_date)s) as returns
		from `tabSales Team` st
		join `tabSales Invoice` si on si.name = st.parent
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by st.sales_person, si.branch
		order by net_sales desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='si', branch_field='branch',
	                 date_field='si.posting_date')
