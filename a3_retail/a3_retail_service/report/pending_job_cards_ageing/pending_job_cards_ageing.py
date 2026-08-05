# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Pending Job Cards Ageing — scope 12.5 report #3."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Job Card", "name", "Link", 140, "Service Job Card"),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 150),
	col("Status", "status", "Data", 140),
	col("Age (days)", "age_days", "Int", 100),
	col("Bucket", "bucket", "Data", 110),
	col("Technician", "assigned_technician", "Link", 130, "Employee"),
	col("Due", "sla_due_on", "Datetime", 150),
]

SQL = """
select jc.name, jc.branch, jc.customer_name, jc.status, jc.assigned_technician,
		       jc.sla_due_on, datediff(curdate(), date(jc.received_on)) as age_days,
		       case
		         when datediff(curdate(), date(jc.received_on)) <= 3 then '0-3 days'
		         when datediff(curdate(), date(jc.received_on)) <= 7 then '4-7 days'
		         when datediff(curdate(), date(jc.received_on)) <= 15 then '8-15 days'
		         else '15+ days' end as bucket
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status not in ('Delivered', 'Closed', 'Cancelled')
		  {conditions}
		order by age_days desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field=None)
