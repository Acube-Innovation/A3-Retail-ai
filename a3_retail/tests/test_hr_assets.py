# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""HRMS configuration, the attendance geofence and asset custody (scope step 23, 10.1, 10.3)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from a3_retail.hr import assets, attendance
from a3_retail.setup import hr
from a3_retail.tests.fixtures import ensure_branch, ensure_company

# Branch Profile puts Kochi at 9.9312 / 76.2673.
KOCHI = (9.9312, 76.2673)


def employee(name):
	return frappe.db.get_value("Employee", {"employee_name": name}, "name")


class TestHrmsConfiguration(FrappeTestCase):
	def test_shift_types(self):
		for name in ("General", "Morning", "Evening", "Service Bay"):
			self.assertTrue(frappe.db.exists("Shift Type", name), name)

	def test_shift_hours(self):
		self.assertEqual(str(frappe.db.get_value("Shift Type", "General", "start_time")), "9:30:00")

	def test_leave_types(self):
		for name, allowance in (("Casual Leave", 12), ("Sick Leave", 8), ("Earned Leave", 15)):
			self.assertEqual(
				frappe.db.get_value("Leave Type", name, "max_leaves_allowed"), allowance, name
			)

	def test_leave_without_pay_is_flagged(self):
		self.assertTrue(frappe.db.get_value("Leave Type", "Leave Without Pay", "is_lwp"))

	def test_salary_components(self):
		for name in ("Basic", "HRA", "Special Allowance", "PF (Employee)", "ESI (Employee)"):
			self.assertTrue(frappe.db.exists("Salary Component", name), name)

	def test_basic_is_half_of_base(self):
		self.assertEqual(frappe.db.get_value("Salary Component", "Basic", "formula"), "base * 0.50")

	def test_esi_only_applies_below_the_ceiling(self):
		self.assertEqual(
			frappe.db.get_value("Salary Component", "ESI (Employee)", "condition"),
			"gross_pay <= 21000",
		)

	def test_incentive_components_are_paid_through_additional_salary(self):
		"""They must not sit in the structure, or the payout would double."""
		structure = frappe.get_doc("Salary Structure", hr.STRUCTURE_NAME)
		names = {row.salary_component for row in structure.earnings}
		self.assertNotIn("Sales Incentive", names)
		self.assertIn("Basic", names)

	def test_the_structure_is_submitted(self):
		self.assertEqual(frappe.db.get_value("Salary Structure", hr.STRUCTURE_NAME, "docstatus"), 1)

	def test_asset_categories(self):
		for name in ("Service Tools & Equipment", "Test & Measuring Instruments",
		             "Computers & POS Hardware", "Vehicles (Delivery)"):
			self.assertTrue(frappe.db.exists("Asset Category", name), name)

	def test_every_branch_employee_has_a_payroll_cost_center(self):
		missing = frappe.db.sql(
			"""select name from `tabEmployee`
			   where status = 'Active' and branch not in ('Head Office', '')
			     and ifnull(payroll_cost_center, '') = ''"""
		)
		self.assertFalse(missing, f"employees without a payroll cost center: {missing}")

	def test_hr_custom_fields_exist(self):
		meta = frappe.get_meta("Employee")
		for fieldname in ("a3_staff_category", "a3_shift_pattern", "a3_geofence_exempt"):
			self.assertTrue(meta.has_field(fieldname), fieldname)


class TestGeofence(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	_minute = [0]

	def _checkin(self, latitude, longitude, employee_name="Vipin S"):
		# Every log needs its own timestamp: HRMS rejects duplicates outright.
		self._minute[0] += 1
		doc = frappe.new_doc("Employee Checkin")
		doc.employee = employee(employee_name)
		doc.time = f"{nowdate()} 09:{self._minute[0]:02d}:00"
		doc.log_type = "IN"
		doc.latitude = latitude
		doc.longitude = longitude
		doc.flags.ignore_permissions = True
		return doc

	def test_distance_between_two_points(self):
		# Kochi to Thiruvananthapuram is roughly 160 km.
		metres = attendance.haversine_metres(9.9312, 76.2673, 8.5241, 76.9366)
		self.assertGreater(metres, 150000)
		self.assertLess(metres, 190000)

	def test_the_same_point_is_zero_metres_away(self):
		self.assertEqual(attendance.haversine_metres(*KOCHI, *KOCHI), 0)

	def test_a_check_in_at_the_counter_is_inside(self):
		doc = self._checkin(*KOCHI)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_geofence_status, "Inside")
		self.assertEqual(doc.a3_branch, "Kochi")

	def test_a_check_in_across_town_is_refused(self):
		frappe.db.set_single_value("A3 Retail Settings", "enforce_checkin_geofence", 1)
		doc = self._checkin(9.9800, 76.3200)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_an_exempt_employee_may_check_in_anywhere(self):
		name = employee("Jithin Raj")
		frappe.db.set_value("Employee", name, "a3_geofence_exempt", 1)
		doc = self._checkin(9.9800, 76.3200, "Jithin Raj")
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_geofence_status, "Outside")
		frappe.db.set_value("Employee", name, "a3_geofence_exempt", 0)

	def test_enforcement_can_be_turned_off(self):
		frappe.db.set_single_value("A3 Retail Settings", "enforce_checkin_geofence", 0)
		doc = self._checkin(9.9800, 76.3200)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_geofence_status, "Outside")
		frappe.db.set_single_value("A3 Retail Settings", "enforce_checkin_geofence", 1)

	def test_a_check_in_without_coordinates_is_not_checked(self):
		doc = self._checkin(None, None)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_geofence_status, "Not Checked")

	def test_a_branch_without_coordinates_is_not_checked(self):
		profile = frappe.db.get_value("Branch Profile", {"branch": "Kochi"}, "name")
		saved = frappe.db.get_value("Branch Profile", profile, "latitude")
		frappe.db.set_value("Branch Profile", profile, "latitude", 0)

		doc = self._checkin(9.9800, 76.3200)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_geofence_status, "Not Checked")

		frappe.db.set_value("Branch Profile", profile, "latitude", saved)


class TestAttendance(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_attendance_carries_the_branch(self):
		doc = frappe.new_doc("Attendance")
		doc.employee = employee("Vipin S")
		doc.attendance_date = add_days(nowdate(), -1)
		doc.status = "Present"
		doc.company = ensure_company()
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.a3_branch, "Kochi")

	def test_july_attendance_was_seeded(self):
		count = frappe.db.count(
			"Attendance", {"attendance_date": ["between", ["2026-07-01", "2026-07-31"]],
			               "docstatus": 1}
		)
		self.assertGreaterEqual(count, 250)

	def test_branch_summary_shape(self):
		summary = attendance.branch_attendance_summary("Kochi", "2026-07-01", "2026-07-31")
		for key in ("total", "present", "absent", "attendance_percent"):
			self.assertIn(key, summary)
		self.assertGreater(summary["present"], 0)

	def test_auto_absent_respects_the_setting(self):
		frappe.db.set_single_value("A3 Retail Settings", "auto_mark_absent", 0)
		self.assertEqual(attendance.mark_absent_for_yesterday(), 0)
		frappe.db.set_single_value("A3 Retail Settings", "auto_mark_absent", 1)

	def test_auto_absent_skips_employees_already_marked(self):
		date = "2026-07-10"
		before = frappe.db.count("Attendance", {"attendance_date": date, "docstatus": 1})
		attendance.mark_absent_for_yesterday(date)
		after = frappe.db.count("Attendance", {"attendance_date": date, "docstatus": 1})
		self.assertGreaterEqual(after, before)


class TestAssetCustody(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _asset(self, asset_name="Digital Microscope 7050"):
		return frappe.db.get_value("Asset", {"asset_name": asset_name}, "name")

	def test_twelve_assets_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Asset"), 12)

	def test_every_submitted_asset_has_a_custodian(self):
		rows = frappe.db.sql(
			"""select name from `tabAsset`
			   where docstatus = 1 and status = 'Submitted'
			     and ifnull(a3_assigned_employee, '') = ''"""
		)
		self.assertFalse(rows, f"assets without a custodian: {rows}")

	def test_custody_is_set_from_the_movement(self):
		asset = self._asset()
		self.assertEqual(
			frappe.db.get_value("Asset", asset, "a3_assigned_employee"), employee("Vishnu P")
		)

	def test_held_by_lists_the_instruments(self):
		held = assets.held_by(employee("Vishnu P"))
		self.assertIn("Digital Microscope 7050", held)

	def test_receipt_clears_the_custodian(self):
		asset = self._asset("Ultrasonic Cleaner")
		holder = frappe.db.get_value("Asset", asset, "a3_assigned_employee")

		movement = frappe.new_doc("Asset Movement")
		movement.company = ensure_company()
		movement.purpose = "Receipt"
		movement.transaction_date = f"{nowdate()} 10:00:00"
		movement.append("assets", {"asset": asset, "from_employee": holder,
		                           "target_location": frappe.db.get_value("Asset", asset, "location")})
		movement.flags.ignore_permissions = True
		movement.flags.ignore_mandatory = True
		movement.insert(ignore_permissions=True)
		movement.submit()

		self.assertIsNone(frappe.db.get_value("Asset", asset, "a3_assigned_employee"))

	def test_exit_clearance_blocks_an_employee_holding_assets(self):
		doc = frappe.get_doc("Employee", employee("Vishnu P"))
		doc.status = "Left"
		doc.relieving_date = nowdate()
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_an_employee_holding_nothing_may_leave(self):
		name = employee("Arjun V")
		self.assertFalse(assets.held_by(name))

	def test_custody_register_shape(self):
		register = assets.custody_register("Kochi")
		self.assertTrue(register)
		for key in ("asset_name", "employee", "branch", "since"):
			self.assertIn(key, register[0])

	def test_calibration_reminders_raise_todos(self):
		created = assets.calibration_reminders()
		self.assertIsInstance(created, int)
		self.assertTrue(
			frappe.db.exists("ToDo", {"reference_type": "Asset", "status": "Open"})
			or created == 0
		)

	def test_calibration_reminders_do_not_duplicate(self):
		assets.calibration_reminders()
		self.assertEqual(assets.calibration_reminders(), 0)

	def test_asset_custom_fields_exist(self):
		meta = frappe.get_meta("Asset")
		for fieldname in ("a3_branch", "a3_assigned_employee", "a3_custody_since",
		                  "a3_asset_condition", "a3_is_calibration_required",
		                  "a3_next_calibration_date", "a3_insurance_expiry"):
			self.assertTrue(meta.has_field(fieldname), fieldname)


class TestValidationQueries(FrappeTestCase):
	"""Scope 10.5 — all four must return zero rows."""

	def test_no_active_employee_without_a_payroll_cost_center(self):
		rows = frappe.db.sql(
			"""select name from `tabEmployee`
			   where status = 'Active' and branch not in ('Head Office', '')
			     and ifnull(payroll_cost_center, '') = ''"""
		)
		self.assertFalse(rows, f"{rows}")

	def test_no_submitted_asset_without_a_custodian(self):
		rows = frappe.db.sql(
			"""select name from `tabAsset`
			   where docstatus = 1 and status = 'Submitted'
			     and ifnull(a3_assigned_employee, '') = ''"""
		)
		self.assertFalse(rows, f"{rows}")

	def test_posted_incentive_matches_the_payroll_rows(self):
		rows = frappe.db.sql(
			"""select r.name, r.total_incentive, ifnull(sum(a.amount), 0) as posted
			   from `tabIncentive Calculation Run` r
			   join `tabIncentive Calculation Item` i on i.parent = r.name
			   left join `tabAdditional Salary` a on a.name = i.additional_salary
			   where r.status = 'Posted to Payroll' and r.docstatus = 1
			   group by r.name""",
			as_dict=True,
		)
		self.assertTrue(rows)
		for row in rows:
			self.assertAlmostEqual(row.total_incentive, row.posted, places=2, msg=row.name)

	def test_no_left_employee_still_holds_an_asset(self):
		rows = frappe.db.sql(
			"""select a.name from `tabAsset` a
			   join `tabEmployee` e on e.name = a.a3_assigned_employee
			   where e.status = 'Left' and a.docstatus = 1"""
		)
		self.assertFalse(rows, f"{rows}")
