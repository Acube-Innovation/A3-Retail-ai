# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stock Adjustment Register — what a count changed, by how much and by how many.

One line per item on a submitted Stock Reconciliation: what the system believed
was on the shelf, what the count actually found, and the gap in both pieces and
money.

Two things are worth knowing about where the numbers come from.

**The difference is worked out here rather than read.** ERPNext does store
`quantity_difference` on the row, but as a read-only *string* — `'1.0'`,
`'-4.0'` — so summing it in SQL adds text and totals come out wrong. The
subtraction is the same arithmetic ERPNext did and gives a number.

**Opening Stock is excluded unless asked for.** A Stock Reconciliation carries
a purpose, and the migration brought the shop's opening balances in under
`Opening Stock` — 49 documents worth about ₹2.47 crore against ₹34 lakh of real
counting. Left in, the register would be a report about the migration. The
filter defaults to `Stock Reconciliation`, and anyone who wants the openings can
ask for them.
"""

import frappe
from frappe.utils import flt

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Adjustment", "adjustment", "Link", 150, "Stock Reconciliation"),
	col("Date", "posting_date", "Date", 95),
	col("Branch", "branch", "Link", 150, "Branch"),
	col("Purpose", "purpose", "Data", 130),
	col("Item", "item_code", "Link", 180, "Item"),
	col("Item Name", "item_name", "Data", 200),
	col("Godown", "warehouse", "Link", 170, "Warehouse"),
	col("System Qty", "system_qty", "Float", 100),
	col("Counted Qty", "counted_qty", "Float", 100),
	col("Qty Difference", "qty_difference", "Float", 120),
	# Float, not Currency: the page totals every Currency column, and a column
	# of rates added together is a number that means nothing.
	col("Rate", "valuation_rate", "Float", 110),
	col("System Value", "system_value", "Currency", 130),
	col("Counted Value", "counted_value", "Currency", 130),
	col("Amount Difference", "amount_difference", "Currency", 150),
]

SQL = """
	select sr.name                                as adjustment,
	       sr.posting_date,
	       sr.branch,
	       sr.purpose,
	       it.item_code,
	       i.item_name,
	       it.warehouse,
	       ifnull(it.current_qty, 0)              as system_qty,
	       ifnull(it.qty, 0)                      as counted_qty,
	       ifnull(it.qty, 0) - ifnull(it.current_qty, 0)        as qty_difference,
	       ifnull(it.valuation_rate, it.current_valuation_rate) as valuation_rate,
	       ifnull(it.current_amount, 0)           as system_value,
	       ifnull(it.amount, 0)                   as counted_value,
	       ifnull(it.amount, 0) - ifnull(it.current_amount, 0)  as amount_difference
	from `tabStock Reconciliation Item` it
	join `tabStock Reconciliation` sr on sr.name = it.parent
	left join `tabItem` i on i.name = it.item_code
	where sr.docstatus = 1 {conditions}
	order by sr.posting_date desc, sr.name, it.idx
"""


def execute(filters=None):
	filters = frappe._dict(filters or {})

	conditions = []
	if filters.get("purpose"):
		conditions.append("sr.purpose = %(purpose)s")
	else:
		# The shop means counting, not the migration's opening balances.
		conditions.append("sr.purpose = 'Stock Reconciliation'")
	if filters.get("item_code"):
		conditions.append("it.item_code = %(item_code)s")
	if cint_or_zero(filters.get("only_differences")):
		# A count that found exactly what was expected is not an adjustment;
		# it is the shelf agreeing with the books.
		conditions.append("ifnull(it.qty, 0) <> ifnull(it.current_qty, 0)")

	columns, data = run_query(
		COLUMNS, SQL, filters, alias="sr", branch_field="branch",
		date_field="sr.posting_date", extra=" and ".join(conditions))

	# No total row is appended. The reports page sums every Currency column it
	# is given, so a "Total" row in the data would be counted a second time and
	# every money figure would come out doubled.
	return columns, data, None, None, _summary_cards(data)


def cint_or_zero(value) -> int:
	try:
		return int(flt(value))
	except (TypeError, ValueError):
		return 0


def _summary_cards(data) -> list[dict]:
	"""The four numbers the shop asked for, as cards above the table.

	Gained and lost are kept apart on purpose. A count that found 50 extra of
	one thing and 50 missing of another nets to zero, and that is the one case
	where a net figure is most misleading — nothing wrong, says the total,
	while a hundred pieces moved.
	"""
	rows = data or []

	qty_up = sum(flt(r["qty_difference"]) for r in rows if flt(r["qty_difference"]) > 0)
	qty_down = sum(flt(r["qty_difference"]) for r in rows if flt(r["qty_difference"]) < 0)
	value_up = sum(flt(r["amount_difference"]) for r in rows
	               if flt(r["amount_difference"]) > 0)
	value_down = sum(flt(r["amount_difference"]) for r in rows
	                 if flt(r["amount_difference"]) < 0)

	# `datatype` is the key the reports page reads, not `fieldtype`.
	return [
		{"label": "Pieces found extra", "value": qty_up, "datatype": "Float"},
		{"label": "Pieces missing", "value": abs(qty_down), "datatype": "Float"},
		{"label": "Net value change", "value": value_up + value_down,
		 "datatype": "Currency"},
		{"label": "Value written off", "value": abs(value_down),
		 "datatype": "Currency"},
	]
