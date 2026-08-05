# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Incentive Payout Register — scope 12.5 report #36."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Run", "parent", "Link", 140, "Incentive Calculation Run"),
	col("Scheme", "scheme", "Link", 170, "Employee Incentive Scheme"),
	col("Employee", "employee", "Link", 130, "Employee"),
	col("Name", "employee_name", "Data", 150),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Target", "target", "Float", 110),
	col("Achieved", "achieved", "Float", 110),
	col("Achievement %", "achievement_percent", "Percent", 130),
	col("Base", "base_incentive", "Currency", 110),
	col("Spiff", "spiff_amount", "Currency", 100),
	col("Clawback", "clawback_amount", "Currency", 110),
	col("Gates", "gates", "Data", 200),
	col("Payout", "final_incentive", "Currency", 120),
]

SQL = """
select i.parent, r.scheme, i.employee, i.employee_name, i.branch, i.target, i.achieved,
		       i.achievement_percent, i.base_incentive, i.spiff_amount, i.clawback_amount,
		       i.final_incentive,
		       case when i.gates_passed = 1 then 'Pass'
		            else concat('Fail — ', ifnull(i.gate_failure_reason, '')) end as gates
		from `tabIncentive Calculation Item` i
		join `tabIncentive Calculation Run` r on r.name = i.parent
		where r.docstatus = 1 {conditions}
		order by i.parent desc, i.final_incentive desc
"""


def execute(filters=None):
	return run_query(COLUMNS, SQL, filters, alias='r', branch_field='branch',
	                 date_field='r.from_date')
