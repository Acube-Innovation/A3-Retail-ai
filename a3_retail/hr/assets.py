# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Asset custody, calibration and exit clearance (scope 10.3).

ERPNext's Asset Movement already models issue/transfer/receipt; this layer keeps
a denormalised "who holds it now" on the Asset so a branch manager can answer the
question without walking the movement ledger, and refuses to let an employee be
marked Left while a soldering station is still in their drawer.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from a3_retail.utils import commit_if_not_testing

CALIBRATION_LEAD_DAYS = 30


def sync_custody(doc, method=None):
	"""An Asset Movement is the source of truth for custody."""
	for row in doc.get("assets") or []:
		if not row.asset:
			continue

		if doc.purpose == "Issue":
			holder = row.get("to_employee") or doc.get("to_employee")
			if holder:
				frappe.db.set_value(
					"Asset",
					row.asset,
					{
						"a3_assigned_employee": holder,
						"a3_custody_since": getdate(doc.transaction_date),
					},
					update_modified=False,
				)
		elif doc.purpose == "Receipt":
			frappe.db.set_value(
				"Asset",
				row.asset,
				{"a3_assigned_employee": None, "a3_custody_since": None},
				update_modified=False,
			)
		elif doc.purpose == "Transfer" and row.get("target_location"):
			branch = frappe.db.get_value("Location", row.target_location, "a3_branch") \
				if frappe.db.has_column("Location", "a3_branch") else None
			if branch:
				frappe.db.set_value("Asset", row.asset, "a3_branch", branch, update_modified=False)


def clear_custody(doc, method=None):
	"""Cancelling a movement must not leave a stale holder on the asset."""
	for row in doc.get("assets") or []:
		if row.asset and doc.purpose == "Issue":
			frappe.db.set_value(
				"Asset",
				row.asset,
				{"a3_assigned_employee": None, "a3_custody_since": None},
				update_modified=False,
			)


def held_by(employee: str) -> list[str]:
	if not frappe.db.has_column("Asset", "a3_assigned_employee"):
		return []
	return frappe.get_all(
		"Asset",
		filters={
			"a3_assigned_employee": employee,
			"docstatus": 1,
			"status": ["not in", ["Scrapped", "Sold"]],
		},
		pluck="asset_name",
	)


def block_exit_with_assets(doc, method=None):
	"""Exit clearance: an employee cannot be marked Left holding company assets."""
	if doc.get("status") != "Left":
		return

	before = doc.get_doc_before_save()
	if before and before.get("status") == "Left":
		return

	assets = held_by(doc.name)
	if assets:
		frappe.throw(
			_("{0} still holds: {1}. Record the return through an Asset Movement first.").format(
				doc.employee_name or doc.name, ", ".join(assets)
			),
			title=_("Exit Clearance Pending"),
		)


@frappe.whitelist()
def custody_register(branch: str | None = None) -> list[dict]:
	"""Who holds what, for the branch manager's handover sheet."""
	if not frappe.db.has_column("Asset", "a3_assigned_employee"):
		return []

	filters = {"docstatus": 1, "a3_assigned_employee": ["is", "set"]}
	if branch:
		filters["a3_branch"] = branch

	return frappe.get_all(
		"Asset",
		filters=filters,
		fields=[
			"name",
			"asset_name",
			"a3_branch as branch",
			"a3_asset_class as asset_class",
			"a3_assigned_employee as employee",
			"a3_custody_since as since",
			"a3_next_calibration_date as calibration_due",
		],
		order_by="a3_branch asc, asset_name asc",
	)


def calibration_reminders() -> int:
	"""Weekly — raise a ToDo for instruments due for calibration."""
	if not frappe.db.has_column("Asset", "a3_next_calibration_date"):
		return 0

	rows = frappe.get_all(
		"Asset",
		filters={
			"docstatus": 1,
			"a3_is_calibration_required": 1,
			"a3_next_calibration_date": ["<=", add_days(nowdate(), CALIBRATION_LEAD_DAYS)],
		},
		fields=["name", "asset_name", "a3_assigned_employee", "a3_next_calibration_date"],
	)

	created = 0
	for row in rows:
		if frappe.db.exists(
			"ToDo", {"reference_type": "Asset", "reference_name": row.name, "status": "Open"}
		):
			continue

		user = (
			frappe.db.get_value("Employee", row.a3_assigned_employee, "user_id")
			if row.a3_assigned_employee
			else None
		)
		todo = frappe.new_doc("ToDo")
		todo.allocated_to = user
		todo.reference_type = "Asset"
		todo.reference_name = row.name
		todo.date = row.a3_next_calibration_date
		todo.priority = "High"
		todo.description = _("{0} is due for calibration on {1}.").format(
			row.asset_name, row.a3_next_calibration_date
		)
		todo.flags.ignore_permissions = True
		try:
			todo.insert(ignore_permissions=True)
			created += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: calibration ToDo {row.name}")

	commit_if_not_testing()
	return created
