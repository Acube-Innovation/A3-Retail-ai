# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Brand Wise Stock — what is on every shelf, one row per item.

The companion to Brand Wise Sales, read sideways: that report asks what each
brand *sold* over a period, this one asks what each brand is *holding* right
now. Which is why there is no date on it — stock is a photograph, not a film,
and a date range on a Bin would only invite the question of what it meant.

The branches are columns rather than rows on purpose. The question the shop
actually asks is "who has the Nokia?", and an answer spread down forty rows is
one the counter has to assemble in their head. Across, it is one line.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from a3_retail.reporting import col
from a3_retail.utils.permissions import get_permitted_branches

OTHERS = "Others (Non-Branded)"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	branches = _branches(filters)

	columns = [
		col("Item", "item_name", "Data", 260),
		col("Description", "description", "Data", 230),
		col("Brand", "brand", "Data", 130),
	]
	# One column per branch, in the order the shop lists them, then the row's
	# own total so the eye has somewhere to land.
	for branch in branches:
		columns.append(col(branch, _key(branch), "Float", 120))
	columns.append(col("Total", "total", "Float", 100))

	rows = _rows(filters, branches)
	return columns, rows, None, None, _summary(rows, branches)


def _branches(filters) -> list[str]:
	"""The branches this person may see, narrowed to the one they asked for."""
	permitted = set(get_permitted_branches() or [])
	names = frappe.get_all("Branch", pluck="name", order_by="name")
	if permitted:
		names = [n for n in names if n in permitted]
	if filters.get("branch"):
		names = [n for n in names if n == filters.branch]
	return names


def _key(branch: str) -> str:
	"""A fieldname a column can carry, from a branch name that has spaces in it."""
	return "b_" + frappe.scrub(branch)


def _rows(filters, branches: list[str]) -> list[dict]:
	conditions, values = [], {}

	if filters.get("brand"):
		wanted = filters.brand if isinstance(filters.brand, list) else [filters.brand]
		real = [b for b in wanted if b != OTHERS]
		clauses = []
		if real:
			values["brands"] = real
			clauses.append("i.brand in %(brands)s")
		if OTHERS in wanted:
			clauses.append("ifnull(i.brand, '') = ''")
		if clauses:
			conditions.append("(" + " or ".join(clauses) + ")")

	if filters.get("item_group"):
		values["item_group"] = filters.item_group
		conditions.append("i.item_group = %(item_group)s")

	if branches:
		values["branches"] = branches
		conditions.append("w.custom_branch in %(branches)s")
	else:
		return []

	where = (" and " + " and ".join(conditions)) if conditions else ""

	data = frappe.db.sql(f"""
		select i.name as item_code, i.item_name,
		       coalesce(nullif(i.description, ''), '') as description,
		       coalesce(nullif(i.brand, ''), %(others)s) as brand,
		       w.custom_branch as branch,
		       sum(b.actual_qty) as qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where ifnull(w.custom_branch, '') != '' {where}
		group by i.name, i.item_name, i.description, i.brand, w.custom_branch
	""", dict(values, others=OTHERS), as_dict=True)

	# Pivot: one row per item, a column per branch.
	rows: dict[str, dict] = {}
	for hit in data:
		row = rows.get(hit.item_code)
		if row is None:
			row = rows[hit.item_code] = {
				"item_code": hit.item_code,
				"item_name": hit.item_name or hit.item_code,
				"description": _plain(hit.description),
				"brand": hit.brand,
				"total": 0.0,
			}
			for branch in branches:
				row[_key(branch)] = 0.0
		row[_key(hit.branch)] = flt(hit.qty)
		row["total"] = flt(row["total"]) + flt(hit.qty)

	out = list(rows.values())
	if cint(filters.get("hide_empty", 1)):
		out = [row for row in out if row["total"] != 0]
	# Brand first, because that is what the report is for; then the item, so a
	# brand's range reads in order.
	out.sort(key=lambda row: (row["brand"], row["item_name"]))
	return out


def _plain(description: str) -> str:
	"""Item descriptions arrive as HTML from the desk; a table wants words."""
	if not description:
		return ""
	text = frappe.utils.strip_html(description).strip()
	return text[:180]


def _summary(rows: list[dict], branches: list[str]) -> list[dict]:
	"""What each branch is holding in total, above the table."""
	cards = [{"label": _("Items"), "value": len(rows), "datatype": "Int"}]
	for branch in branches:
		total = sum(flt(row.get(_key(branch))) for row in rows)
		cards.append({"label": branch, "value": total, "datatype": "Float"})
	return cards
