# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Spare parts and accessories (`/branch/parts`).

The counter's view of the two shelves it touches most: what a part fits, where
it is, what it is worth, and the four things anyone ever does with one — put it
on a repair, sell it, replace a failed one, or send it back.

None of that is invented here. `a3_retail_service.parts` already owns the parts
lifecycle for a job card (request, issue, return), `api.stock_control` owns the
shelf, and ERPNext owns the ledger. This module composes them for one screen.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me
from a3_retail.api.stock_control import LOW_STOCK_FLOOR, _available, _profile, _warehouses

# The two shelves this page manages, and the item groups behind each.
KINDS = {
	"parts": {"label": "Spare Parts", "groups": ("Spare Parts",)},
	"accessories": {"label": "Accessories", "groups": ("Accessories",)},
}

OPEN_JOB_STATUSES = ("Open", "Under Diagnosis", "Estimate Approved", "Awaiting Parts",
                     "In Progress", "On Hold", "Repair Completed", "QC Failed")


def _groups(kind: str) -> tuple:
	return KINDS.get(kind, KINDS["parts"])["groups"]


@frappe.whitelist()
def bootstrap(kind: str = "parts") -> dict:
	"""The shelf, the bench, and what this person may do with either."""
	employee = _me()
	profile = _profile(employee.branch)

	return {
		"branch": employee.branch,
		"kind": kind if kind in KINDS else "parts",
		"kinds": [{"key": key, "label": value["label"]} for key, value in KINDS.items()],
		"store": profile.default_warehouse,
		"bench": profile.service_warehouse or profile.default_warehouse,
		"warehouses": _warehouses(employee.branch),
		"brands": [brand for brand in frappe.get_all("Brand", pluck="name", order_by="name")
		           if not brand.startswith("_Test")],
		"can": {
			"issue": bool(frappe.has_permission("Service Job Card", "write")
			              and frappe.has_permission("Stock Entry", "create")),
			"sell": bool(frappe.has_permission("Sales Invoice", "create")),
			"replace": bool(frappe.has_permission("OEM Warranty Return", "create")),
			"request": bool(frappe.has_permission("Stock Request", "create")),
		},
	}


# ---------------------------------------------------------------------------
# The shelf
# ---------------------------------------------------------------------------
@frappe.whitelist()
def catalogue(kind: str = "parts", query: str = "", brand: str = "", status: str = "all",
              limit: int = 60) -> list[dict]:
	"""Every part or accessory this branch carries, with where it is and what it fits."""
	employee = _me()
	require_permission("Item", "read")

	profile = _profile(employee.branch)
	store = profile.default_warehouse
	bench = profile.service_warehouse or store

	conditions = ["i.disabled = 0", "i.item_group in %(groups)s"]
	values = {"groups": _groups(kind), "branch": employee.branch,
	          "limit": min(cint(limit) or 60, 200)}

	if query:
		conditions.append("(i.name like %(like)s or i.item_name like %(like)s "
		                  "or i.brand like %(like)s)")
		values["like"] = f"%{query}%"
	if brand:
		conditions.append("i.brand = %(brand)s")
		values["brand"] = brand

	rows = frappe.db.sql(
		f"""
		select i.name as item_code, i.item_name, i.item_group, i.brand, i.image,
		       ifnull(i.has_serial_no, 0) as has_serial,
		       ifnull(i.standard_rate, 0) as standard_rate,
		       ifnull(mine.qty, 0) as branch_qty,
		       ifnull(mine.reserved, 0) as reserved,
		       ifnull((select r.warehouse_reorder_level from `tabItem Reorder` r
		               where r.parent = i.name limit 1), 0) as reorder_level
		from `tabItem` i
		left join (
			select b.item_code, sum(b.actual_qty) qty, sum(b.reserved_qty) reserved
			from `tabBin` b join `tabWarehouse` w on w.name = b.warehouse
			where w.custom_branch = %(branch)s group by b.item_code
		) mine on mine.item_code = i.name
		where {" and ".join(conditions)}
		order by i.item_name
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		row["store_qty"] = _available(row["item_code"], store)
		row["bench_qty"] = _available(row["item_code"], bench) if bench != store else 0
		row["available"] = flt(row["branch_qty"]) - flt(row["reserved"])
		row["rate"] = _selling_rate(row["item_code"]) or flt(row["standard_rate"])
		row["fits"] = _fits(row["item_code"])
		row["status"] = _status(row)
		row["waiting"] = _waiting_for(row["item_code"], employee.branch)

	if status != "all":
		rows = [row for row in rows if row["status"] == status]
	return rows


def _status(row) -> str:
	available = flt(row["available"])
	if available <= 0:
		return "Out of Stock"
	if available <= flt(row["reorder_level"] or LOW_STOCK_FLOOR):
		return "Low Stock"
	return "Healthy"


def _selling_rate(item_code: str) -> float:
	from a3_retail.api.pos import _price_list

	price_list = _price_list(_profile(_me().branch))
	return flt(frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list, "selling": 1},
		"price_list_rate"))


def _fits(item_code: str) -> list[str]:
	"""Which handsets this part belongs to — from the models' own standard parts."""
	return frappe.db.sql_list(
		"""
		select name from `tabDevice Model`
		where standard_display_part = %(item)s or standard_battery_part = %(item)s
		order by name limit 6
		""",
		{"item": item_code},
	)


def _waiting_for(item_code: str, branch: str) -> int:
	"""How many open repairs are stopped waiting for this part."""
	return cint(frappe.db.sql(
		"""
		select count(distinct jc.name) from `tabJob Card Part` p
		join `tabService Job Card` jc on jc.name = p.parent
		where p.item_code = %(item)s and jc.branch = %(branch)s and jc.docstatus = 1
		  and p.part_status in ('Required', 'Awaiting Purchase', 'Awaiting Transfer')
		""",
		{"item": item_code, "branch": branch},
	)[0][0])


@frappe.whitelist()
def kpis(kind: str = "parts") -> dict:
	"""The cards over the shelf, for whichever shelf is open."""
	employee = _me()
	require_permission("Item", "read")

	rows = catalogue(kind=kind, limit=200)
	profile = _profile(employee.branch)
	bench = profile.service_warehouse or profile.default_warehouse

	issued_today = flt(frappe.db.sql(
		"""
		select sum(abs(sle.actual_qty)) from `tabStock Ledger Entry` sle
		join `tabItem` i on i.name = sle.item_code
		where sle.warehouse = %(bench)s and sle.posting_date = %(today)s
		  and sle.actual_qty < 0 and sle.is_cancelled = 0 and i.item_group in %(groups)s
		""",
		{"bench": bench, "today": nowdate(), "groups": _groups(kind)},
	)[0][0]) if bench else 0

	value = flt(frappe.db.sql(
		"""
		select sum(b.stock_value) from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where w.custom_branch = %(branch)s and i.item_group in %(groups)s
		""",
		{"branch": employee.branch, "groups": _groups(kind)},
	)[0][0])

	return {
		"lines": {"label": _("Items carried"), "value": len(rows)},
		"value": {"label": _("Stock value"), "value": value, "money": True},
		"low": {"label": _("Low stock"), "value": len([r for r in rows
		                                               if r["status"] == "Low Stock"]),
		        "tone": "warn", "filter": "Low Stock"},
		"out": {"label": _("Out of stock"), "value": len([r for r in rows
		                                                  if r["status"] == "Out of Stock"]),
		        "tone": "bad", "filter": "Out of Stock"},
		"reserved": {"label": _("Reserved"), "value": sum(flt(r["reserved"]) for r in rows)},
		"issued": {"label": _("Issued today"), "value": issued_today, "tone": "good"},
		"waiting": {"label": _("Repairs waiting"),
		            "value": sum(cint(r["waiting"]) for r in rows), "tone": "warn",
		            "tab": "waiting"},
	}


# ---------------------------------------------------------------------------
# The tabs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def tab(name: str, kind: str = "parts", limit: int = 40) -> dict:
	employee = _me()
	branch = employee.branch
	limit = min(cint(limit) or 40, 200)

	if name == "waiting":
		return {"rows": _waiting(branch, kind)}
	if name == "issued":
		return {"rows": _issued(branch, kind, limit)}
	if name == "movements":
		return {"rows": _movements(branch, kind, limit)}
	if name == "replacements":
		return {"rows": _replacements(branch, limit)}
	if name == "returns":
		return {"rows": _returns(branch, limit)}
	return {"rows": []}


def _waiting(branch: str, kind: str) -> list[dict]:
	"""Repairs standing still because a part has not arrived.

	`parts_position` is the service desk's own view of what has been chased —
	parts already on a transfer or a purchase. A stock desk also has to see the
	ones only written on a card so far, so those are added alongside, each under
	its own status.
	"""
	from a3_retail.a3_retail_service.parts import parts_position

	groups = _groups(kind)
	rows = [
		{"item_code": row["item_code"], "item_name": row["item_name"],
		 "required": flt(row["required"]), "available": flt(row["available"]),
		 "status": row["part_status"], "job_cards": row["job_cards"],
		 "reference": row.get("stock_request") or row.get("material_request") or ""}
		for row in parts_position(branch)
		if frappe.db.get_value("Item", row["item_code"], "item_group") in groups
	]

	rows += [
		{"item_code": row.item_code, "item_name": row.item_name, "required": flt(row.required),
		 "available": _available(row.item_code, _profile(branch).default_warehouse),
		 "status": row.part_status, "job_cards": row.job_cards, "reference": ""}
		for row in frappe.db.sql(
			"""
			select p.item_code, p.item_name, sum(p.qty) as required, p.part_status,
			       group_concat(distinct jc.name) as job_cards
			from `tabJob Card Part` p
			join `tabService Job Card` jc on jc.name = p.parent
			join `tabItem` i on i.name = p.item_code
			where jc.branch = %(branch)s and jc.docstatus = 1 and p.part_status = 'Required'
			  and i.item_group in %(groups)s
			group by p.item_code, p.item_name, p.part_status
			order by required desc
			""",
			{"branch": branch, "groups": groups}, as_dict=True)
	]
	return rows


def _issued(branch: str, kind: str, limit: int) -> list[dict]:
	return [
		{"job_card": row.parent, "item_code": row.item_code, "item_name": row.item_name,
		 "qty": flt(row.qty), "rate": flt(row.rate), "status": row.part_status,
		 "reference": row.stock_entry or "",
		 "covered": _("Warranty") if row.is_warranty_covered else _("Chargeable")}
		for row in frappe.db.sql(
			"""
			select p.parent, p.item_code, p.item_name, p.qty, p.rate, p.part_status,
			       p.stock_entry, p.is_warranty_covered, jc.modified
			from `tabJob Card Part` p
			join `tabService Job Card` jc on jc.name = p.parent
			join `tabItem` i on i.name = p.item_code
			where jc.branch = %(branch)s and jc.docstatus = 1
			  and p.part_status in ('Issued', 'Returned') and i.item_group in %(groups)s
			order by jc.modified desc limit %(limit)s
			""",
			{"branch": branch, "groups": _groups(kind), "limit": limit}, as_dict=True)
	]


def _movements(branch: str, kind: str, limit: int) -> list[dict]:
	warehouses = _warehouses(branch)
	if not warehouses:
		return []

	return [
		{"date": str(row.posting_date), "kind": row.voucher_type, "reference": row.voucher_no,
		 "item_code": row.item_code, "warehouse": row.warehouse, "qty": flt(row.actual_qty),
		 "balance": flt(row.qty_after_transaction), "user": row.owner,
		 "status": _("In") if flt(row.actual_qty) > 0 else _("Out")}
		for row in frappe.db.sql(
			"""
			select sle.posting_date, sle.voucher_type, sle.voucher_no, sle.item_code,
			       sle.warehouse, sle.actual_qty, sle.qty_after_transaction, sle.owner
			from `tabStock Ledger Entry` sle
			join `tabItem` i on i.name = sle.item_code
			where sle.warehouse in %(warehouses)s and sle.is_cancelled = 0
			  and i.item_group in %(groups)s
			order by sle.posting_date desc, sle.creation desc limit %(limit)s
			""",
			{"warehouses": warehouses, "groups": _groups(kind), "limit": limit}, as_dict=True)
	]


def _replacements(branch: str, limit: int) -> list[dict]:
	if not frappe.has_permission("OEM Warranty Return", "read"):
		return []

	return [
		{"name": row.name, "supplier": row.supplier, "date": str(row.dispatch_date or ""),
		 "kind": row.return_type, "items": cint(row.item_count),
		 "value": flt(row.total_claim_value), "status": row.status}
		for row in frappe.db.sql(
			"""
			select r.name, r.supplier, r.dispatch_date, r.return_type, r.total_claim_value,
			       -- `items` is the dict's own method; the count needs its own name.
			       r.status, (select count(*) from `tabOEM Return Item` it
			                  where it.parent = r.name) as item_count
			from `tabOEM Warranty Return` r
			where r.branch = %(branch)s and r.docstatus < 2
			order by r.modified desc limit %(limit)s
			""",
			{"branch": branch, "limit": limit}, as_dict=True)
	]


def _returns(branch: str, limit: int) -> list[dict]:
	"""Parts issued to a bench and sent back unused."""
	return [
		{"job_card": row.parent, "item_code": row.item_code, "item_name": row.item_name,
		 "qty": flt(row.qty), "status": row.part_status, "reference": row.stock_entry or ""}
		for row in frappe.db.sql(
			"""
			select p.parent, p.item_code, p.item_name, p.qty, p.part_status, p.stock_entry
			from `tabJob Card Part` p
			join `tabService Job Card` jc on jc.name = p.parent
			where jc.branch = %(branch)s and p.part_status = 'Returned'
			order by jc.modified desc limit %(limit)s
			""",
			{"branch": branch, "limit": limit}, as_dict=True)
	]


@frappe.whitelist()
def movements_for(item_code: str, limit: int = 25) -> list[dict]:
	"""One part's own history, for the popup behind its row."""
	employee = _me()
	warehouses = _warehouses(employee.branch)
	if not warehouses:
		return []

	return [
		{"date": str(row.posting_date), "kind": row.voucher_type, "reference": row.voucher_no,
		 "warehouse": row.warehouse, "qty": flt(row.actual_qty),
		 "balance": flt(row.qty_after_transaction),
		 "status": _("In") if flt(row.actual_qty) > 0 else _("Out")}
		for row in frappe.db.sql(
			"""
			select sle.posting_date, sle.voucher_type, sle.voucher_no, sle.warehouse,
			       sle.actual_qty, sle.qty_after_transaction
			from `tabStock Ledger Entry` sle
			where sle.item_code = %(item)s and sle.warehouse in %(warehouses)s
			  and sle.is_cancelled = 0
			order by sle.posting_date desc, sle.creation desc limit %(limit)s
			""",
			{"item": item_code, "warehouses": warehouses, "limit": cint(limit) or 25},
			as_dict=True)
	]


@frappe.whitelist()
def open_jobs(query: str = "", limit: int = 20) -> list[dict]:
	"""The repairs on the bench right now, for the assign popup."""
	employee = _me()
	require_permission("Service Job Card", "read")

	filters = {"branch": employee.branch, "docstatus": 1,
	           "status": ["in", OPEN_JOB_STATUSES]}
	if query:
		filters["name"] = ["like", f"%{query}%"]

	return frappe.get_all(
		"Service Job Card", filters=filters,
		fields=["name", "customer_name", "device_model", "imei_1", "status"],
		order_by="received_on desc", limit=min(cint(limit) or 20, 50),
	)


# ---------------------------------------------------------------------------
# The four things anyone does with a part
# ---------------------------------------------------------------------------
@frappe.whitelist()
def assign_to_service(job_card: str, item_code: str, qty: float = 1,
                      warranty: int = 0, serial_no: str | None = None) -> dict:
	"""Put a part on a repair, and move it to the bench if it is on the shelf.

	The row goes on the job card first, because that is what the repair is
	billed from; the stock movement is the job card's own `issue_parts`, which
	writes the Stock Entry.
	"""
	employee = _me()
	require_permission("Service Job Card", "write")

	doc = frappe.get_doc("Service Job Card", job_card)
	if doc.branch != employee.branch:
		frappe.throw(_("That repair belongs to another branch."), title=_("Not this branch"))
	if doc.status in ("Delivered", "Closed", "Cancelled"):
		frappe.throw(_("{0} is {1} — parts cannot be added to it now.").format(
			job_card, doc.status.lower()))

	qty = flt(qty) or 1
	profile = _profile(employee.branch)
	on_shelf = _available(item_code, profile.default_warehouse)

	row = doc.append("parts", {
		"item_code": item_code,
		"qty": qty,
		"warehouse": profile.service_warehouse or profile.default_warehouse,
		"serial_no": serial_no,
		"is_warranty_covered": cint(warranty),
		"part_status": "Required",
	})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	doc.reload()

	result = {"job_card": job_card, "item_code": item_code, "qty": qty,
	          "on_shelf": on_shelf, "row": row.name}

	if on_shelf >= qty:
		from a3_retail.a3_retail_service.parts import issue_parts

		issued = issue_parts(job_card)
		result["stock_entry"] = issued.get("stock_entry")
		result["status"] = "Issued"
		result["message"] = _("Moved from the store to the bench.")
		return result

	# Not on the store shelf — the parts module decides what that means: it is
	# already on the bench, another branch has it, or it has to be bought.
	from a3_retail.a3_retail_service.parts import request_part

	asked = request_part(job_card, row.name)
	result.update(asked)
	result["status"] = ("On the bench" if asked.get("action") == "none"
	                    else "Requested")
	return result


@frappe.whitelist()
def replace_part(job_card: str, item_code: str, defect: str, qty: float = 1,
                 supplier: str | None = None) -> dict:
	"""A part that failed under warranty: a new one out, the old one logged back.

	Two things have to happen and both are documents — the replacement goes on
	the repair at no charge to the customer, and the failed one is written down
	for the supplier to answer for.
	"""
	employee = _me()
	require_permission("Service Job Card", "write")
	if not (defect or "").strip():
		frappe.throw(_("Say what was wrong with the part being replaced."))

	given = assign_to_service(job_card, item_code, qty, warranty=1)

	claim = None
	if frappe.has_permission("OEM Warranty Return", "create"):
		claim = _log_defective(employee.branch, job_card, item_code, qty, defect, supplier)

	return {**given, "oem_return": claim, "defect": defect.strip()}


def _log_defective(branch: str, job_card: str, item_code: str, qty: float, defect: str,
                   supplier: str | None) -> str | None:
	"""Add the failed part to this branch's open OEM return, or start one."""
	supplier = supplier or frappe.db.get_value(
		"Item Default", {"parent": item_code}, "default_supplier"
	) or frappe.db.get_value("Supplier", {"disabled": 0}, "name")
	if not supplier:
		return None

	name = frappe.db.get_value(
		"OEM Warranty Return",
		{"branch": branch, "supplier": supplier, "status": "Draft", "docstatus": 0},
		"name",
	)
	doc = frappe.get_doc("OEM Warranty Return", name) if name else frappe.new_doc(
		"OEM Warranty Return")

	if not name:
		doc.supplier = supplier
		doc.branch = branch
		doc.return_type = "Defective Part Return"
		doc.status = "Draft"

	doc.append("items", {
		"item_code": item_code,
		"qty": flt(qty),
		"job_card": job_card,
		"defect_description": defect.strip(),
		# What the shop is out of pocket for: what it sells the part at, falling
		# back to the item's own rate when there is no price list entry.
		"claim_value": (_selling_rate(item_code)
		                or flt(frappe.db.get_value("Item", item_code, "standard_rate"))) * flt(qty),
	})

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def return_to_store(job_card: str) -> dict:
	"""Parts issued to the bench but not used go back on the shelf."""
	_me()
	from a3_retail.a3_retail_service.parts import return_unused_parts

	return return_unused_parts(job_card)


@frappe.whitelist()
def sell_url(item_code: str) -> str:
	"""Selling one is the counter's job — this hands the item to it."""
	_me()
	return f"/branch/sales?item={frappe.utils.quoted(item_code)}"
