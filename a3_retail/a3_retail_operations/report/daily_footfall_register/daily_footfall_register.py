# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Daily Footfall Register — scope 12.5 report #31."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Visit", "name", "Link", 130, "Branch Visit Log"),
	col("Time", "visit_datetime", "Datetime", 150),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Visitor", "visitor_name", "Data", 150),
	col("Mobile", "mobile_no", "Data", 110),
	col("Type", "visitor_type", "Data", 130),
	col("Purpose", "purpose", "Data", 150),
	col("Attended By", "attended_by", "Link", 130, "Employee"),
	col("Outcome", "outcome", "Data", 160),
	col("Sale Value", "sale_value", "Currency", 120),
]

SQL = """
select v.name, v.visit_datetime, v.branch, v.visitor_name, v.mobile_no, v.visitor_type,
		       v.purpose, v.attended_by, v.outcome, v.sale_value
		from `tabBranch Visit Log` v
		where 1 = 1 {conditions}
		order by v.visit_datetime desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='v', branch_field='branch',
	                 date_field='v.visit_datetime')
