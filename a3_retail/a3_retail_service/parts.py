# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Parts lifecycle for a Service Job Card (scope 3.11).

The rules the shop actually follows:

| Situation                    | What happens                                        |
|------------------------------|-----------------------------------------------------|
| Available in the branch store| Stock Entry (Material Transfer) Store -> Service Bay |
| Available at another branch  | Stock Request; part goes Awaiting Transfer           |
| Not in the company at all    | Material Request (Purchase); part Awaiting Purchase  |
| Customer brought the part    | rate 0, no stock movement                            |
| Issued but not used          | return Stock Entry Service Bay -> Store              |

While any part is awaiting purchase or transfer the job card sits in
`Awaiting Parts` and the TAT clock is paused, so a supplier's delay never counts
against the branch's SLA.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import require_permission
from a3_retail.utils.branch import get_branch_profile

WAITING_STATUSES = ("Awaiting Purchase", "Awaiting Transfer")
SETTLED_STATUSES = ("Issued", "Received", "Returned")


def _profile(branch: str):
	profile = get_branch_profile(branch)
	if not profile:
		frappe.throw(_("Branch {0} has no Branch Profile.").format(branch))
	return profile


def _row(doc, row_name: str):
	for row in doc.get("parts") or []:
		if row.name == row_name:
			return row
	frappe.throw(_("Part row {0} is not on {1}.").format(row_name, doc.name))


# ---------------------------------------------------------------------------
# Requesting
# ---------------------------------------------------------------------------
@frappe.whitelist()
def request_part(job_card: str, row_name: str, source: str = "auto",
                 source_branch: str | None = None) -> dict:
	"""Raise the right document for a part the Service Bay does not have.

	`source` is "transfer", "purchase" or "auto" — auto picks a branch that has
	stock, and falls back to a purchase request when nobody does.
	"""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	row = _row(doc, row_name)
	profile = _profile(doc.branch)
	shortfall = flt(row.qty) - flt(row.available_qty)

	if shortfall <= 0 and source == "auto":
		return {"action": "none", "message": _("Stock is already available in the Service Bay.")}

	if source == "auto":
		source_branch = source_branch or find_branch_with_stock(row.item_code, shortfall, doc.branch)
		source = "transfer" if source_branch else "purchase"

	# An explicit request with stock already on hand still orders the full row
	# quantity — the quantity moved can never be zero or negative.
	request_qty = shortfall if shortfall > 0 else flt(row.qty)

	if source == "transfer":
		result = _raise_stock_request(doc, row, profile, source_branch, request_qty)
	else:
		result = _raise_material_request(doc, row, profile, request_qty)

	_move_to_awaiting_parts(doc)
	return result


def find_branch_with_stock(item_code: str, qty: float, exclude_branch: str | None = None) -> str | None:
	"""Which other branch can spare this part? Most stock first."""
	rows = frappe.db.sql(
		"""
		select w.custom_branch as branch, sum(b.actual_qty) as qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code = %(item_code)s
		  and w.disabled = 0
		  and ifnull(w.custom_branch, '') != ''
		  and w.custom_branch != %(exclude)s
		group by w.custom_branch
		having sum(b.actual_qty) >= %(qty)s
		order by qty desc
		""",
		{"item_code": item_code, "exclude": exclude_branch or "", "qty": flt(qty)},
		as_dict=True,
	)
	return rows[0].branch if rows else None


def _raise_stock_request(doc, row, profile, source_branch: str, qty: float) -> dict:
	if not frappe.db.exists("DocType", "Stock Request"):
		# Stock Request arrives in step 17; until then a transfer-type Material
		# Request keeps the flow working rather than silently doing nothing.
		return _raise_material_request(doc, row, profile, qty, purpose="Material Transfer")

	request = frappe.new_doc("Stock Request")
	request.requesting_branch = doc.branch
	request.requesting_warehouse = profile.service_warehouse
	request.source_branch = source_branch
	# Leave source_warehouse blank: Stock Request picks the branch warehouse that
	# actually holds the part (a spare lives in the Service Bay, not the store).
	request.purpose = "Service Job Card"
	request.reference_job_card = doc.name
	request.required_by = add_days(nowdate(), 2)
	request.append("items", {"item_code": row.item_code, "qty": qty})
	request.flags.ignore_permissions = True
	request.insert(ignore_permissions=True)

	row.db_set("stock_request", request.name, update_modified=False)
	row.db_set("part_status", "Awaiting Transfer", update_modified=False)

	return {"action": "transfer", "stock_request": request.name, "source_branch": source_branch}


def _raise_material_request(doc, row, profile, qty: float, purpose: str = "Purchase") -> dict:
	request = frappe.new_doc("Material Request")
	request.material_request_type = purpose
	request.company = doc.company
	request.transaction_date = getdate(nowdate())
	request.schedule_date = add_days(nowdate(), 3)
	# Material Request is not an accounting-dimension doctype, so it only has a
	# `branch` field where one has been added; the service warehouse carries the
	# branch either way.
	if request.meta.has_field("branch"):
		request.branch = doc.branch
	request.append(
		"items",
		{
			"item_code": row.item_code,
			"qty": qty,
			"warehouse": profile.service_warehouse,
			"schedule_date": add_days(nowdate(), 3),
		},
	)
	request.flags.ignore_permissions = True
	request.insert(ignore_permissions=True)
	request.submit()

	row.db_set("material_request", request.name, update_modified=False)
	row.db_set("part_status", "Awaiting Purchase", update_modified=False)

	return {"action": "purchase", "material_request": request.name}


def _move_to_awaiting_parts(doc):
	"""Park the job card while parts are on their way, pausing the TAT clock."""
	if doc.status == st.AWAITING_PARTS:
		return
	if not st.can_transition(doc.status, st.AWAITING_PARTS):
		return

	doc.reload()
	doc.status = st.AWAITING_PARTS
	doc.delay_reason = "Awaiting Parts"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Issuing and returning
# ---------------------------------------------------------------------------
@frappe.whitelist()
def issue_parts(job_card: str) -> dict:
	"""Move required parts from the branch store into the Service Bay."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)
	require_permission("Stock Entry", "create")

	profile = _profile(doc.branch)
	pending = [
		row
		for row in doc.get("parts") or []
		if not row.is_customer_provided and row.part_status in ("Required", "Reserved", "Received")
	]
	if not pending:
		return {"issued": 0, "message": _("Nothing to issue.")}

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = doc.company
	entry.posting_date = getdate(nowdate())
	entry.branch = doc.branch
	entry.from_warehouse = profile.default_warehouse
	entry.to_warehouse = profile.service_warehouse

	for row in pending:
		entry.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.qty),
				"s_warehouse": profile.default_warehouse,
				"t_warehouse": profile.service_warehouse,
				"serial_no": row.serial_no,
			},
		)

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()

	for row in pending:
		row.db_set("stock_entry", entry.name, update_modified=False)
		row.db_set("part_status", "Issued", update_modified=False)

	resume_if_parts_ready(doc.name)
	return {"issued": len(pending), "stock_entry": entry.name}


@frappe.whitelist()
def return_unused_parts(job_card: str, row_names: list | str | None = None) -> dict:
	"""Send parts that were issued but not used back to the store."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	if isinstance(row_names, str):
		row_names = frappe.parse_json(row_names)

	profile = _profile(doc.branch)
	rows = [
		row
		for row in doc.get("parts") or []
		if row.part_status == "Issued" and (not row_names or row.name in row_names)
	]
	if not rows:
		return {"returned": 0}

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = doc.company
	entry.posting_date = getdate(nowdate())
	entry.branch = doc.branch
	entry.from_warehouse = profile.service_warehouse
	entry.to_warehouse = profile.default_warehouse

	for row in rows:
		entry.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.qty),
				"s_warehouse": profile.service_warehouse,
				"t_warehouse": profile.default_warehouse,
				"serial_no": row.serial_no,
			},
		)

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()

	for row in rows:
		row.db_set("part_status", "Returned", update_modified=False)
		row.db_set("stock_entry", entry.name, update_modified=False)

	return {"returned": len(rows), "stock_entry": entry.name}


@frappe.whitelist()
def mark_part_received(job_card: str, row_name: str) -> dict:
	"""A requested part has arrived at the branch."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	row = _row(doc, row_name)
	row.db_set("part_status", "Received", update_modified=False)

	resumed = resume_if_parts_ready(doc.name)
	return {"part_status": "Received", "job_card_resumed": resumed}


def resume_if_parts_ready(job_card: str) -> bool:
	"""Leave `Awaiting Parts` once nothing is outstanding (scope 3.11)."""
	doc = frappe.get_doc("Service Job Card", job_card)
	if doc.status != st.AWAITING_PARTS:
		return False

	waiting = [row for row in doc.get("parts") or [] if row.part_status in WAITING_STATUSES]
	if waiting:
		return False

	if not st.can_transition(doc.status, st.IN_PROGRESS):
		return False

	doc.status = st.IN_PROGRESS
	doc.delay_reason = None
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return True


# ---------------------------------------------------------------------------
# Technician Workbench
# ---------------------------------------------------------------------------
@frappe.whitelist()
def my_job_cards(technician: str | None = None) -> dict:
	"""Kanban payload: the logged-in technician's live job cards by status."""
	require_permission("Service Job Card", "read")

	technician = technician or frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
	)
	if not technician:
		return {"technician": None, "columns": {}}

	rows = frappe.get_all(
		"Service Job Card",
		filters={
			"assigned_technician": technician,
			"docstatus": 1,
			"status": ["in", list(st.OPEN_STATUSES)],
		},
		fields=[
			"name", "status", "customer_name", "device_model", "imei_1", "priority",
			"sla_due_on", "is_delayed", "delay_hours", "complaint_description", "grand_total",
		],
		order_by="is_delayed desc, sla_due_on asc",
		limit_page_length=200,
	)

	columns: dict[str, list] = {}
	for row in rows:
		columns.setdefault(row.status, []).append(row)

	return {
		"technician": technician,
		"columns": columns,
		"total": len(rows),
		"delayed": sum(1 for r in rows if r.is_delayed),
	}


@frappe.whitelist()
def log_work_minutes(job_card: str, minutes: float, service_item: str | None = None) -> dict:
	"""Write timer output into a Job Card Labour row (scope 3.10)."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	minutes = flt(minutes)
	if minutes <= 0:
		frappe.throw(_("Logged time must be greater than zero."))

	technician = doc.assigned_technician
	target = None
	for row in doc.get("labour") or []:
		if service_item and row.service_item != service_item:
			continue
		if row.technician in (None, technician):
			target = row
			break

	if target:
		target.minutes = flt(target.minutes) + minutes
		target.technician = target.technician or technician
	else:
		service_item = service_item or _default_labour_item(doc)
		if not service_item:
			frappe.throw(_("Pick a service item before logging time."))
		doc.append(
			"labour",
			{"service_item": service_item, "qty": 1, "minutes": minutes, "technician": technician},
		)

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	return {"job_card": doc.name, "labour_total": flt(doc.labour_total)}


def _default_labour_item(doc) -> str | None:
	"""Labour item suggested by the first reported issue, else a sensible level."""
	for row in doc.get("reported_issues") or []:
		item = frappe.db.get_value("Service Issue Type", row.issue_type, "default_labour_item")
		if item:
			return item

	by_category = {
		"Software": "SRV-LAB-L1",
		"Hardware - Board Level": "SRV-LAB-L3",
	}
	fallback = by_category.get(doc.repair_category, "SRV-LAB-L2")
	return fallback if frappe.db.exists("Item", fallback) else None


@frappe.whitelist()
def parts_position(branch: str | None = None) -> list[dict]:
	"""What every open job card is still waiting for — feeds the control tower."""
	require_permission("Service Job Card", "read")

	conditions = {"jc.docstatus": 1}
	values = {"waiting": WAITING_STATUSES}
	branch_clause = ""
	if branch:
		branch_clause = "and jc.branch = %(branch)s"
		values["branch"] = branch

	return frappe.db.sql(
		f"""
		select p.item_code, p.item_name, sum(p.qty) as required,
		       min(p.available_qty) as available, p.part_status,
		       group_concat(distinct jc.name) as job_cards,
		       min(p.material_request) as material_request,
		       min(p.stock_request) as stock_request
		from `tabJob Card Part` p
		join `tabService Job Card` jc on jc.name = p.parent
		where jc.docstatus = 1 and p.part_status in %(waiting)s {branch_clause}
		group by p.item_code, p.item_name, p.part_status
		order by required desc
		""",
		values,
		as_dict=True,
	)
