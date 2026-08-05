# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Device Model Failure Analysis — scope 12.5 report #11."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Device Model", "device_model", "Data", 180),
	col("Brand", "brand", "Link", 120, "Brand"),
	col("Job Cards", "jobs", "Int", 100),
	col("Top Category", "repair_category", "Data", 160),
	col("Average Cost", "avg_cost", "Currency", 130),
	col("Warranty Jobs", "warranty_jobs", "Int", 120),
]

SQL = """
select jc.device_model, jc.brand, count(*) as jobs,
		       jc.repair_category,
		       round(avg(jc.grand_total), 2) as avg_cost,
		       sum(case when jc.warranty_type like '%%Warranty%%' then 1 else 0 end) as warranty_jobs
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.device_model, '') != '' {conditions}
		group by jc.device_model, jc.brand, jc.repair_category
		order by jobs desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
