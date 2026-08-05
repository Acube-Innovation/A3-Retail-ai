# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""TAT resolution and SLA due-date arithmetic (scope 3.7).

`resolve_policy` picks the most specific Service TAT Policy for a job, and
`compute_sla_due` walks the branch calendar forward, skipping closed hours, the
weekly off and Holiday List dates when the policy asks for it.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import get_datetime, get_time, getdate

from a3_retail.utils.branch import get_branch_profile

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def resolve_policy(repair_category: str, priority: str = "Normal", branch: str | None = None,
                   warranty_type: str | None = None):
	"""Return the best-matching active Service TAT Policy, or None.

	Specificity order: branch+warranty > branch > warranty > generic. Within the
	same specificity the shortest TAT wins, so an "Urgent (Same Day)" policy is
	never beaten by a laxer one.
	"""
	candidates = frappe.get_all(
		"Service TAT Policy",
		filters={"repair_category": repair_category, "priority": priority, "is_active": 1},
		fields=["name", "branch", "warranty_type", "tat_hours", "exclude_non_working_hours",
		        "warn_at_percent", "escalate_after_hours", "escalate_to_role", "notify_customer_on_delay"],
	)
	if not candidates:
		return None

	def score(policy):
		matches_branch = policy.branch == branch
		matches_warranty = policy.warranty_type == warranty_type
		# Policies scoped to another branch/warranty type do not apply at all.
		if policy.branch and not matches_branch:
			return None
		if policy.warranty_type and not matches_warranty:
			return None
		return (bool(policy.branch) + bool(policy.warranty_type), -policy.tat_hours)

	scored = [(score(p), p) for p in candidates]
	scored = [(s, p) for s, p in scored if s is not None]
	if not scored:
		return None

	scored.sort(key=lambda row: row[0], reverse=True)
	return frappe.get_cached_doc("Service TAT Policy", scored[0][1].name)


def get_tat_hours(repair_category: str, priority: str = "Normal", branch: str | None = None,
                  warranty_type: str | None = None) -> int:
	"""TAT hours for a job, falling back to the branch/global default."""
	policy = resolve_policy(repair_category, priority, branch, warranty_type)
	if policy:
		return policy.tat_hours

	profile = get_branch_profile(branch)
	if profile and profile.default_tat_hours:
		return profile.default_tat_hours

	return int(frappe.db.get_single_value("A3 Retail Settings", "default_tat_hours") or 48)


def _branch_calendar(branch: str | None) -> dict:
	"""Working hours, weekly off and holidays for a branch."""
	profile = get_branch_profile(branch)
	if not profile:
		return {"start": get_time("09:30:00"), "end": get_time("20:00:00"),
		        "weekly_off": "Sunday", "holidays": set()}

	holidays = set()
	if profile.holiday_list:
		holidays = {
			str(getdate(d))
			for d in frappe.get_all(
				"Holiday", filters={"parent": profile.holiday_list}, pluck="holiday_date"
			)
		}

	return {
		"start": get_time(profile.working_hours_from or "09:30:00"),
		"end": get_time(profile.working_hours_to or "20:00:00"),
		"weekly_off": profile.weekly_off or "Sunday",
		"holidays": holidays,
	}


def is_working_day(day, calendar: dict) -> bool:
	day = getdate(day)
	if str(day) in calendar["holidays"]:
		return False
	return WEEKDAY_NAMES[day.weekday()] != calendar["weekly_off"]


def compute_sla_due(start: datetime | str, tat_hours: float, branch: str | None = None,
                    working_hours_only: bool = True) -> datetime:
	"""Add `tat_hours` to `start`, optionally counting only open hours.

	A Saturday 18:00 intake with a 48-hour policy and Sunday closed lands on the
	following Tuesday, because Sunday contributes no hours at all.
	"""
	start = get_datetime(start)
	if not tat_hours:
		return start

	if not working_hours_only:
		return start + timedelta(hours=float(tat_hours))

	calendar = _branch_calendar(branch)
	day_start, day_end = calendar["start"], calendar["end"]

	# Guard against a misconfigured branch (would loop forever otherwise).
	open_seconds = (
		datetime.combine(start.date(), day_end) - datetime.combine(start.date(), day_start)
	).total_seconds()
	if open_seconds <= 0:
		return start + timedelta(hours=float(tat_hours))

	remaining = timedelta(hours=float(tat_hours))
	cursor = start
	# 400 iterations covers a year of closed days — far beyond any real TAT.
	for _ in range(400):
		if not is_working_day(cursor, calendar):
			cursor = datetime.combine(cursor.date() + timedelta(days=1), day_start)
			continue

		window_start = datetime.combine(cursor.date(), day_start)
		window_end = datetime.combine(cursor.date(), day_end)

		if cursor < window_start:
			cursor = window_start
		if cursor >= window_end:
			cursor = datetime.combine(cursor.date() + timedelta(days=1), day_start)
			continue

		available = window_end - cursor
		if remaining <= available:
			return cursor + remaining

		remaining -= available
		cursor = datetime.combine(cursor.date() + timedelta(days=1), day_start)

	return cursor


def working_hours_between(start: datetime | str, end: datetime | str, branch: str | None = None) -> float:
	"""Open hours between two datetimes — used for delay and TAT reporting."""
	start, end = get_datetime(start), get_datetime(end)
	if end <= start:
		return 0.0

	calendar = _branch_calendar(branch)
	day_start, day_end = calendar["start"], calendar["end"]

	total = timedelta()
	cursor = start
	for _ in range(400):
		if cursor >= end:
			break
		if not is_working_day(cursor, calendar):
			cursor = datetime.combine(cursor.date() + timedelta(days=1), day_start)
			continue

		window_start = datetime.combine(cursor.date(), day_start)
		window_end = datetime.combine(cursor.date(), day_end)
		segment_start = max(cursor, window_start)
		segment_end = min(end, window_end)

		if segment_end > segment_start:
			total += segment_end - segment_start

		cursor = datetime.combine(cursor.date() + timedelta(days=1), day_start)

	return round(total.total_seconds() / 3600.0, 2)


def apply_policy(doc):
	"""Set `tat_policy` and `sla_due_on` on a Service Job Card."""
	if not doc.get("received_on"):
		return

	policy = resolve_policy(
		doc.get("repair_category"),
		doc.get("priority") or "Normal",
		doc.get("branch"),
		doc.get("warranty_type"),
	)

	if policy:
		doc.tat_policy = policy.name
		tat_hours = policy.tat_hours
		working_only = bool(policy.exclude_non_working_hours)
	else:
		doc.tat_policy = None
		tat_hours = get_tat_hours(doc.get("repair_category"), doc.get("priority") or "Normal", doc.get("branch"))
		working_only = True

	# Time spent waiting for parts or the customer does not count against us.
	paused = float(doc.get("paused_hours") or 0)
	doc.sla_due_on = compute_sla_due(doc.received_on, tat_hours + paused, doc.get("branch"), working_only)

	if not doc.get("estimated_delivery_date"):
		doc.estimated_delivery_date = doc.sla_due_on
