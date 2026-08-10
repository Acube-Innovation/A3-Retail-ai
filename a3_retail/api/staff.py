# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch staff portal API (`/retail`).

Everything here answers for exactly one person: the employee behind the logged-in
Website User, and only for their own branch. `_me()` is the gate — it refuses a
guest, refuses a user with no Employee record, and returns the branch every query
below is then scoped to. Nothing accepts a branch from the caller.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from a3_retail.setup.staff_portal import PORTAL_ROLE, current_employee


def _me() -> dict:
	"""The employee making the request. Throws unless they are portal staff."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)

	employee = current_employee()
	if not employee:
		frappe.throw(
			_("This account is not linked to an employee record."), frappe.PermissionError
		)
	if not employee.branch:
		frappe.throw(_("Your employee record has no branch."), frappe.PermissionError)

	return employee


@frappe.whitelist()
def session_context() -> dict:
	"""Who is signed in, and what the portal should show them."""
	employee = _me()
	roles = [role for role in frappe.get_roles() if role not in ("All", "Guest", PORTAL_ROLE)]

	return {
		"user": frappe.session.user,
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"designation": employee.designation,
		"department": employee.department,
		"branch": employee.branch,
		"roles": roles,
		"is_manager": bool({"Branch Manager", "Service Manager"} & set(roles)),
	}


@frappe.whitelist()
def dashboard() -> dict:
	"""The welcome screen: tiles, my work, and what is waiting on this branch."""
	employee = _me()
	branch = employee.branch
	roles = set(frappe.get_roles())

	return {
		"context": session_context(),
		"as_of": str(now_datetime()),
		"tiles": _tiles(branch, employee, roles),
		"my_work": _my_work(employee, roles),
		"branch_activity": _branch_activity(branch),
		"notices": _notices(branch, employee, roles),
	}


# ------------------------------------------------------------------- tiles
def _tiles(branch: str, employee: dict, roles: set) -> list[dict]:
	"""Role-aware counters. A tile only appears if the user may read its source."""
	tiles = []
	today = nowdate()

	if frappe.has_permission("Service Job Card", "read"):
		tiles += [
			{"label": _("Received today"), "value": _job_count(branch, received_on=today),
			 "tone": "neutral"},
			{"label": _("In progress"), "value": _job_count(
				branch, status=["Under Diagnosis", "In Progress", "Awaiting Parts"]), "tone": "neutral"},
			{"label": _("Ready for delivery"), "value": _job_count(
				branch, status=["Ready for Delivery"]), "tone": "good"},
			{"label": _("Delayed"), "value": _job_count(branch, delayed=True), "tone": "bad"},
		]

	if "Technician" in roles:
		tiles.append(
			{"label": _("My open jobs"), "value": frappe.db.count(
				"Service Job Card",
				{"assigned_technician": employee.name, "docstatus": 1,
				 "status": ["not in", ["Delivered", "Closed", "Cancelled"]]}),
			 "tone": "neutral"}
		)

	if frappe.has_permission("Sales Invoice", "read") and {"Sales Executive", "Branch Manager"} & roles:
		tiles.append(
			{"label": _("Sales today"), "value": _money(_sales_today(branch, today)),
			 "tone": "neutral"}
		)

	if frappe.has_permission("Branch Visit Log", "read"):
		tiles.append(
			{"label": _("Footfall today"), "value": frappe.db.count(
				"Branch Visit Log",
				{"branch": branch, "visit_datetime": ["between", [today, f"{today} 23:59:59"]]}),
			 "tone": "neutral"}
		)

	if "Telecaller" in roles and frappe.db.exists("DocType", "Call Task"):
		tiles.append(
			{"label": _("Calls in my queue"), "value": frappe.db.count(
				"Call Task", {"assigned_to": employee.name, "call_status": "Not Called"}),
			 "tone": "neutral"}
		)

	return tiles


def _job_count(branch: str, status: list[str] | None = None, received_on: str | None = None,
               delayed: bool = False) -> int:
	filters = {"branch": branch, "docstatus": 1}
	if status:
		filters["status"] = ["in", status]
	if received_on:
		filters["received_on"] = ["between", [received_on, f"{received_on} 23:59:59"]]
	if delayed:
		filters["is_delayed"] = 1
		filters["status"] = ["not in", ["Delivered", "Closed", "Cancelled"]]
	return frappe.db.count("Service Job Card", filters)


def _sales_today(branch: str, today: str) -> float:
	return flt(
		frappe.db.sql(
			"""select sum(base_grand_total) from `tabSales Invoice`
			   where docstatus = 1 and is_return = 0 and branch = %(branch)s
			     and posting_date = %(today)s""",
			{"branch": branch, "today": today},
		)[0][0]
	)


def _money(value) -> str:
	"""Whole rupees. A day's takings on a tile does not need the paise, and the
	two extra characters push the number off the edge of the tile."""
	from frappe.utils import fmt_money

	return fmt_money(flt(value), precision=0, currency="INR")


# ----------------------------------------------------------------- my work
def _my_work(employee: dict, roles: set) -> list[dict]:
	"""The rows this person is expected to act on today."""
	work = []

	if "Technician" in roles and frappe.has_permission("Service Job Card", "read"):
		for row in frappe.get_all(
			"Service Job Card",
			filters={"assigned_technician": employee.name, "docstatus": 1,
			         "status": ["not in", ["Delivered", "Closed", "Cancelled"]]},
			fields=["name", "customer_name", "device_model", "status", "sla_due_on", "is_delayed"],
			order_by="is_delayed desc, sla_due_on asc", limit=10,
		):
			work.append(
				{
					"kind": _("Repair"),
					"reference": row.name,
					"title": f"{row.device_model or ''} — {row.customer_name or ''}".strip(" —"),
					"status": row.status,
					"due": str(row.sla_due_on or ""),
					"urgent": bool(row.is_delayed),
				}
			)

	if {"Reception Executive", "Branch Manager", "Service Manager"} & roles:
		for row in frappe.get_all(
			"Service Job Card",
			filters={"branch": employee.branch, "docstatus": 1, "status": "Ready for Delivery"},
			fields=["name", "customer_name", "device_model", "ready_on", "outstanding_amount"],
			order_by="ready_on asc", limit=10,
		):
			work.append(
				{
					"kind": _("Hand over"),
					"reference": row.name,
					"title": f"{row.device_model or ''} — {row.customer_name or ''}".strip(" —"),
					"status": _("Ready since {0}").format(str(row.ready_on or "")[:10]),
					"due": "",
					"urgent": flt(row.outstanding_amount) > 0,
				}
			)

	if "Telecaller" in roles and frappe.db.exists("DocType", "Call Task"):
		for row in frappe.get_all(
			"Call Task",
			filters={"assigned_to": employee.name, "call_status": "Not Called"},
			fields=["name", "contact_name", "mobile_no", "scheduled_date"],
			order_by="scheduled_date asc", limit=10,
		):
			work.append(
				{
					"kind": _("Call"),
					"reference": row.name,
					"title": f"{row.contact_name or ''} · {row.mobile_no or ''}".strip(" ·"),
					"status": _("Scheduled {0}").format(str(row.scheduled_date or "")[:10]),
					"due": "",
					"urgent": False,
				}
			)

	if "Store Keeper" in roles and frappe.has_permission("Stock Request", "read"):
		for row in frappe.get_all(
			"Stock Request",
			filters={"source_branch": employee.branch, "docstatus": 1,
			         "status": ["in", ["Pending Approval", "Approved"]]},
			fields=["name", "requesting_branch", "status", "required_by"],
			order_by="required_by asc", limit=10,
		):
			work.append(
				{
					"kind": _("Transfer"),
					"reference": row.name,
					"title": _("Requested by {0}").format(row.requesting_branch),
					"status": row.status,
					"due": str(row.required_by or ""),
					"urgent": row.status == "Pending Approval",
				}
			)

	return work[:20]


def _branch_activity(branch: str) -> list[dict]:
	"""The last few things that happened here, so the screen feels alive."""
	if not frappe.has_permission("Service Job Card", "read"):
		return []

	return [
		{
			"reference": row.name,
			"title": f"{row.customer_name or ''} · {row.device_model or ''}".strip(" ·"),
			"status": row.status,
			"when": str(row.modified),
		}
		for row in frappe.get_all(
			"Service Job Card",
			filters={"branch": branch, "docstatus": 1},
			fields=["name", "customer_name", "device_model", "status", "modified"],
			order_by="modified desc", limit=8,
		)
	]


def _notices(branch: str, employee: dict, roles: set) -> list[dict]:
	"""Things worth saying out loud on the welcome screen."""
	notices = []

	delayed = _job_count(branch, delayed=True)
	if delayed:
		notices.append(
			{"tone": "bad", "text": _("{0} repairs at this branch are past their promised time.")
				.format(delayed)}
		)

	if frappe.has_permission("Stock Request", "read") and {"Branch Manager", "Store Keeper"} & roles:
		pending = frappe.db.count(
			"Stock Request", {"source_branch": branch, "status": "Pending Approval", "docstatus": 1}
		)
		if pending:
			notices.append(
				{"tone": "warn", "text": _("{0} stock requests are waiting for your approval.")
					.format(pending)}
			)

	if frappe.db.exists("DocType", "Portal OTP") and "Reception Executive" in roles:
		waiting = _job_count(branch, status=["Ready for Delivery"])
		if waiting:
			notices.append(
				{"tone": "good", "text": _("{0} devices are ready and waiting for collection.")
					.format(waiting)}
			)

	if not notices:
		notices.append({"tone": "good", "text": _("Nothing needs chasing right now.")})

	return notices


@frappe.whitelist()
def my_attendance_summary() -> dict:
	"""This month's attendance for the signed-in employee."""
	employee = _me()
	from frappe.utils import get_first_day, get_last_day

	rows = frappe.db.sql(
		"""select status, count(*) as days from `tabAttendance`
		   where employee = %(employee)s and docstatus = 1
		     and attendance_date between %(start)s and %(end)s
		   group by status""",
		{"employee": employee.name, "start": get_first_day(nowdate()),
		 "end": get_last_day(nowdate())},
		as_dict=True,
	)
	by_status = {row.status: cint(row.days) for row in rows}
	marked = sum(by_status.values())
	present = by_status.get("Present", 0) + by_status.get("Half Day", 0) * 0.5

	return {
		"marked": marked,
		"present": by_status.get("Present", 0),
		"absent": by_status.get("Absent", 0),
		"leave": by_status.get("On Leave", 0),
		"percent": round(present / marked * 100, 1) if marked else 0.0,
	}
