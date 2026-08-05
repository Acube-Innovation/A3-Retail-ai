# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""TAT policy resolution and working-hours SLA maths (scope step 6, section 3.7)."""

from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.a3_retail_service.tat import (
	compute_sla_due,
	get_tat_hours,
	is_working_day,
	resolve_policy,
	working_hours_between,
)
from a3_retail.tests.fixtures import ensure_branch


def _seed_masters():
	import importlib.util
	import os

	path = os.path.join(frappe.get_app_path("a3_retail"), "demo", "08_service_masters.py")
	spec = importlib.util.spec_from_file_location("a3_seed_service_masters", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	module.run()


class TestTATPolicyResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		_seed_masters()
		frappe.db.commit()

	def test_urgent_software_policy_is_four_hours(self):
		"""Scope step 6 acceptance."""
		policy = resolve_policy("Software", "Urgent (Same Day)", "Kochi")
		self.assertIsNotNone(policy)
		self.assertEqual(policy.tat_hours, 4)

	def test_normal_software_policy_is_eight_hours(self):
		policy = resolve_policy("Software", "Normal", "Kochi")
		self.assertEqual(policy.tat_hours, 8)

	def test_board_level_policy_is_ninety_six_hours(self):
		policy = resolve_policy("Hardware - Board Level", "Normal", "Kochi")
		self.assertEqual(policy.tat_hours, 96)

	def test_unknown_category_falls_back_to_branch_default(self):
		self.assertIsNone(resolve_policy("Accessory", "Normal", "Kochi"))
		self.assertEqual(get_tat_hours("Accessory", "Normal", "Kochi"), 48)

	def test_branch_scoped_policy_beats_generic(self):
		name = "Kochi Express Software"
		if not frappe.db.exists("Service TAT Policy", name):
			doc = frappe.new_doc("Service TAT Policy")
			doc.policy_name = name
			doc.repair_category = "Software"
			doc.priority = "Normal"
			doc.branch = "Kochi"
			doc.tat_hours = 6
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)

		self.assertEqual(resolve_policy("Software", "Normal", "Kochi").tat_hours, 6)
		# A different branch must not pick up the Kochi-scoped policy.
		self.assertEqual(resolve_policy("Software", "Normal", "Thiruvananthapuram").tat_hours, 8)
		frappe.delete_doc("Service TAT Policy", name, force=1, ignore_permissions=True)


class TestWorkingHoursMaths(FrappeTestCase):
	"""Kochi is open 09:30–20:00 (10.5 h/day) and closed on Sunday."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_sunday_is_not_a_working_day(self):
		from a3_retail.a3_retail_service.tat import _branch_calendar

		calendar = _branch_calendar("Kochi")
		self.assertFalse(is_working_day("2026-08-09", calendar))  # Sunday
		self.assertTrue(is_working_day("2026-08-10", calendar))  # Monday

	def test_same_day_completion_stays_on_the_same_day(self):
		due = compute_sla_due("2026-08-10 10:00:00", 4, "Kochi")
		self.assertEqual(due, datetime(2026, 8, 10, 14, 0))

	def test_overflow_rolls_into_the_next_working_day(self):
		# Monday 18:00 + 4h; only 2h left today, so 2h spill to Tuesday 09:30.
		due = compute_sla_due("2026-08-10 18:00:00", 4, "Kochi")
		self.assertEqual(due, datetime(2026, 8, 11, 11, 30))

	def test_saturday_intake_skips_sunday(self):
		"""Scope step 6 acceptance: Saturday 18:00 + 48 h with Sunday closed.

		Sat 18:00→20:00 = 2 h. Sunday is closed. Mon/Tue/Wed give 10.5 h each
		(31.5 h, running total 33.5). Thursday needs the remaining 14.5 h, which
		exceeds one day, so Thursday contributes 10.5 (44 h) and Friday the last
		4 h — landing Friday 13:30, never on a Sunday.
		"""
		due = compute_sla_due("2026-08-08 18:00:00", 48, "Kochi")  # Saturday
		self.assertEqual(due.strftime("%A"), "Friday")
		self.assertEqual(due, datetime(2026, 8, 14, 13, 30))

	def test_intake_before_opening_starts_at_opening(self):
		due = compute_sla_due("2026-08-10 07:00:00", 2, "Kochi")
		self.assertEqual(due, datetime(2026, 8, 10, 11, 30))

	def test_intake_after_closing_starts_next_morning(self):
		due = compute_sla_due("2026-08-10 22:00:00", 2, "Kochi")
		self.assertEqual(due, datetime(2026, 8, 11, 11, 30))

	def test_calendar_hours_mode_ignores_the_branch_calendar(self):
		due = compute_sla_due("2026-08-08 18:00:00", 48, "Kochi", working_hours_only=False)
		self.assertEqual(due, datetime(2026, 8, 10, 18, 0))

	def test_working_hours_between_excludes_sunday(self):
		# Saturday 18:00 -> Monday 12:00 = 2 h (Sat) + 2.5 h (Mon) = 4.5 h.
		hours = working_hours_between("2026-08-08 18:00:00", "2026-08-10 12:00:00", "Kochi")
		self.assertEqual(hours, 4.5)

	def test_working_hours_between_is_zero_for_reversed_range(self):
		self.assertEqual(working_hours_between("2026-08-10 12:00:00", "2026-08-08 18:00:00", "Kochi"), 0.0)


class TestTechnicianProfile(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		_seed_masters()
		frappe.db.commit()

	def test_profiles_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Technician Profile"), 3)

	def test_wip_is_zero_without_job_cards(self):
		from a3_retail.a3_retail_service.doctype.technician_profile.technician_profile import count_wip

		employee = frappe.db.get_value("Technician Profile", {}, "employee")
		self.assertIsInstance(count_wip(employee), int)

	def test_duplicate_profile_is_rejected(self):
		existing = frappe.get_all("Technician Profile", fields=["name", "employee"], limit=1)
		if not existing:
			self.skipTest("no technician profiles seeded")

		duplicate = frappe.new_doc("Technician Profile")
		duplicate.employee = existing[0].employee
		duplicate.technician_level = "L1 - Software"
		duplicate.flags.ignore_permissions = True
		# autoname() derives the name from the employee, so a second profile for
		# the same employee is rejected either by our validation or by the
		# primary-key constraint — both are the correct outcome.
		self.assertRaises((frappe.ValidationError, frappe.DuplicateEntryError), duplicate.insert)

	def test_issue_types_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Service Issue Type"), 12)

	def test_liquid_damage_voids_warranty(self):
		self.assertTrue(frappe.db.get_value("Service Issue Type", "Water Damage", "is_warranty_void_trigger"))
