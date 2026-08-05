# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stock Ageing and Dead Stock — scope 12.5 report #29."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Item", "item_code", "Link", 180, "Item"),
	col("Warehouse", "warehouse", "Link", 170, "Warehouse"),
	col("Serial / IMEI", "name", "Link", 150, "Serial No"),
	col("Received", "received_on", "Date", 110),
	col("Age (days)", "age_days", "Int", 100),
	col("Bucket", "bucket", "Data", 110),
	col("Value", "purchase_rate", "Currency", 120),
]

SQL = """
select s.item_code, s.warehouse, s.name, date(s.creation) as received_on, s.purchase_rate,
		       datediff(curdate(), date(s.creation)) as age_days,
		       case
		         when datediff(curdate(), date(s.creation)) <= 30 then '0-30 days'
		         when datediff(curdate(), date(s.creation)) <= 60 then '31-60 days'
		         when datediff(curdate(), date(s.creation)) <= 90 then '61-90 days'
		         else '90+ days (dead)' end as bucket
		from `tabSerial No` s
		where s.status = 'Active' and s.warehouse is not null
		order by age_days desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='s', branch_field='branch',
	                 date_field=None)
