# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Branch data isolation (scope step 3, 13.5)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.overrides.employee import clear_branch_permissions, sync_user_permissions
from a3_retail.setup.permissions import PERMISSION_MATRIX
from a3_retail.tests.fixtures import ensure_branch, ensure_company, ensure_employee
from a3_retail.utils.permissions import build_branch_condition, get_permitted_branches

BRANCH_USER = "a3test.branchuser@example.com"


class TestBranchIsolation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_company()
		cls.kochi = ensure_branch("Kochi", "KCH")
		cls.tvm = ensure_branch("Thiruvananthapuram", "TVM")
		cls.user = cls._make_branch_user()

	@classmethod
	def _make_branch_user(cls):
		if not frappe.db.exists("User", BRANCH_USER):
			user = frappe.new_doc("User")
			user.email = BRANCH_USER
			user.first_name = "Branch"
			user.last_name = "Tester"
			user.send_welcome_email = 0
			user.user_type = "System User"
			user.append("roles", {"role": "Sales Executive"})
			user.flags.ignore_permissions = True
			user.insert(ignore_permissions=True)

		employee = frappe.db.get_value("Employee", {"user_id": BRANCH_USER}, "name")
		if not employee:
			employee = ensure_employee("Branch Tester", "Kochi", "Sales Executive")
			doc = frappe.get_doc("Employee", employee)
			doc.user_id = BRANCH_USER
			doc.create_user_permission = 0
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)

		sync_user_permissions(BRANCH_USER, "Kochi")
		frappe.db.commit()
		return BRANCH_USER

	def test_user_permission_created_for_branch(self):
		self.assertTrue(
			frappe.db.exists("User Permission", {"user": self.user, "allow": "Branch", "for_value": "Kochi"})
		)

	def test_user_permission_scoped_to_kochi_warehouses_only(self):
		values = frappe.get_all(
			"User Permission",
			filters={"user": self.user, "allow": "Warehouse"},
			pluck="for_value",
			distinct=True,
		)
		self.assertTrue(values, "no warehouse permissions were created")
		shared = self.kochi.transit_warehouse
		for warehouse in values:
			if warehouse == shared:
				# Goods In Transit is company-level by design (scope 6.2) and
				# deliberately carries no branch.
				continue
			self.assertEqual(
				frappe.db.get_value("Warehouse", warehouse, "custom_branch"),
				"Kochi",
				f"{warehouse} is not a Kochi warehouse",
			)
		self.assertNotIn(self.tvm.default_warehouse, values)

	def test_permissions_are_never_apply_to_all_doctypes(self):
		"""Masters (Item, Customer) are shared — a blanket permission would hide them."""
		rows = frappe.get_all(
			"User Permission",
			filters={"user": self.user},
			fields=["allow", "apply_to_all_doctypes", "applicable_for"],
		)
		for row in rows:
			self.assertFalse(row.apply_to_all_doctypes, f"{row.allow} applies to all doctypes")
			self.assertTrue(row.applicable_for, f"{row.allow} has no applicable_for")

	def test_permitted_branches_for_branch_user(self):
		self.assertEqual(get_permitted_branches(self.user), ["Kochi"])

	def test_query_condition_restricts_to_branch(self):
		condition = build_branch_condition("Service Job Card", "branch", self.user)
		self.assertIn("Kochi", condition)
		self.assertIn("`tabService Job Card`.`branch`", condition)

	def test_head_office_roles_are_unrestricted(self):
		self.assertEqual(get_permitted_branches("Administrator"), [])
		self.assertEqual(build_branch_condition("Service Job Card", "branch", "Administrator"), "")

	def test_permissions_resync_on_branch_change(self):
		sync_user_permissions(self.user, "Thiruvananthapuram")
		values = frappe.get_all(
			"User Permission", filters={"user": self.user, "allow": "Branch"}, pluck="for_value"
		)
		self.assertEqual(set(values), {"Thiruvananthapuram"})
		# put it back so the other tests in the class are unaffected
		sync_user_permissions(self.user, "Kochi")

	def test_clear_removes_all_managed_permissions(self):
		clear_branch_permissions(self.user)
		self.assertFalse(frappe.db.exists("User Permission", {"user": self.user, "allow": "Branch"}))
		sync_user_permissions(self.user, "Kochi")


class TestPermissionMatrix(FrappeTestCase):
	def test_strict_user_permissions_enabled(self):
		self.assertEqual(frappe.db.get_single_value("System Settings", "apply_strict_user_permissions"), 1)

	def test_every_matrix_role_exists(self):
		for doctype, roles in PERMISSION_MATRIX.items():
			for role in roles:
				self.assertTrue(frappe.db.exists("Role", role), f"{role} (referenced by {doctype}) is missing")

	def test_branch_manager_can_submit_job_cards(self):
		if not frappe.db.exists("DocType", "Service Job Card"):
			self.skipTest("Service Job Card arrives in step 7")
		perm = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Service Job Card", "role": "Branch Manager", "permlevel": 0},
			["read", "submit"],
			as_dict=True,
		)
		self.assertTrue(perm and perm.read and perm.submit)

	def test_technician_cannot_delete_job_cards(self):
		if not frappe.db.exists("DocType", "Service Job Card"):
			self.skipTest("Service Job Card arrives in step 7")
		perm = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Service Job Card", "role": "Technician", "permlevel": 0},
			["read", "delete"],
			as_dict=True,
		)
		self.assertTrue(perm and perm.read)
		self.assertFalse(perm.delete)

	def test_cost_fields_are_permlevel_gated_on_item(self):
		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Item", "permlevel": 1},
			pluck="role",
		)
		self.assertIn("Branch Manager", rows)
		self.assertNotIn("Sales Executive", rows)
