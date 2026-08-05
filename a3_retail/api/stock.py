"""A3 Retail — stock API (scope 6.1).

Cross-branch availability is deliberately readable by every branch user: the
whole point of requirement 8 is that a counter can answer "do you have it in
Kochi?" without leaving POS. Writes stay restricted by User Permission.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate

from a3_retail.api import require_permission
from a3_retail.utils.branch import get_user_branch

MANAGER_ROLES = {"Branch Manager", "A3 Retail Admin", "Accounts Manager", "System Manager", "Auditor"}


def _may_see_valuation(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(MANAGER_ROLES & set(frappe.get_roles(user)))


@frappe.whitelist()
def availability_matrix(item_code: str) -> list[dict]:
	"""Quantity of an item at every branch.

	ignore_permissions rationale (scope 6.1): a branch user's Warehouse User
	Permission restricts *writes* to their own branch. Availability has to be
	visible everywhere or a counter could never raise a cross-branch transfer,
	so this runs as a read-only aggregate over `tabBin` returning quantity
	columns only. Valuation is appended separately, for manager roles alone.
	"""
	require_permission("Item", "read")

	rows = frappe.db.sql(
		"""
		select w.custom_branch as branch, b.warehouse, b.actual_qty, b.reserved_qty,
		       b.indented_qty, b.ordered_qty, b.projected_qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s and w.disabled = 0 and b.actual_qty != 0
		order by w.custom_branch, b.warehouse
		""",
		{"item_code": item_code},
		as_dict=True,
	)

	show_valuation = _may_see_valuation()
	for row in rows:
		row["available"] = flt(row["actual_qty"]) - flt(row["reserved_qty"])
		if show_valuation:
			row["stock_value"] = flt(
				frappe.db.get_value(
					"Bin", {"item_code": item_code, "warehouse": row["warehouse"]}, "stock_value"
				)
			)

	return rows


@frappe.whitelist()
def search_items(query: str = "", filters: dict | str | None = None, branch: str | None = None,
                 limit: int = 40) -> list[dict]:
	"""Item search for the Stock Explorer, with this branch's quantity attached."""
	require_permission("Item", "read")

	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}

	branch = branch or get_user_branch()
	conditions = ["i.disabled = 0"]
	values = {"query": f"%{query}%", "limit": int(limit)}

	if query:
		conditions.append("(i.name like %(query)s or i.item_name like %(query)s)")
	if filters.get("item_group"):
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = filters["item_group"]
	if filters.get("brand"):
		conditions.append("i.brand = %(brand)s")
		values["brand"] = filters["brand"]

	branch_join = ""
	qty_column = "0"
	if branch:
		branch_join = """
			left join (
				select b.item_code, sum(b.actual_qty) qty
				from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
				where w.custom_branch = %(branch)s group by b.item_code
			) mine on mine.item_code = i.name"""
		qty_column = "ifnull(mine.qty, 0)"
		values["branch"] = branch

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.brand, i.image,
		       {qty_column} as branch_qty, i.a3_is_device
		from `tabItem` i
		{branch_join}
		where {" and ".join(conditions)}
		order by i.item_name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)

	if filters.get("only_in_stock"):
		rows = [r for r in rows if flt(r["branch_qty"]) > 0]

	return rows


@frappe.whitelist()
def serial_list(item_code: str, warehouse: str | None = None, limit: int = 100) -> list[dict]:
	"""Serial numbers in stock, with their age in days."""
	require_permission("Serial No", "read")

	filters = {"item_code": item_code, "status": "Active"}
	if warehouse:
		filters["warehouse"] = warehouse

	rows = frappe.get_all(
		"Serial No",
		filters=filters,
		fields=["name", "a3_imei_1", "warehouse", "creation", "a3_warranty_state"],
		limit_page_length=int(limit),
		order_by="creation asc",
	)
	for row in rows:
		row["age_days"] = date_diff(nowdate(), row["creation"])
	return rows
