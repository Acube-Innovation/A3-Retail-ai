# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Give every branch real opening hours.

Each of the seven Branch Profiles was imported with `working_hours_from` and
`working_hours_to` both set to the instant of the import — a window sixty
microseconds wide, e.g. `17:27:01.118401` to `17:27:01.118461`. The SLA clock
walks the branch calendar in open hours, so a window that narrow meant no day
ever contributed any time: every repair's `sla_due_on` landed 400 days out, and
every promised-by date and TAT report with it.

`tat.py` now refuses to believe a window under an hour, so nothing can land a
year out again. This is the data half: the shop's hours, so the clock counts the
days the shop is actually open, and then the SLA clock on every card that was
stamped with the bad calendar, recomputed from the day the device came in.

The hours written are the app's own defaults, 09:30 to 20:00. Only profiles
whose window is unusably narrow are touched; a branch whose hours someone has
set deliberately is left exactly as it is.
"""

import frappe
from frappe.utils import get_time

FROM, TO = "09:30:00", "20:00:00"
# Under an hour is not a shop's opening hours, it is the import's timestamp.
MIN_WINDOW = 3600


def execute():
	rows = frappe.get_all(
		"Branch Profile", fields=["name", "branch", "working_hours_from", "working_hours_to"])

	for row in rows:
		if not _is_junk(row.working_hours_from, row.working_hours_to):
			continue
		# `db_set` rather than a save: the only thing wrong with these profiles
		# is two columns, and a save would re-run branch validation and the
		# cost-centre wiring on records nobody asked us to touch.
		frappe.db.set_value("Branch Profile", row.name,
			{"working_hours_from": FROM, "working_hours_to": TO}, update_modified=False)
		print(f"  {row.branch}: working hours set to {FROM}–{TO}")

	_restamp_cards()


def _restamp_cards():
	"""Recompute `sla_due_on` on cards stamped against the broken calendar.

	Only the SLA clock, which is the system's own arithmetic. A promised-by date
	is something a counter told a customer, so one that was typed is left alone;
	one that was only ever a copy of this arithmetic is corrected with it.
	"""
	from a3_retail.a3_retail_service import tat

	cards = frappe.get_all(
		"Service Job Card",
		filters={"docstatus": ("<", 2), "received_on": ("is", "set")},
		fields=["name", "branch", "received_on", "repair_category", "priority",
		        "warranty_type", "paused_hours", "sla_due_on", "estimated_delivery_date"])

	fixed = 0
	for card in cards:
		policy = tat.resolve_policy(card.repair_category, card.priority or "Normal",
			card.branch, card.warranty_type)
		if policy:
			hours, working_only = policy.tat_hours, bool(policy.exclude_non_working_hours)
		else:
			hours = tat.get_tat_hours(card.repair_category, card.priority or "Normal",
				card.branch)
			working_only = True

		due = tat.compute_sla_due(card.received_on, hours + float(card.paused_hours or 0),
			card.branch, working_only)
		if card.sla_due_on and abs((due - card.sla_due_on).total_seconds()) < 60:
			continue

		values = {"sla_due_on": due}
		# The promise and the SLA agreeing to the second is the signature of
		# `apply_policy` having filled a blank promise from its own sum. That
		# copy moves with it; a date a counter chose does not.
		if card.estimated_delivery_date and card.sla_due_on \
				and card.estimated_delivery_date == card.sla_due_on:
			values["estimated_delivery_date"] = due

		frappe.db.set_value("Service Job Card", card.name, values, update_modified=False)
		fixed += 1

	print(f"  {fixed} of {len(cards)} job cards re-stamped with a believable SLA date")


def _is_junk(start, end) -> bool:
	if not start or not end:
		return True
	try:
		start, end = get_time(start), get_time(end)
	except Exception:
		return True
	seconds = (end.hour - start.hour) * 3600 + (end.minute - start.minute) * 60 \
		+ (end.second - start.second)
	return seconds < MIN_WINDOW
