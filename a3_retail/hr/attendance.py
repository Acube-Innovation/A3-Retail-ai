# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Attendance and the branch geofence (scope 10.1).

Staff punch in from a phone, so a check-in carries a location. We stamp the
branch and the measured distance on every check-in, and reject the ones taken
outside the branch's radius — unless the employee is geofence-exempt (delivery
riders, field service) or the branch has no coordinates recorded yet.
"""

from math import asin, cos, radians, sin, sqrt

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing

DEFAULT_RADIUS_METRES = 200


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
	"""Great-circle distance — precise enough for a shop-floor geofence."""
	earth_radius = 6371000.0
	d_lat = radians(lat2 - lat1)
	d_lon = radians(lon2 - lon1)
	a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
	return 2 * earth_radius * asin(sqrt(a))


def branch_geofence(branch: str) -> dict | None:
	if not branch:
		return None
	profile = frappe.db.get_value(
		"Branch Profile",
		{"branch": branch},
		["latitude", "longitude", "geofence_radius_metres"],
		as_dict=True,
	)
	if not profile or not flt(profile.latitude) or not flt(profile.longitude):
		return None
	profile.geofence_radius_metres = cint(profile.geofence_radius_metres) or DEFAULT_RADIUS_METRES
	return profile


def validate_checkin(doc, method=None):
	"""Stamp the branch and geofence verdict on an Employee Checkin."""
	employee = frappe.db.get_value(
		"Employee", doc.employee, ["branch", "a3_geofence_exempt"], as_dict=True
	)
	if not employee:
		return

	doc.a3_branch = employee.branch
	fence = branch_geofence(employee.branch)

	if not doc.get("latitude") or not doc.get("longitude") or not fence:
		doc.a3_geofence_status = "Not Checked"
		doc.a3_distance_metres = 0
		return

	distance = haversine_metres(
		flt(doc.latitude), flt(doc.longitude), flt(fence.latitude), flt(fence.longitude)
	)
	doc.a3_distance_metres = int(distance)
	inside = distance <= fence.geofence_radius_metres
	doc.a3_geofence_status = "Inside" if inside else "Outside"

	if inside or employee.a3_geofence_exempt:
		return

	if not frappe.db.get_single_value("A3 Retail Settings", "enforce_checkin_geofence"):
		# Recorded as Outside for the report, but not blocked.
		return

	frappe.throw(
		_("Check-in is {0} m from {1}; the allowed radius is {2} m.").format(
			int(distance), employee.branch, fence.geofence_radius_metres
		),
		title=_("Outside Branch Geofence"),
	)


def stamp_attendance_branch(doc, method=None):
	"""Attendance is reported branch-wise, so carry the branch on the row."""
	if not doc.get("a3_branch"):
		doc.a3_branch = frappe.db.get_value("Employee", doc.employee, "branch")


def mark_absent_for_yesterday(posting_date: str | None = None) -> int:
	"""Daily — an active employee with neither attendance nor leave is Absent.

	HRMS only auto-marks attendance from shift check-ins. Branches that still run
	a register need yesterday closed off so the incentive attendance gate has a
	denominator it can trust.
	"""
	date = getdate(posting_date or add_days(nowdate(), -1))
	if not frappe.db.get_single_value("A3 Retail Settings", "auto_mark_absent"):
		return 0

	holiday = frappe.db.sql(
		"""select h.name from `tabHoliday` h where h.holiday_date = %s limit 1""", date
	)
	if holiday:
		return 0

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "date_of_joining": ["<=", date], "branch": ["is", "set"]},
		fields=["name", "company", "branch", "department"],
	)

	created = 0
	for employee in employees:
		if frappe.db.exists(
			"Attendance",
			{"employee": employee.name, "attendance_date": date, "docstatus": ["!=", 2]},
		):
			continue
		if _on_leave(employee.name, date):
			continue

		attendance = frappe.new_doc("Attendance")
		attendance.employee = employee.name
		attendance.attendance_date = date
		attendance.company = employee.company
		attendance.department = employee.department
		attendance.a3_branch = employee.branch
		attendance.status = "Absent"
		attendance.flags.ignore_permissions = True
		try:
			attendance.insert(ignore_permissions=True)
			attendance.submit()
			created += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: auto-absent {employee.name}")

	commit_if_not_testing()
	return created


def _on_leave(employee: str, date) -> bool:
	return bool(
		frappe.db.exists(
			"Leave Application",
			{
				"employee": employee,
				"docstatus": 1,
				"status": "Approved",
				"from_date": ["<=", date],
				"to_date": [">=", date],
			},
		)
	)


@frappe.whitelist()
def branch_attendance_summary(branch: str, from_date: str, to_date: str) -> dict:
	"""Feeds the branch attendance card on the control tower."""
	from a3_retail.api import require_branch_access, require_permission

	require_permission("Attendance", "read")
	require_branch_access(branch)

	rows = frappe.db.sql(
		"""
		select status, count(*) as count from `tabAttendance`
		where docstatus = 1 and a3_branch = %(branch)s
		  and attendance_date between %(from_date)s and %(to_date)s
		group by status
		""",
		{"branch": branch, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	by_status = {row.status: row.count for row in rows}
	total = sum(by_status.values())
	present = by_status.get("Present", 0) + by_status.get("Work From Home", 0)

	return {
		"branch": branch,
		"total": total,
		"present": present,
		"absent": by_status.get("Absent", 0),
		"on_leave": by_status.get("On Leave", 0),
		"half_day": by_status.get("Half Day", 0),
		"attendance_percent": round(present / total * 100, 2) if total else 0.0,
	}
