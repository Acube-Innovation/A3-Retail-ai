# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.tests.fixtures import ensure_branch, ensure_company


class TestBranchProfile(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()

	def test_branch_creates_four_warehouses(self):
		profile = ensure_branch("Kochi", "KCH")
		for field in ("default_warehouse", "service_warehouse", "damaged_warehouse", "used_device_warehouse"):
			self.assertTrue(profile.get(field), f"{field} was not auto-created")
			self.assertFalse(frappe.db.get_value("Warehouse", profile.get(field), "is_group"))

	def test_state_code_derived_from_gstin(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.gstin = "32AABCM1234K1Z5"
		profile.save()
		self.assertEqual(profile.state_code, "32")

	def test_short_gstin_is_rejected(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.gstin = "32AABCM"
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()

	def test_branch_code_is_uppercased(self):
		profile = ensure_branch("Thiruvananthapuram", "tvm")
		self.assertEqual(profile.branch_code, "TVM")

	def test_group_cost_center_is_rejected(self):
		profile = ensure_branch("Kochi", "KCH")
		group_cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
		profile.cost_center = group_cc
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()

	def test_warehouse_carries_branch_backreference(self):
		profile = ensure_branch("Kochi", "KCH")
		self.assertEqual(
			frappe.db.get_value("Warehouse", profile.default_warehouse, "custom_branch"), profile.branch
		)

	def test_working_hours_must_be_ordered(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.working_hours_from = "20:00:00"
		profile.working_hours_to = "09:30:00"
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()
