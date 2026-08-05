# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Job Card state machine (scope 3.3).

Implemented as a plain `status` Select with server-side transition validation
rather than a Frappe Workflow: a Workflow would block the granular role rules and
the custom pages (Reception Desk, Technician Workbench) that drive most status
changes. Only the estimate approval uses a Workflow.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

DRAFT = "Draft"
OPEN = "Open"
UNDER_DIAGNOSIS = "Under Diagnosis"
ESTIMATE_PENDING = "Estimate Pending"
ESTIMATE_SENT = "Estimate Sent"
ESTIMATE_APPROVED = "Estimate Approved"
ESTIMATE_REJECTED = "Estimate Rejected"
AWAITING_PARTS = "Awaiting Parts"
IN_PROGRESS = "In Progress"
ON_HOLD = "On Hold"
REPAIR_COMPLETED = "Repair Completed"
QC_FAILED = "QC Failed"
QC_PASSED = "QC Passed"
NOT_REPAIRABLE = "Not Repairable"
READY_FOR_DELIVERY = "Ready for Delivery"
DELIVERED = "Delivered"
CLOSED = "Closed"
CANCELLED = "Cancelled"

STATUSES = [
	DRAFT, OPEN, UNDER_DIAGNOSIS, ESTIMATE_PENDING, ESTIMATE_SENT, ESTIMATE_APPROVED,
	ESTIMATE_REJECTED, AWAITING_PARTS, IN_PROGRESS, ON_HOLD, REPAIR_COMPLETED, QC_FAILED,
	QC_PASSED, NOT_REPAIRABLE, READY_FOR_DELIVERY, DELIVERED, CLOSED, CANCELLED,
]

# from -> allowed next states
ALLOWED: dict[str, tuple[str, ...]] = {
	DRAFT: (OPEN, CANCELLED),
	OPEN: (UNDER_DIAGNOSIS, CANCELLED),
	UNDER_DIAGNOSIS: (ESTIMATE_PENDING, IN_PROGRESS, NOT_REPAIRABLE, ON_HOLD, CANCELLED),
	ESTIMATE_PENDING: (ESTIMATE_SENT, IN_PROGRESS, CANCELLED),
	ESTIMATE_SENT: (ESTIMATE_APPROVED, ESTIMATE_REJECTED, ESTIMATE_PENDING, CANCELLED),
	ESTIMATE_APPROVED: (AWAITING_PARTS, IN_PROGRESS),
	ESTIMATE_REJECTED: (READY_FOR_DELIVERY, CANCELLED),
	AWAITING_PARTS: (IN_PROGRESS, ON_HOLD, NOT_REPAIRABLE),
	IN_PROGRESS: (REPAIR_COMPLETED, ON_HOLD, AWAITING_PARTS, NOT_REPAIRABLE),
	ON_HOLD: (IN_PROGRESS, NOT_REPAIRABLE, CANCELLED),
	REPAIR_COMPLETED: (QC_PASSED, QC_FAILED),
	QC_FAILED: (IN_PROGRESS,),
	QC_PASSED: (READY_FOR_DELIVERY,),
	NOT_REPAIRABLE: (READY_FOR_DELIVERY,),
	READY_FOR_DELIVERY: (DELIVERED,),
	DELIVERED: (CLOSED,),
	CLOSED: (),
	CANCELLED: (),
}

# Statuses that count as live work — used for WIP and control-tower counters.
OPEN_STATUSES = (
	OPEN, UNDER_DIAGNOSIS, ESTIMATE_PENDING, ESTIMATE_SENT, ESTIMATE_APPROVED,
	AWAITING_PARTS, IN_PROGRESS, ON_HOLD, REPAIR_COMPLETED, QC_FAILED, QC_PASSED,
	READY_FOR_DELIVERY,
)

# Statuses where the TAT clock is paused (scope 3.11).
PAUSED_STATUSES = (AWAITING_PARTS, ON_HOLD, ESTIMATE_SENT, ESTIMATE_PENDING)

# Statuses that end the job — no delay flagging past these.
TERMINAL_STATUSES = (DELIVERED, CLOSED, CANCELLED)

# Indicator colours for the list view and the control tower.
STATUS_COLOURS = {
	DRAFT: "grey",
	OPEN: "orange",
	UNDER_DIAGNOSIS: "blue",
	ESTIMATE_PENDING: "yellow",
	ESTIMATE_SENT: "yellow",
	ESTIMATE_APPROVED: "blue",
	ESTIMATE_REJECTED: "red",
	AWAITING_PARTS: "orange",
	IN_PROGRESS: "blue",
	ON_HOLD: "grey",
	REPAIR_COMPLETED: "purple",
	QC_FAILED: "red",
	QC_PASSED: "green",
	NOT_REPAIRABLE: "red",
	READY_FOR_DELIVERY: "green",
	DELIVERED: "green",
	CLOSED: "grey",
	CANCELLED: "red",
}

# Roles allowed to move into a status. Empty means "anyone with write access".
TRANSITION_ROLES = {
	QC_PASSED: ("Service Manager", "Branch Manager", "A3 Retail Admin"),
	QC_FAILED: ("Service Manager", "Branch Manager", "A3 Retail Admin"),
	NOT_REPAIRABLE: ("Service Manager", "Branch Manager", "A3 Retail Admin"),
	CANCELLED: ("Service Manager", "Branch Manager", "A3 Retail Admin", "Reception Executive"),
}


def can_transition(from_status: str, to_status: str) -> bool:
	if from_status == to_status:
		return True
	return to_status in ALLOWED.get(from_status, ())


def validate_transition(from_status: str, to_status: str, user: str | None = None):
	"""Throw unless the transition is in the map and the user holds the role."""
	if from_status == to_status:
		return

	if frappe.flags.get("a3_import_history"):
		# Back-dated history (demo seeds, go-live imports) records the state the
		# job ended in; the shop floor already walked the real route months ago.
		return

	if not can_transition(from_status, to_status):
		allowed = ", ".join(ALLOWED.get(from_status, ())) or _("none")
		frappe.throw(
			_("Cannot move a job card from {0} to {1}. Allowed next states: {2}").format(
				_(from_status), _(to_status), allowed
			),
			title=_("Invalid Status Change"),
		)

	required = TRANSITION_ROLES.get(to_status)
	if required:
		user = user or frappe.session.user
		if user != "Administrator" and not (set(required) | {"System Manager"}) & set(frappe.get_roles(user)):
			frappe.throw(
				_("Only {0} can set the status to {1}.").format(", ".join(required), _(to_status)),
				frappe.PermissionError,
			)


def log_transition(doc, from_status: str, to_status: str, remarks: str | None = None):
	"""Append a Job Card Status Log row with the duration spent in `from_status`."""
	now = now_datetime()
	duration = 0.0

	previous = doc.get("status_log")
	if previous:
		last_changed = get_datetime(previous[-1].changed_on)
		duration = round((now - last_changed).total_seconds() / 3600.0, 2)
	elif doc.get("received_on"):
		duration = round((now - get_datetime(doc.received_on)).total_seconds() / 3600.0, 2)

	doc.append(
		"status_log",
		{
			"from_status": from_status,
			"to_status": to_status,
			"changed_by": frappe.session.user,
			"changed_on": now,
			"duration_hours": duration,
			"remarks": remarks,
		},
	)


def next_statuses(status: str) -> tuple[str, ...]:
	return ALLOWED.get(status, ())


def path_to(from_status: str, to_status: str) -> list[str]:
	"""Shortest legal route between two statuses, excluding the starting point.

	Callers that drive the job card indirectly (an approved estimate, a received
	transfer) know the destination but not the intermediate hops. Walking the
	real path keeps the status log honest instead of teleporting.
	Returns [] when no route exists.
	"""
	if from_status == to_status:
		return []

	queue: list[tuple[str, list[str]]] = [(from_status, [])]
	seen = {from_status}

	while queue:
		current, route = queue.pop(0)
		for nxt in ALLOWED.get(current, ()):
			if nxt in seen:
				continue
			path = [*route, nxt]
			if nxt == to_status:
				return path
			seen.add(nxt)
			queue.append((nxt, path))

	return []
