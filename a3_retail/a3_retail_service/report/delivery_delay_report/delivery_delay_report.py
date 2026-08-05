# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Delivery Delay Report — scope 12.5 report #10."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Job Card", "name", "Link", 140, "Service Job Card"),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 150),
	col("Promised", "estimated_delivery_date", "Datetime", 150),
	col("Delivered", "delivered_on", "Datetime", 150),
	col("Days Late", "days_late", "Int", 100),
	col("Reason", "reason", "Data", 200),
]

SQL = """
select jc.name, jc.branch, jc.customer_name, jc.estimated_delivery_date, jc.delivered_on,
		       datediff(ifnull(date(jc.delivered_on), curdate()),
		                date(jc.estimated_delivery_date)) as days_late,
		       coalesce(nullif(jc.delay_reason, ''), nullif(jc.hold_reason, ''), jc.status) as reason
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.estimated_delivery_date is not null
		  and (jc.delivered_on is null or jc.delivered_on > jc.estimated_delivery_date)
		  {conditions}
		having days_late > 0
		order by days_late desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
