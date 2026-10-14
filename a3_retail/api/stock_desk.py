# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Desk-side corrections to stock documents.

The branch screens under /retail are the counter's. This module is the other
side of the house: the few operations a manager does from the ERPNext desk,
where the thing being corrected has already been posted to the ledger.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate, nowdate

from a3_retail.api import require_permission


@frappe.whitelist()
def redate(name: str, posting_date: str, posting_time: str | None = None) -> dict:
	"""Put a submitted Stock Entry on a different day.

	A posting date cannot simply be edited once the entry is submitted, and
	nothing good comes of making it: the stock and ledger entries it wrote stay
	on the old day, and the valuation quietly stops agreeing with itself. The
	only correct way to move one is to reverse it and post it again, which is
	what this does — cancel the original, build its replacement on the new day,
	submit that. Both documents stay on file, which is the audit trail.

	The replacement is built from the original's figures rather than copied from
	the cancelled document, because the serial and batch bundles a copy would
	carry have been cancelled along with it and cannot be submitted again. Named
	serial numbers go on the new entry as text and ERPNext makes fresh bundles.
	"""
	require_permission("Stock Entry", "cancel")
	require_permission("Stock Entry", "submit")

	old = frappe.get_doc("Stock Entry", name)
	if old.docstatus != 1:
		frappe.throw(
			_("Only a submitted entry needs this. A draft's date can be edited "
			  "on the form, and a cancelled one is already undone."),
			title=_("Not submitted"),
		)

	when = getdate(posting_date)
	if when > getdate(nowdate()):
		frappe.throw(_("An entry cannot be dated in the future."), title=_("Date"))
	if when == getdate(old.posting_date) and not posting_time:
		frappe.throw(_("That is the day it is already on."), title=_("No change"))

	rows = [_row(row) for row in old.items]
	old.cancel()

	fresh = frappe.new_doc("Stock Entry")
	for field in ("stock_entry_type", "purpose", "company", "from_warehouse",
	              "to_warehouse", "project", "letter_head"):
		if old.meta.has_field(field):
			fresh.set(field, old.get(field))
	if fresh.meta.has_field("branch"):
		fresh.branch = old.get("branch")

	fresh.set_posting_time = 1
	fresh.posting_date = when
	fresh.posting_time = posting_time or old.posting_time
	# Why it moved, kept with the entry that is now the real one.
	fresh.remarks = " ".join(filter(None, [
		(old.remarks or "").strip(),
		_("Re-dated from {0}, replacing {1}.").format(
			formatdate(old.posting_date), old.name),
	])).strip()

	for row in rows:
		fresh.append("items", row)

	fresh.insert()
	fresh.submit()

	return {
		"name": fresh.name,
		"cancelled": old.name,
		"posting_date": str(fresh.posting_date),
	}


def _row(row) -> dict:
	"""One line of the original, as figures the new entry can be built from."""
	out = {
		"item_code": row.item_code,
		"qty": row.qty,
		"uom": row.uom,
		"stock_uom": row.stock_uom,
		"conversion_factor": row.conversion_factor,
		"s_warehouse": row.s_warehouse,
		"t_warehouse": row.t_warehouse,
		"cost_center": row.cost_center,
		"expense_account": row.expense_account,
	}

	serials = _serials(row)
	batch = row.batch_no or _batch(row)
	if serials or batch:
		# The named numbers, not the cancelled bundle that held them.
		out["use_serial_batch_fields"] = 1
		out["serial_no"] = "\n".join(serials) or None
		out["batch_no"] = batch

	# Stock coming in from outside carries a rate somebody decided on; stock
	# moving between our own shelves is valued from the shelf it leaves, as at
	# the new date — which is the point of moving the entry.
	if not row.s_warehouse and row.basic_rate:
		out["basic_rate"] = row.basic_rate
		out["set_basic_rate_manually"] = 1

	return out


def _serials(row) -> list[str]:
	if row.serial_no:
		return [s.strip() for s in row.serial_no.split("\n") if s.strip()]
	if row.serial_and_batch_bundle:
		return frappe.get_all("Serial and Batch Entry",
			filters={"parent": row.serial_and_batch_bundle, "serial_no": ("is", "set")},
			pluck="serial_no")
	return []


def _batch(row) -> str | None:
	if not row.serial_and_batch_bundle:
		return None
	return frappe.db.get_value("Serial and Batch Entry",
		{"parent": row.serial_and_batch_bundle, "batch_no": ("is", "set")}, "batch_no")
