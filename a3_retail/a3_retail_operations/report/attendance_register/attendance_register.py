# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Attendance Register — scope 12.5 report #35."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Employee", "employee", "Link", 130, "Employee"),
	col("Name", "employee_name", "Data", 160),
	col("Branch", "branch", "Link", 120, "Branch"),
	col("Present", "present", "Int", 90),
	col("Half Day", "half_day", "Int", 90),
	col("Absent", "absent", "Int", 90),
	col("On Leave", "on_leave", "Int", 90),
	col("Marked Days", "marked", "Int", 110),
	col("Attendance %", "attendance_percent", "Percent", 130),
]

SQL = """
select a.employee, a.employee_name, a.a3_branch as branch,
		       sum(case when a.status = 'Present' then 1 else 0 end) as present,
		       sum(case when a.status = 'Half Day' then 1 else 0 end) as half_day,
		       sum(case when a.status = 'Absent' then 1 else 0 end) as absent,
		       sum(case when a.status = 'On Leave' then 1 else 0 end) as on_leave,
		       count(*) as marked
		from `tabAttendance` a
		where a.docstatus = 1 {conditions}
		group by a.employee, a.employee_name, a.a3_branch
		order by a.employee_name
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="a", branch_field="a3_branch",
	                          date_field="a.attendance_date")
	for row in data:
		effective = (row.get("present") or 0) + (row.get("half_day") or 0) * 0.5
		row["attendance_percent"] = percent(effective, row.get("marked"))
	return columns, data
