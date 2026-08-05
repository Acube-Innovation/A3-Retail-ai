# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Daily Service Register — scope 12.5 report #1."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Job Card", "name", "Link", 140, "Service Job Card"),
	col("Received", "received_on", "Datetime", 150),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 150),
	col("Mobile", "customer_mobile", "Data", 110),
	col("Device", "device_model", "Data", 150),
	col("IMEI", "imei_1", "Data", 130),
	col("Complaint", "complaint_description", "Data", 200),
	col("Technician", "assigned_technician", "Link", 120, "Employee"),
	col("Status", "status", "Data", 130),
	col("Amount", "grand_total", "Currency", 110),
]

SQL = """
select jc.name, jc.received_on, jc.branch, jc.customer_name, jc.customer_mobile,
		       jc.device_model, jc.imei_1, jc.complaint_description, jc.assigned_technician,
		       jc.status, jc.grand_total
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		order by jc.received_on desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.received_on')
