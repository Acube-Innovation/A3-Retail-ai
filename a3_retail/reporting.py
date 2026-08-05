# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Shared plumbing for the 42 reports in the register (scope 12.5).

Every report is a Script Report over one SQL statement with a `{conditions}`
placeholder. `run_query` fills that in with the date range, the branch filter the
user chose, and — always — the branches that user is actually permitted to see.
That last part is why these are Script Reports rather than Query Reports: a
static query cannot narrow itself to the caller's User Permissions.
"""

import frappe
from frappe.utils import add_months, flt, nowdate

from a3_retail.utils.permissions import get_permitted_branches


def col(label: str, fieldname: str, fieldtype: str = "Data", width: int = 120,
        options: str | None = None) -> dict:
	column = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
	if options:
		column["options"] = options
	return column


def default_period(filters: dict) -> dict:
	filters = frappe._dict(filters or {})
	if not filters.get("from_date"):
		filters.from_date = add_months(nowdate(), -1)
	if not filters.get("to_date"):
		filters.to_date = nowdate()
	return filters


def branch_conditions(filters, alias: str, branch_field: str = "branch") -> tuple[str, dict]:
	"""`branch = %(branch)s` when one is chosen, always narrowed to what the user may see."""
	conditions, values = [], {}

	if filters.get("branch"):
		conditions.append(f"{alias}.`{branch_field}` = %(branch)s")
		values["branch"] = filters.branch

	permitted = get_permitted_branches()
	if permitted:
		names = ", ".join(frappe.db.escape(branch) for branch in permitted)
		conditions.append(f"({alias}.`{branch_field}` in ({names}) "
		                  f"or ifnull({alias}.`{branch_field}`, '') = '')")

	return (" and " + " and ".join(conditions) if conditions else ""), values


def date_conditions(filters, date_field: str | None) -> tuple[str, dict]:
	if not date_field:
		return "", {}
	return (
		f" and date({date_field}) between %(from_date)s and %(to_date)s",
		{"from_date": filters.get("from_date"), "to_date": filters.get("to_date")},
	)


def build_conditions(filters, alias: str, branch_field: str = "branch",
                     date_field: str | None = None, extra: str = "") -> tuple[str, dict]:
	branch_sql, values = branch_conditions(filters, alias, branch_field)
	date_sql, date_values = date_conditions(filters, date_field)
	values.update(date_values)
	values.update({k: v for k, v in (filters or {}).items() if v not in (None, "")})
	return branch_sql + date_sql + (f" and {extra}" if extra else ""), values


def run_query(columns: list[dict], sql: str, filters=None, alias: str = "t",
              branch_field: str = "branch", date_field: str | None = None,
              extra: str = "", post=None):
	"""The body of nearly every report in the register."""
	filters = default_period(filters)
	conditions, values = build_conditions(filters, alias, branch_field, date_field, extra)
	data = frappe.db.sql(sql.format(conditions=conditions), values, as_dict=True)
	if post:
		data = post(data, filters)
	return columns, data


def percent(numerator, denominator) -> float:
	denominator = flt(denominator)
	return round(flt(numerator) / denominator * 100, 2) if denominator else 0.0


def add_total_row(data: list[dict], label_field: str, numeric_fields: list[str],
                  label: str = "Total") -> list[dict]:
	if not data:
		return data
	total = {label_field: label}
	for field in numeric_fields:
		total[field] = sum(flt(row.get(field)) for row in data)
	return data + [total]
