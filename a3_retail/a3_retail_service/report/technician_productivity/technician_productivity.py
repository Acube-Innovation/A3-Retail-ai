# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Technician Productivity — scope 12.5 report #5."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Technician", "assigned_technician", "Link", 140, "Employee"),
	col("Name", "employee_name", "Data", 150),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Jobs Delivered", "jobs", "Int", 120),
	col("Labour Value", "labour_value", "Currency", 130),
	col("Parts Value", "parts_value", "Currency", 130),
	col("Average TAT (h)", "avg_hours", "Float", 130),
	col("QC Failures", "qc_failures", "Int", 110),
]

SQL = """
select jc.assigned_technician, e.employee_name, jc.branch,
		       count(*) as jobs,
		       sum(jc.labour_total) as labour_value,
		       sum(jc.parts_total) as parts_value,
		       round(avg(timestampdiff(hour, jc.received_on, jc.delivered_on)), 1) as avg_hours,
		       (select count(distinct l.parent) from `tabJob Card Status Log` l
		        join `tabService Job Card` j2 on j2.name = l.parent
		        where l.to_status = 'QC Failed' and j2.assigned_technician = jc.assigned_technician
		          and date(j2.received_on) between %(from_date)s and %(to_date)s) as qc_failures
		from `tabService Job Card` jc
		left join `tabEmployee` e on e.name = jc.assigned_technician
		where jc.docstatus = 1 and jc.status in ('Delivered', 'Closed')
		  and jc.assigned_technician is not null {conditions}
		group by jc.assigned_technician, e.employee_name, jc.branch
		order by jobs desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='jc', branch_field='branch',
	                 date_field='jc.delivered_on')
