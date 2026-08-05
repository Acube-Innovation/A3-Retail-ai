# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Asset Register by Branch — scope 12.5 report #37."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Asset", "name", "Link", 150, "Asset"),
	col("Asset Name", "asset_name", "Data", 220),
	col("Category", "asset_category", "Link", 170, "Asset Category"),
	col("Branch", "branch", "Link", 120, "Branch"),
	col("Custodian", "custodian", "Link", 130, "Employee"),
	col("Since", "custody_since", "Date", 100),
	col("Purchase Value", "gross_purchase_amount", "Currency", 130),
	col("Condition", "condition", "Data", 120),
	col("Calibration Due", "calibration_due", "Date", 130),
]

SQL = """
select a.name, a.asset_name, a.asset_category, a.a3_branch as branch,
		       a.a3_assigned_employee as custodian, a.a3_custody_since as custody_since,
		       a.gross_purchase_amount, a.a3_asset_condition as `condition`,
		       a.a3_next_calibration_date as calibration_due
		from `tabAsset` a
		where a.docstatus = 1 {conditions}
		order by a.a3_branch, a.asset_name
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='a', branch_field='a3_branch',
	                 date_field=None)
