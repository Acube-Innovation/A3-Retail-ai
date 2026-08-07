# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Stock Control (`/branch/stock`).

An operational layer over ERPNext, not a second stock engine. Every quantity on
this page is read from `tabBin` and the stock ledger; every action creates the
document ERPNext already expects — a Stock Request for an inter-branch move, its
own `dispatch`/`receive` for the two transfer legs, a Stock Entry for an internal
move, a Stock Reconciliation for an adjustment, a Material Request for
procurement. Nothing here writes a quantity anywhere.

The Stock Request doctype already owns the whole transfer lifecycle, so this
module calls it rather than restating it.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

LOW_STOCK_FLOOR = 5


def _branch() -> str:
	return _me().branch


def _warehouses(branch: str) -> list[str]:
	return frappe.get_all(
		"Warehouse", filters={"custom_branch": branch, "disabled": 0}, pluck="name"
	)


def _default_warehouse(branch: str) -> str:
	"""The shelf a branch sends from, or receives into.

	The Branch Profile names it; a branch without one falls back to its own
	store, and a branch with nothing at all is named in the error rather than
	failing later with a blank field.
	"""
	profile = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
	if profile:
		return profile

	for warehouse in _warehouses(branch):
		if "transit" not in warehouse.lower() and "damaged" not in warehouse.lower():
			return warehouse

	frappe.throw(_("{0} has no warehouse set up to send stock from.").format(branch),
	             title=_("No warehouse"))


def _profile(branch: str):
	return frappe.db.get_value(
		"Branch Profile", {"branch": branch},
		["name", "default_warehouse", "service_warehouse", "cost_center"], as_dict=True,
	) or frappe._dict()


# ---------------------------------------------------------------------------
# What the page needs before anything else
# ---------------------------------------------------------------------------
@frappe.whitelist()
def bootstrap() -> dict:
	"""The branch, its warehouses, and what this person is allowed to do."""
	employee = _me()
	branch = employee.branch

	return {
		"branch": branch,
		"warehouses": _warehouses(branch),
		"item_groups": frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name",
		                              order_by="name"),
		"brands": [brand for brand in frappe.get_all("Brand", pluck="name", order_by="name")
		           if not brand.startswith("_Test")],
		"branches": frappe.get_all("Branch", filters={"name": ["!=", branch]}, pluck="name",
		                           order_by="name"),
		"can": {
			"request": bool(frappe.has_permission("Stock Request", "create")),
			"approve": bool(frappe.has_permission("Stock Request", "submit")),
			"transfer": bool(frappe.has_permission("Stock Entry", "create")),
			"adjust": bool(frappe.has_permission("Stock Reconciliation", "create")),
			"procure": bool(frappe.has_permission("Material Request", "create")),
		},
		"as_of": frappe.utils.now_datetime().strftime("%H:%M"),
	}


# ---------------------------------------------------------------------------
# Live stock
# ---------------------------------------------------------------------------
def _stock_conditions(data: dict, branch: str) -> tuple[str, dict]:
	conditions = ["i.disabled = 0", "w.custom_branch = %(branch)s"]
	values = {"branch": branch, "floor": LOW_STOCK_FLOOR}

	if data.get("query"):
		conditions.append("(i.name like %(like)s or i.item_name like %(like)s "
		                  "or i.brand like %(like)s)")
		values["like"] = f"%{data['query']}%"
	if data.get("item_group"):
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = data["item_group"]
	if data.get("brand"):
		conditions.append("i.brand = %(brand)s")
		values["brand"] = data["brand"]
	if data.get("warehouse"):
		conditions.append("b.warehouse = %(warehouse)s")
		values["warehouse"] = data["warehouse"]

	kind = data.get("kind") or "all"
	if kind == "saleable":
		conditions.append("ifnull(i.is_sales_item, 1) = 1 and i.item_group != 'Spare Parts'")
	elif kind == "parts":
		conditions.append("i.item_group = 'Spare Parts'")
	elif kind == "accessories":
		conditions.append("i.item_group = 'Accessories'")
	elif kind == "damaged":
		conditions.append("w.name like '%%Damaged%%'")

	return " and ".join(conditions), values


def _status(row) -> str:
	available = flt(row["available"])
	if available <= 0:
		return "Out of Stock" if flt(row["incoming"]) <= 0 else "Incoming"
	if available <= flt(row["reorder_level"] or LOW_STOCK_FLOOR):
		return "Low Stock"
	return "Healthy"


@frappe.whitelist()
def live_stock(filters=None, page: int = 1, page_size: int = 25) -> dict:
	"""The shelf, as ERPNext holds it: one row per item and warehouse."""
	employee = _me()
	require_permission("Item", "read")

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _stock_conditions(data, employee.branch)
	page = max(cint(page), 1)
	size = min(max(cint(page_size) or 25, 5), 100)
	values.update({"start": (page - 1) * size, "size": size})

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.brand, i.image,
		       ifnull(i.has_serial_no, 0) as has_serial,
		       ifnull(i.has_batch_no, 0) as has_batch,
		       b.warehouse,
		       ifnull(b.actual_qty, 0) as actual_qty,
		       ifnull(b.reserved_qty, 0) as reserved_qty,
		       ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) as available,
		       ifnull(b.ordered_qty, 0) + ifnull(b.indented_qty, 0) as incoming,
		       ifnull(b.reserved_qty_for_production, 0) as outgoing,
		       ifnull((select r.warehouse_reorder_level from `tabItem Reorder` r
		               where r.parent = i.name and r.warehouse = b.warehouse limit 1), 0)
		           as reorder_level
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where {where}
		order by i.item_name, b.warehouse
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	total = frappe.db.sql(
		f"""select count(*) from `tabBin` b
		    join `tabWarehouse` w on w.name = b.warehouse
		    join `tabItem` i on i.name = b.item_code
		    where {where}""",
		values,
	)[0][0]

	for row in rows:
		row["status"] = _status(row)
		row["branches"] = _branches_holding(row["item_code"], employee.branch)

	status = data.get("status") or "all"
	if status != "all":
		rows = [row for row in rows if row["status"] == status]

	return {
		"rows": rows, "total": total, "page": page, "page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


def _branches_holding(item_code: str, branch: str) -> int:
	return cint(frappe.db.sql(
		"""
		select count(distinct w.custom_branch) from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s and b.actual_qty > 0
		  and w.custom_branch is not null and w.custom_branch != %(branch)s
		""",
		{"item_code": item_code, "branch": branch},
	)[0][0])


@frappe.whitelist()
def kpis(filters=None) -> dict:
	"""The nine cards, answering to the same filters as the table below them."""
	employee = _me()
	require_permission("Item", "read")

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _stock_conditions(data, employee.branch)

	row = frappe.db.sql(
		f"""
		-- `items` would land on the dict's own `.items` method, so it is named
		-- for what it counts instead.
		select count(distinct i.name) as item_count,
		       sum(ifnull(b.stock_value, 0)) as value,
		       sum(case when ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) <= 0
		                then 1 else 0 end) as out_of_stock,
		       sum(case when ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) > 0
		                 and ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) <= %(floor)s
		                then 1 else 0 end) as low_stock,
		       sum(ifnull(b.reserved_qty, 0)) as reserved
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where {where}
		""",
		values,
		as_dict=True,
	)[0]

	branch = employee.branch
	incoming = frappe.db.count("Stock Request", {"requesting_branch": branch,
	                                             "status": ["in", ("Approved", "In Transit")],
	                                             "docstatus": 1})
	outgoing = frappe.db.count("Stock Request", {"source_branch": branch,
	                                             "status": ["in", ("Approved", "In Transit")],
	                                             "docstatus": 1})
	pending = frappe.db.count("Stock Request", {"source_branch": branch,
	                                            "status": "Pending Approval", "docstatus": 1})
	devices = frappe.db.count("Service Job Card", {
		"branch": branch, "docstatus": 1,
		"status": ["not in", ("Delivered", "Closed", "Cancelled")],
	})

	return {
		"items": {"label": _("Total Items"), "value": cint(row.item_count), "tone": "sky"},
		"value": {"label": _("Stock Value"), "value": flt(row.value), "money": True, "tone": "sky"},
		"low": {"label": _("Low Stock"), "value": cint(row.low_stock), "tone": "warn",
		        "filter": {"status": "Low Stock"}},
		"out": {"label": _("Out of Stock"), "value": cint(row.out_of_stock), "tone": "bad",
		        "filter": {"status": "Out of Stock"}},
		"reserved": {"label": _("Reserved"), "value": flt(row.reserved), "tone": "sky",
		             "tab": "reservations"},
		"incoming": {"label": _("Incoming"), "value": incoming, "tone": "good",
		             "tab": "transfers", "sub": "incoming"},
		"outgoing": {"label": _("Outgoing"), "value": outgoing, "tone": "warn",
		             "tab": "transfers", "sub": "outgoing"},
		"requests": {"label": _("Pending Requests"), "value": pending, "tone": "warn",
		             "tab": "requests"},
		"devices": {"label": _("Customer Devices"), "value": devices, "tone": "good",
		            "tab": "devices"},
	}


@frappe.whitelist()
def network(item_code: str) -> dict:
	"""Where this item is across the whole network, and where it is coming from."""
	employee = _me()
	from a3_retail.api.stock import availability_matrix

	rows = availability_matrix(item_code)
	by_branch: dict[str, dict] = {}
	for row in rows:
		branch = row.get("branch") or _("Unassigned")
		bucket = by_branch.setdefault(branch, {
			"branch": branch, "warehouse": row["warehouse"], "available": 0,
			"reserved": 0, "incoming": 0,
		})
		bucket["available"] += flt(row["available"])
		bucket["reserved"] += flt(row["reserved_qty"])
		bucket["incoming"] += flt(row.get("ordered_qty")) + flt(row.get("indented_qty"))

	for bucket in by_branch.values():
		bucket["is_mine"] = bucket["branch"] == employee.branch
		bucket["status"] = ("Available" if bucket["available"] > LOW_STOCK_FLOOR
		                    else "Low" if bucket["available"] > 0
		                    else "Incoming" if bucket["incoming"] > 0 else "Out of Stock")

	branches = sorted(by_branch.values(),
	                  key=lambda row: (not row["is_mine"], -row["available"]))
	item = frappe.db.get_value("Item", item_code, ["item_name", "item_group", "brand"],
	                           as_dict=True) or frappe._dict()

	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"branch": employee.branch,
		"network_qty": sum(row["available"] for row in branches),
		"branches": branches,
		"recommendation": _recommend(branches, employee.branch),
	}


def _recommend(branches: list[dict], branch: str) -> str:
	"""What a person would say, looking at that table."""
	elsewhere = [row for row in branches if not row["is_mine"] and row["available"] > 0]
	if not elsewhere:
		return _("No branch has this in stock — procurement is the way to get it.")
	best = max(elsewhere, key=lambda row: row["available"])
	return _("{0} has {1} on the shelf — request from there.").format(
		best["branch"], int(best["available"]))


# ---------------------------------------------------------------------------
# The tabs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def tab(name: str, sub: str = "", limit: int = 40) -> dict:
	"""Every tab answers in the same shape, so the page renders them the same way."""
	employee = _me()
	branch = employee.branch
	limit = min(cint(limit) or 40, 200)

	if name == "overview":
		return {"panels": _overview(branch)}
	if name == "purchases":
		return {"rows": _purchases(branch, limit)}
	if name == "requests":
		return {"rows": _requests(branch, limit), "inbox": _inbox(branch)}
	if name == "transfers":
		return {"rows": _transfers(branch, sub or "incoming", limit)}
	if name == "receipts":
		return {"rows": _receipts(branch, limit)}
	if name == "movements":
		return {"rows": _movements(branch, limit)}
	if name == "adjustments":
		return {"rows": _adjustments(branch, limit)}
	if name == "reservations":
		return {"rows": _reservations(branch, limit)}
	if name == "service":
		return {"rows": _service_stock(branch, limit), "cards": _service_cards(branch)}
	if name == "devices":
		return {"rows": _customer_devices(branch, limit), "cards": _device_cards(branch)}
	return {"rows": []}


def _overview(branch: str) -> list[dict]:
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	low = frappe.db.sql(
		"""
		select i.item_name as title, b.warehouse as sub,
		       ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) as value
		from `tabBin` b join `tabItem` i on i.name = b.item_code
		where b.warehouse in %(warehouses)s
		  and ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) <= %(floor)s
		order by value limit 8
		""",
		{"warehouses": warehouses, "floor": LOW_STOCK_FLOOR},
		as_dict=True,
	)

	received = [
		{"title": row.name, "sub": f"{row.source_branch} → {row.requesting_branch}",
		 "value": str(row.received_on or "")[:16]}
		for row in frappe.get_all(
			"Stock Request", filters={"requesting_branch": branch, "status": "Received"},
			fields=["name", "source_branch", "requesting_branch", "received_on"],
			order_by="received_on desc", limit=5)
	]
	sent = [
		{"title": row.name, "sub": f"{row.source_branch} → {row.requesting_branch}",
		 "value": row.status}
		for row in frappe.get_all(
			"Stock Request", filters={"source_branch": branch, "docstatus": 1},
			fields=["name", "source_branch", "requesting_branch", "status"],
			order_by="modified desc", limit=5)
	]

	return [
		{"title": _("Low and out of stock"), "rows": [
			{"title": row.title, "sub": row.sub, "value": f"{flt(row.value):g}"} for row in low]},
		{"title": _("Recently received"), "rows": received},
		{"title": _("Recently sent"), "rows": sent},
	]


def _purchases(branch: str, limit: int) -> list[dict]:
	if not frappe.has_permission("Purchase Order", "read"):
		return []
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	return [
		{"name": row.name, "party": row.supplier, "date": str(row.transaction_date),
		 "items": row.items, "amount": flt(row.grand_total),
		 "expected": str(row.schedule_date or ""), "status": row.status}
		for row in frappe.db.sql(
			"""
			select po.name, po.supplier, po.transaction_date, po.grand_total, po.schedule_date,
			       po.status, (select count(*) from `tabPurchase Order Item` it
			                   where it.parent = po.name) as items
			from `tabPurchase Order` po
			where po.docstatus < 2 and exists (
				select 1 from `tabPurchase Order Item` it
				where it.parent = po.name and it.warehouse in %(warehouses)s)
			order by po.transaction_date desc limit %(limit)s
			""",
			{"warehouses": warehouses, "limit": limit}, as_dict=True)
	]


def _requests(branch: str, limit: int) -> list[dict]:
	return [
		{"name": row.name, "date": str(row.request_date or "")[:10], "party": row.source_branch,
		 "items": row.items, "priority": row.priority, "required": str(row.required_by or ""),
		 "status": row.status, "docstatus": row.docstatus}
		for row in frappe.db.sql(
			"""
			select sr.name, sr.request_date, sr.source_branch, sr.priority, sr.required_by,
			       sr.status, sr.docstatus,
			       (select count(*) from `tabStock Request Item` it where it.parent = sr.name) items
			from `tabStock Request` sr
			where sr.requesting_branch = %(branch)s and sr.docstatus < 2
			order by sr.request_date desc limit %(limit)s
			""",
			{"branch": branch, "limit": limit}, as_dict=True)
	]


def _inbox(branch: str) -> list[dict]:
	"""Requests other branches have put to this one, waiting for an answer."""
	return [
		{"name": row.name, "party": row.requesting_branch, "priority": row.priority,
		 "date": str(row.request_date or "")[:10], "items": _request_items(row.name),
		 "status": row.status}
		for row in frappe.get_all(
			"Stock Request",
			filters={"source_branch": branch, "status": "Pending Approval", "docstatus": 1},
			fields=["name", "requesting_branch", "priority", "request_date", "status"],
			order_by="request_date")
	]


def _request_items(request: str) -> list[dict]:
	rows = frappe.get_all(
		"Stock Request Item", filters={"parent": request},
		fields=["item_code", "item_name", "qty", "rate", "serial_no"], order_by="idx",
	)
	for row in rows:
		row["available"] = _available(row["item_code"], _source_warehouse(request))
	return rows


def _source_warehouse(request: str) -> str | None:
	return frappe.db.get_value("Stock Request", request, "source_warehouse")


def _available(item_code: str, warehouse: str | None) -> float:
	if not warehouse:
		return 0.0
	row = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
	                          ["actual_qty", "reserved_qty"], as_dict=True)
	return flt(row.actual_qty) - flt(row.reserved_qty) if row else 0.0


def _transfers(branch: str, direction: str, limit: int) -> list[dict]:
	field = "requesting_branch" if direction == "incoming" else "source_branch"
	return [
		{"name": row.name, "date": str(row.request_date or "")[:10],
		 "from": row.source_branch, "to": row.requesting_branch,
		 "items": row.items, "qty": flt(row.qty), "status": row.status,
		 "expected": str(row.required_by or ""),
		 "dispatched": str(row.dispatched_on or "")[:16],
		 "received": str(row.received_on or "")[:16]}
		for row in frappe.db.sql(
			f"""
			select sr.name, sr.request_date, sr.source_branch, sr.requesting_branch, sr.status,
			       sr.required_by, sr.dispatched_on, sr.received_on,
			       (select count(*) from `tabStock Request Item` it where it.parent = sr.name) items,
			       (select ifnull(sum(it.qty), 0) from `tabStock Request Item` it
			        where it.parent = sr.name) qty
			from `tabStock Request` sr
			where sr.{field} = %(branch)s and sr.docstatus = 1
			  and sr.status in ('Approved', 'In Transit', 'Received', 'Partially Received')
			order by sr.request_date desc limit %(limit)s
			""",
			{"branch": branch, "limit": limit}, as_dict=True)
	]


def _receipts(branch: str, limit: int) -> list[dict]:
	"""Transfers on their way here that nobody has acknowledged yet."""
	return [
		{"name": row.name, "party": row.source_branch, "date": str(row.dispatched_on or "")[:16],
		 "items": _request_items(row.name), "status": row.status,
		 "outward": row.outward_stock_entry}
		for row in frappe.get_all(
			"Stock Request",
			filters={"requesting_branch": branch, "status": "In Transit", "docstatus": 1},
			fields=["name", "source_branch", "dispatched_on", "status", "outward_stock_entry"],
			order_by="dispatched_on")
	]


def _movements(branch: str, limit: int) -> list[dict]:
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	return [
		{"date": str(row.posting_date), "kind": row.voucher_type, "reference": row.voucher_no,
		 "item": row.item_code, "warehouse": row.warehouse, "qty": flt(row.actual_qty),
		 "serial": (row.serial_no or "").split("\n")[0], "user": row.owner,
		 "status": _("In") if flt(row.actual_qty) > 0 else _("Out")}
		for row in frappe.db.sql(
			"""
			select sle.posting_date, sle.voucher_type, sle.voucher_no, sle.item_code,
			       sle.warehouse, sle.actual_qty, sle.serial_no, sle.owner
			from `tabStock Ledger Entry` sle
			where sle.warehouse in %(warehouses)s and sle.is_cancelled = 0
			order by sle.posting_date desc, sle.creation desc limit %(limit)s
			""",
			{"warehouses": warehouses, "limit": limit}, as_dict=True)
	]


def _adjustments(branch: str, limit: int) -> list[dict]:
	if not frappe.has_permission("Stock Reconciliation", "read"):
		return []
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	return [
		{"name": row.name, "date": str(row.posting_date), "warehouse": row.set_warehouse,
		 "reason": row.purpose, "items": row.items, "amount": flt(row.difference_amount),
		 "user": row.owner, "status": _("Submitted") if row.docstatus == 1 else _("Draft")}
		for row in frappe.db.sql(
			"""
			select sr.name, sr.posting_date, sr.set_warehouse, sr.purpose, sr.difference_amount,
			       sr.owner, sr.docstatus,
			       (select count(*) from `tabStock Reconciliation Item` it
			        where it.parent = sr.name) items
			from `tabStock Reconciliation` sr
			where sr.docstatus < 2 and (sr.set_warehouse in %(warehouses)s or exists (
				select 1 from `tabStock Reconciliation Item` it
				where it.parent = sr.name and it.warehouse in %(warehouses)s))
			order by sr.posting_date desc limit %(limit)s
			""",
			{"warehouses": warehouses, "limit": limit}, as_dict=True)
	]


def _reservations(branch: str, limit: int) -> list[dict]:
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	return [
		{"item": row.item_name or row.item_code, "warehouse": row.warehouse,
		 "reserved": flt(row.reserved_qty),
		 "available": flt(row.actual_qty) - flt(row.reserved_qty),
		 "status": "Reserved"}
		for row in frappe.db.sql(
			"""
			select b.item_code, i.item_name, b.warehouse, b.reserved_qty, b.actual_qty
			from `tabBin` b join `tabItem` i on i.name = b.item_code
			where b.warehouse in %(warehouses)s and ifnull(b.reserved_qty, 0) > 0
			order by b.reserved_qty desc limit %(limit)s
			""",
			{"warehouses": warehouses, "limit": limit}, as_dict=True)
	]


def _service_stock(branch: str, limit: int) -> list[dict]:
	profile = _profile(branch)
	warehouse = profile.service_warehouse or profile.default_warehouse
	if not warehouse:
		return []

	rows = frappe.db.sql(
		"""
		select i.name as item_code, i.item_name, b.warehouse,
		       ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) as available,
		       ifnull(b.reserved_qty, 0) as reserved,
		       ifnull((select r.warehouse_reorder_level from `tabItem Reorder` r
		               where r.parent = i.name and r.warehouse = b.warehouse limit 1), 0)
		           as reorder_level
		from `tabBin` b join `tabItem` i on i.name = b.item_code
		where b.warehouse = %(warehouse)s and i.item_group = 'Spare Parts'
		order by available limit %(limit)s
		""",
		{"warehouse": warehouse, "limit": limit},
		as_dict=True,
	)
	for row in rows:
		row["incoming"] = 0
		row["status"] = _status(row)
	return rows


def _service_cards(branch: str) -> list[dict]:
	profile = _profile(branch)
	warehouse = profile.service_warehouse or profile.default_warehouse
	issued = flt(frappe.db.sql(
		"""select sum(abs(sle.actual_qty)) from `tabStock Ledger Entry` sle
		   where sle.warehouse = %(warehouse)s and sle.posting_date = %(today)s
		     and sle.actual_qty < 0 and sle.is_cancelled = 0""",
		{"warehouse": warehouse, "today": nowdate()},
	)[0][0]) if warehouse else 0

	parts = _service_stock(branch, 200)
	return [
		{"label": _("Service parts on the shelf"), "value": len(parts)},
		{"label": _("Below reorder level"),
		 "value": len([row for row in parts if row["status"] != "Healthy"])},
		{"label": _("Issued today"), "value": issued},
	]


def _customer_devices(branch: str, limit: int) -> list[dict]:
	return [
		{"job_card": row.name, "customer": row.customer_name, "device": row.device_model,
		 "imei": row.imei_1, "received": str(row.received_on or "")[:16],
		 "status": row.status, "promised": str(row.estimated_delivery_date or "")[:16]}
		for row in frappe.get_all(
			"Service Job Card",
			filters={"branch": branch, "docstatus": 1,
			         "status": ["not in", ("Delivered", "Closed", "Cancelled")]},
			fields=["name", "customer_name", "device_model", "imei_1", "received_on", "status",
			        "estimated_delivery_date"],
			order_by="received_on desc", limit=limit)
	]


def _device_cards(branch: str) -> list[dict]:
	base = {"branch": branch, "docstatus": 1}
	open_statuses = ("Delivered", "Closed", "Cancelled")
	return [
		{"label": _("Devices held"), "value": frappe.db.count(
			"Service Job Card", {**base, "status": ["not in", open_statuses]})},
		{"label": _("Under repair"), "value": frappe.db.count(
			"Service Job Card", {**base, "status": ["in", ("In Progress", "Under Diagnosis")]})},
		{"label": _("Ready for delivery"), "value": frappe.db.count(
			"Service Job Card", {**base, "status": "Ready for Delivery"})},
		{"label": _("Past the promised date"), "value": frappe.db.count(
			"Service Job Card", {**base, "is_delayed": 1,
			                     "status": ["not in", open_statuses]})},
	]


# ---------------------------------------------------------------------------
# Alerts and activity
# ---------------------------------------------------------------------------
@frappe.whitelist()
def alerts() -> list[dict]:
	"""What a stock desk should look at first, each one a jump into a tab."""
	employee = _me()
	branch = employee.branch
	warehouses = _warehouses(branch)
	out = []

	if warehouses:
		low, empty = frappe.db.sql(
			"""
			select sum(case when qty > 0 and qty <= %(floor)s then 1 else 0 end),
			       sum(case when qty <= 0 then 1 else 0 end)
			from (select ifnull(b.actual_qty, 0) - ifnull(b.reserved_qty, 0) qty
			      from `tabBin` b where b.warehouse in %(warehouses)s) x
			""",
			{"warehouses": warehouses, "floor": LOW_STOCK_FLOOR},
		)[0]
		if cint(low):
			out.append({"tone": "warn", "text": _("{0} items below reorder level").format(cint(low)),
			            "filter": {"status": "Low Stock"}})
		if cint(empty):
			out.append({"tone": "bad", "text": _("{0} items out of stock").format(cint(empty)),
			            "filter": {"status": "Out of Stock"}})

	awaiting = frappe.db.count("Stock Request", {"requesting_branch": branch,
	                                             "status": "In Transit", "docstatus": 1})
	if awaiting:
		out.append({"tone": "sky", "text": _("{0} transfers awaiting receipt").format(awaiting),
		            "tab": "receipts"})

	approvals = frappe.db.count("Stock Request", {"source_branch": branch,
	                                              "status": "Pending Approval", "docstatus": 1})
	if approvals:
		out.append({"tone": "warn", "text": _("{0} requests awaiting your approval").format(approvals),
		            "tab": "requests"})

	overdue = frappe.db.count("Service Job Card", {
		"branch": branch, "docstatus": 1, "is_delayed": 1,
		"status": ["not in", ("Delivered", "Closed", "Cancelled")]})
	if overdue:
		out.append({"tone": "bad", "text": _("{0} customer devices past their promised date")
		            .format(overdue), "tab": "devices"})

	return out


@frappe.whitelist()
def activity(limit: int = 12) -> list[dict]:
	"""What happened on this branch's shelves, most recent first."""
	employee = _me()
	warehouses = _warehouses(employee.branch)
	if not warehouses:
		return []

	return [
		{"at": str(row.creation)[11:16], "date": str(row.posting_date),
		 "kind": row.voucher_type, "reference": row.voucher_no,
		 "text": _("{0} × {1} · {2}").format(
			 f"{flt(row.qty):g}", row.item_code, row.warehouse)}
		for row in frappe.db.sql(
			"""
			select sle.voucher_type, sle.voucher_no, sle.item_code, sle.warehouse,
			       sum(sle.actual_qty) qty, max(sle.creation) creation, max(sle.posting_date) posting_date
			from `tabStock Ledger Entry` sle
			where sle.warehouse in %(warehouses)s and sle.is_cancelled = 0
			group by sle.voucher_no, sle.item_code, sle.warehouse, sle.voucher_type
			order by creation desc limit %(limit)s
			""",
			{"warehouses": warehouses, "limit": cint(limit) or 12}, as_dict=True)
	]


# ---------------------------------------------------------------------------
# Actions — every one of them writes an ERPNext document
# ---------------------------------------------------------------------------
@frappe.whitelist()
def create_request(payload) -> dict:
	"""Ask another branch for stock. One Stock Request, the doctype's own rules."""
	employee = _me()
	require_permission("Stock Request", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	items = [row for row in (data.get("items") or []) if row.get("item_code")
	         and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Add at least one item to the request."))
	if not data.get("source_branch"):
		frappe.throw(_("Say which branch the stock should come from."))

	doc = frappe.new_doc("Stock Request")
	doc.requesting_branch = employee.branch
	doc.source_branch = data["source_branch"]
	doc.source_warehouse = data.get("source_warehouse") or _default_warehouse(data["source_branch"])
	doc.requesting_warehouse = data.get("warehouse") or _default_warehouse(employee.branch)
	doc.request_date = frappe.utils.now_datetime()
	doc.required_by = data.get("required_by") or None
	doc.priority = data.get("priority") or "Normal"
	doc.purpose = data.get("purpose") or "Stock Balancing"
	doc.reference_job_card = data.get("job_card") or None

	for row in items:
		doc.append("items", {
			"item_code": row["item_code"],
			"qty": flt(row["qty"]),
			"serial_no": row.get("serial_no"),
		})

	# The role check above is the gate. The document is written with permissions
	# bypassed for the same reason the counters do it: a Stock Request touches
	# warehouses and cost centers that shop-floor staff hold User Permissions on
	# but cannot open (scope 11.1, 6.1). Every rule on the doctype still runs.
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	return {"request": doc.name, "status": doc.status,
	        "print_url": print_url("Stock Request", doc.name)}


@frappe.whitelist()
def approve_request(request: str, qty_by_item=None) -> dict:
	"""Say yes to another branch — in full, or for what can actually be spared."""
	_me()
	require_permission("Stock Request", "submit")

	doc = _own_request(request, "source_branch")
	changes = frappe.parse_json(qty_by_item) if isinstance(qty_by_item, str) else (qty_by_item or {})

	if changes:
		for row in doc.get("items") or []:
			if row.item_code in changes:
				wanted = flt(changes[row.item_code])
				if wanted <= 0:
					frappe.throw(_("A quantity of zero is a rejection, not an approval."))
				row.db_set("qty", wanted, update_modified=False)

	doc.reload()
	doc.approve()
	return {"request": doc.name, "status": doc.status}


@frappe.whitelist()
def reject_request(request: str, reason: str) -> dict:
	_me()
	require_permission("Stock Request", "submit")
	if not (reason or "").strip():
		frappe.throw(_("Say why, so the branch that asked knows what to do next."))

	doc = _own_request(request, "source_branch")
	doc.reject(reason.strip())
	return {"request": doc.name, "status": doc.status}


@frappe.whitelist()
def dispatch_request(request: str) -> dict:
	"""Send it: source shelf → goods in transit, as a real Stock Entry."""
	_me()
	require_permission("Stock Entry", "create")

	doc = _own_request(request, "source_branch")
	entry = doc.dispatch()
	doc.reload()
	return {"request": doc.name, "status": doc.status, "stock_entry": entry,
	        "print_url": print_url("Stock Entry", entry)}


@frappe.whitelist()
def receive_request(request: str, received=None, reason: str | None = None) -> dict:
	"""Acknowledge what arrived: transit → this branch's shelf.

	A short delivery is a fact, not a formatting problem — it has to be written
	down and explained before the stock is taken in.
	"""
	_me()
	require_permission("Stock Entry", "create")

	doc = _own_request(request, "requesting_branch")
	counted = frappe.parse_json(received) if isinstance(received, str) else (received or {})

	short = []
	for row in doc.get("items") or []:
		if row.item_code not in counted:
			continue
		actual = flt(counted[row.item_code])
		if actual > flt(row.qty) + 0.0001:
			frappe.throw(_("{0}: {1} were sent, so {2} cannot have arrived.").format(
				row.item_code, f"{flt(row.qty):g}", f"{actual:g}"))
		if actual < flt(row.qty) - 0.0001:
			short.append(f"{row.item_code} {actual:g}/{flt(row.qty):g}")
			row.db_set("qty", actual, update_modified=False)

	if short and not (reason or "").strip():
		frappe.throw(
			_("Received quantity differs from what was sent ({0}). Write down why.").format(
				", ".join(short)),
			title=_("Short delivery"),
		)

	doc.reload()
	entry = doc.receive()
	if short:
		doc.add_comment("Comment", _("Short receipt: {0}. {1}").format(", ".join(short), reason))

	doc.reload()
	return {"request": doc.name, "status": doc.status, "stock_entry": entry,
	        "short": short, "print_url": print_url("Stock Entry", entry)}


def _own_request(request: str, field: str):
	employee = _me()
	doc = frappe.get_doc("Stock Request", request)
	if doc.get(field) != employee.branch:
		frappe.throw(_("{0} is not this branch's request to handle.").format(request),
		             title=_("Not this branch"))
	return doc


@frappe.whitelist()
def move_stock(payload) -> dict:
	"""An internal move — one warehouse to another, inside this branch."""
	employee = _me()
	require_permission("Stock Entry", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	source = data.get("source")
	target = data.get("target")
	mine = set(_warehouses(employee.branch))

	if source not in mine or target not in mine:
		frappe.throw(_("Both warehouses have to belong to {0}.").format(employee.branch))
	if source == target:
		frappe.throw(_("Pick two different warehouses."))

	items = [row for row in (data.get("items") or []) if row.get("item_code")
	         and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Nothing to move."))

	for row in items:
		available = _available(row["item_code"], source)
		if flt(row["qty"]) > available + 0.0001:
			frappe.throw(
				_("Only {0} of {1} are available in {2}. {3} were asked for.").format(
					f"{available:g}", row["item_code"], source, f"{flt(row['qty']):g}"),
				title=_("Not enough stock"),
			)

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = frappe.db.get_single_value("Global Defaults", "default_company")
	entry.posting_date = getdate(nowdate())
	entry.from_warehouse = source
	entry.to_warehouse = target
	if entry.meta.has_field("branch"):
		entry.branch = employee.branch
	entry.remarks = data.get("remarks")

	for row in items:
		entry.append("items", {
			"item_code": row["item_code"], "qty": flt(row["qty"]),
			"s_warehouse": source, "t_warehouse": target,
			"serial_no": "\n".join(row.get("serials") or []) or None,
			"use_serial_batch_fields": 1 if row.get("serials") else 0,
		})

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()

	return {"stock_entry": entry.name, "print_url": print_url("Stock Entry", entry.name)}


@frappe.whitelist()
def adjust_stock(payload) -> dict:
	"""Correct the shelf against what is actually on it — a Stock Reconciliation."""
	employee = _me()
	require_permission("Stock Reconciliation", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	warehouse = data.get("warehouse")
	if warehouse not in set(_warehouses(employee.branch)):
		frappe.throw(_("That warehouse does not belong to {0}.").format(employee.branch))

	items = [row for row in (data.get("items") or []) if row.get("item_code")]
	if not items:
		frappe.throw(_("Nothing to adjust."))
	if not (data.get("reason") or "").strip():
		frappe.throw(_("An adjustment needs a reason on it."))

	doc = frappe.new_doc("Stock Reconciliation")
	doc.company = frappe.db.get_single_value("Global Defaults", "default_company")
	doc.posting_date = getdate(nowdate())
	doc.set_posting_time = 1
	doc.purpose = "Stock Reconciliation"
	doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	doc.remarks = data["reason"].strip()

	for row in items:
		doc.append("items", {
			"item_code": row["item_code"],
			"warehouse": warehouse,
			"qty": flt(row.get("counted")),
		})

	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
	except frappe.exceptions.ValidationError as error:
		# ERPNext refuses a reconciliation that changes nothing, and says so in
		# its own words. A counter deserves the plain version.
		if "EmptyStockReconciliationItems" in error.__class__.__name__:
			frappe.throw(
				_("The count matches what the system already holds — nothing to adjust."),
				title=_("No difference"),
			)
		raise
	doc.submit()

	return {"adjustment": doc.name, "difference": flt(doc.difference_amount),
	        "print_url": print_url("Stock Reconciliation", doc.name)}


@frappe.whitelist()
def request_procurement(payload) -> dict:
	"""Nothing in the network — ask head office to buy it. A Material Request."""
	employee = _me()
	require_permission("Material Request", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	items = [row for row in (data.get("items") or []) if row.get("item_code")
	         and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Add at least one item."))

	profile = _profile(employee.branch)
	warehouse = data.get("warehouse") or profile.default_warehouse
	required_by = data.get("required_by") or frappe.utils.add_days(nowdate(), 7)

	doc = frappe.new_doc("Material Request")
	doc.material_request_type = "Purchase"
	doc.company = frappe.db.get_single_value("Global Defaults", "default_company")
	doc.transaction_date = getdate(nowdate())
	doc.schedule_date = getdate(required_by)
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	doc.set_warehouse = warehouse

	for row in items:
		doc.append("items", {
			"item_code": row["item_code"],
			"qty": flt(row["qty"]),
			"warehouse": warehouse,
			"schedule_date": getdate(required_by),
		})

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	if data.get("reason"):
		doc.add_comment("Comment", _("Raised from the branch stock desk: {0}").format(
			data["reason"]))

	return {"material_request": doc.name, "status": doc.status,
	        "print_url": print_url("Material Request", doc.name)}


@frappe.whitelist()
def serials(item_code: str, warehouse: str, limit: int = 100) -> list[dict]:
	"""The exact IMEIs available to move, so a transfer names them."""
	_me()
	require_permission("Serial No", "read")

	return frappe.db.sql(
		"""
		select s.name as serial_no, coalesce(nullif(s.a3_imei_1, ''), s.name) as imei,
		       s.item_code, s.warehouse, s.status
		from `tabSerial No` s
		where s.item_code = %(item_code)s and s.warehouse = %(warehouse)s and s.status = 'Active'
		order by s.creation limit %(limit)s
		""",
		{"item_code": item_code, "warehouse": warehouse, "limit": cint(limit) or 100},
		as_dict=True,
	)


@frappe.whitelist()
def print_url(doctype: str, name: str) -> str:
	"""The application's own print route — no second print system on this page."""
	_me()
	from urllib.parse import urlencode

	formats = {
		"Stock Request": "Stock Transfer Note",
		"Stock Entry": "Stock Transfer Note",
	}
	query = {"doctype": doctype, "name": name, "no_letterhead": 0, "_lang": "en"}
	chosen = formats.get(doctype)
	if chosen and frappe.db.exists("Print Format", chosen):
		query["format"] = chosen

	return f"/api/method/frappe.utils.print_format.download_pdf?{urlencode(query)}"
