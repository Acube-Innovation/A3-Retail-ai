# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Repeat Repair Analysis — scope 12.5 report #7."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("IMEI", "imei_1", "Data", 140),
	col("Device", "device_model", "Data", 150),
	col("Customer", "customer_name", "Data", 150),
	col("Visits", "visits", "Int", 90),
	col("First Visit", "first_visit", "Datetime", 150),
	col("Last Visit", "last_visit", "Datetime", 150),
	col("Days Between", "days_between", "Int", 120),
	col("Total Billed", "billed", "Currency", 130),
]

SQL = """
select jc.imei_1, max(jc.device_model) as device_model, max(jc.customer_name) as customer_name,
		       count(*) as visits, min(jc.received_on) as first_visit, max(jc.received_on) as last_visit,
		       datediff(max(jc.received_on), min(jc.received_on)) as days_between,
		       sum(jc.grand_total) as billed
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.imei_1, '') != '' {conditions}
		group by jc.imei_1
		having visits > 1 and days_between <= 30
		order by visits desc, days_between asc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
