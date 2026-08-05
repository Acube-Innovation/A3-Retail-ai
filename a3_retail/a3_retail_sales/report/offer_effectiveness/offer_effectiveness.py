# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Offer Effectiveness — scope 12.5 report #14."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Campaign", "name", "Link", 180, "Seasonal Offer Campaign"),
	col("Type", "offer_type", "Data", 140),
	col("Valid From", "valid_from", "Date", 100),
	col("Valid Upto", "valid_upto", "Date", 100),
	col("Status", "status", "Data", 110),
	col("Budget Cap", "budget_cap", "Currency", 120),
	col("Consumed", "consumed_amount", "Currency", 120),
	col("Utilisation %", "utilisation", "Percent", 120),
]

SQL = """
select c.name, c.offer_type, c.valid_from, c.valid_upto, c.status,
		       c.budget_cap, c.consumed_amount
		from `tabSeasonal Offer Campaign` c
		where c.docstatus < 2
		order by c.valid_from desc
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c")
	for row in data:
		row["utilisation"] = percent(row.get("consumed_amount"), row.get("budget_cap"))
	return columns, data
