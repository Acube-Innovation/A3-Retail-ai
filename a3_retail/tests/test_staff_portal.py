# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""The branch staff app at /retail: accounts, session boundary and dashboard."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.api import staff
from a3_retail.setup import staff_portal
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestPortalAccounts(FrappeTestCase):
	def test_the_portal_role_exists_without_desk_access(self):
		row = frappe.db.get_value(
			"Role", staff_portal.PORTAL_ROLE, ["desk_access", "home_page"], as_dict=True
		)
		self.assertIsNotNone(row)
		self.assertFalse(row.desk_access)
		self.assertEqual(row.home_page, staff_portal.HOME_PAGE)

	def test_shop_floor_roles_have_no_desk_access(self):
		"""This is what keeps branch staff out of ERPNext."""
		for role in staff_portal.BRANCH_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			self.assertFalse(
				frappe.db.get_value("Role", role, "desk_access"),
				f"{role} still opens the desk",
			)

	def test_head_office_roles_keep_the_desk(self):
		for role in ("A3 Retail Admin", "Accounts Manager", "HR Manager"):
			self.assertTrue(frappe.db.get_value("Role", role, "desk_access"), role)

	def test_branch_staff_are_website_users(self):
		for name in ("Arun Menon", "Vishnu P", "Reshma K", "Vipin S"):
			user = user_for(name)
			if not user:
				continue
			self.assertEqual(
				frappe.db.get_value("User", user, "user_type"), "Website User", name
			)

	def test_head_office_staff_stay_system_users(self):
		for name in ("Lakshmi Nair", "Priya Suresh"):
			user = user_for(name)
			if not user:
				continue
			self.assertEqual(
				frappe.db.get_value("User", user, "user_type"), "System User", name
			)

	def test_portal_accounts_keep_their_functional_roles(self):
		"""Converting to a website user must not strip what they are allowed to do."""
		user = user_for("Vishnu P")
		roles = set(frappe.get_roles(user))
		self.assertIn("Technician", roles)
		self.assertIn(staff_portal.PORTAL_ROLE, roles)

	def test_framework_desk_roles_are_removed(self):
		user = user_for("Arun Menon")
		roles = set(frappe.get_all("Has Role", filters={"parent": user}, pluck="role"))
		self.assertFalse(roles & staff_portal.STRIP_ROLES, roles)

	def test_provisioning_is_idempotent(self):
		before = len(staff_portal.provision(verbose=False))
		after = len(staff_portal.provision(verbose=False))
		self.assertEqual(before, after)

	def test_head_office_employees_are_skipped(self):
		provisioned = {row["user"] for row in staff_portal.provision(verbose=False)}
		lakshmi = user_for("Lakshmi Nair")
		self.assertNotIn(lakshmi, provisioned)


class TestPortalPagesExist(FrappeTestCase):
	def test_the_www_pages_are_in_place(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("index.html", "index.py", "login.html", "login.py",
		             "dashboard.html", "dashboard.py", "logout.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

	def test_the_pages_are_standalone_documents(self):
		"""The branch app must not pull in ERPNext's web template or bundles."""
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("index.html", "login.html", "dashboard.html"):
			markup = open(os.path.join(folder, name)).read()
			self.assertIn("<!doctype html>", markup.lower(), name)
			self.assertNotIn("templates/web.html", markup, name)
			self.assertNotIn("{% extends", markup, name)
			self.assertIn("/assets/a3_retail/css/a3_branch.css", markup, name)

	def test_the_customer_portal_still_uses_the_web_template(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "templates", "pages"), "support.html")
		).read()
		self.assertIn("templates/web.html", markup)

	def test_sign_in_works_without_javascript(self):
		"""The counter browser may block scripts; the form must still post."""
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "login.html")
		).read()
		self.assertIn('method="post"', markup)
		self.assertIn('action="/retail/login"', markup)
		self.assertIn('name="usr"', markup)
		self.assertIn('name="pwd"', markup)

	def test_switching_to_the_desk_signs_the_branch_session_out(self):
		"""Frappe bounces a signed-in user away from /login, so the link has to
		end this session on the way there — otherwise the desk is unreachable."""
		import re

		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in os.listdir(folder):
			if not name.endswith(".html"):
				continue
			markup = open(os.path.join(folder, name)).read()
			# Every reference to the desk's own /login must go through logout.
			# /retail/login is this app's form and is not the desk.
			bare = re.findall(r'href="(/login[^"]*)"', markup)
			self.assertFalse(bare, f"{name} links straight at the desk login: {bare}")

	def test_logout_only_redirects_within_the_site(self):
		import importlib.util

		path = os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "logout.py")
		spec = importlib.util.spec_from_file_location("branch_logout", path)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)

		self.assertEqual(module.safe_destination("/login"), "/login")
		for hostile in ("//evil.example", "https://evil.example", "\\evil", "", None):
			self.assertEqual(module.safe_destination(hostile), module.DEFAULT_DESTINATION)

	def test_sign_out_is_a_plain_link(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "dashboard.html")
		).read()
		self.assertIn('href="/retail/logout"', markup)

	def test_the_branch_assets_exist(self):
		for asset in ("css/a3_branch.css", "js/a3_branch.js"):
			self.assertTrue(
				os.path.exists(os.path.join(frappe.get_app_path("a3_retail", "public"), asset)), asset
			)


class TestLanding(FrappeTestCase):
	"""/retail is the front door: public, and where signing out returns you."""

	def _context(self):
		import importlib.util

		path = os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "index.py")
		spec = importlib.util.spec_from_file_location("branch_index", path)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		return module.get_context(frappe._dict())

	def test_a_guest_sees_the_landing_page(self):
		frappe.set_user("Guest")
		try:
			context = self._context()
			self.assertFalse(context.signed_in)
			self.assertFalse(context.employee_name)
		finally:
			frappe.set_user("Administrator")

	def test_signed_in_staff_are_offered_their_dashboard(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")

		frappe.set_user(user)
		try:
			context = self._context()
			self.assertTrue(context.signed_in)
			self.assertEqual(context.employee_name, "Arun Menon")
			self.assertEqual(context.branch, "Kochi")
		finally:
			frappe.set_user("Administrator")

	def test_the_landing_page_counts_live_branches(self):
		context = self._context()
		self.assertEqual(
			context.branch_count, frappe.db.count("Branch Profile", {"is_active": 1})
		)

	def test_signing_out_returns_to_the_landing_page(self):
		page = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "logout.py")
		).read()
		self.assertIn('DEFAULT_DESTINATION = "/retail', page)
		self.assertIn("login_manager.logout()", page)


class TestSessionBoundary(FrappeTestCase):
	def test_a_guest_cannot_read_the_dashboard(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, staff.dashboard)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		"""Administrator is not branch staff, even though it may do anything else."""
		self.assertRaises(frappe.PermissionError, staff.session_context)

	def test_current_employee_is_none_for_guest(self):
		self.assertIsNone(staff_portal.current_employee("Guest"))


class TestDashboard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _as(self, employee_name: str):
		user = user_for(employee_name)
		if not user:
			self.skipTest(f"{employee_name} is not provisioned")
		frappe.set_user(user)
		return user

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_branch_manager_sees_their_own_branch(self):
		self._as("Arun Menon")
		context = staff.session_context()

		self.assertEqual(context["branch"], "Kochi")
		self.assertIn("Branch Manager", context["roles"])
		self.assertTrue(context["is_manager"])

	def test_the_dashboard_has_every_section(self):
		self._as("Arun Menon")
		data = staff.dashboard()
		for key in ("context", "tiles", "my_work", "branch_activity", "notices", "as_of"):
			self.assertIn(key, data)

	def test_tiles_are_scoped_to_the_branch(self):
		self._as("Arun Menon")
		tiles = {tile["label"]: tile["value"] for tile in staff.dashboard()["tiles"]}

		expected = frappe.db.count(
			"Service Job Card",
			{"branch": "Kochi", "docstatus": 1, "status": "Ready for Delivery"},
		)
		self.assertEqual(tiles["Ready for delivery"], expected)

	def test_a_technician_sees_their_own_jobs(self):
		user = self._as("Vishnu P")
		employee = staff_portal.current_employee(user)
		data = staff.dashboard()

		labels = [tile["label"] for tile in data["tiles"]]
		self.assertIn("My open jobs", labels)

		for row in data["my_work"]:
			if row["kind"] != "Repair":
				continue
			self.assertEqual(
				frappe.db.get_value("Service Job Card", row["reference"], "assigned_technician"),
				employee.name,
			)

	def test_a_technician_at_another_branch_sees_different_work(self):
		kochi = self._as("Vishnu P")
		kochi_work = {row["reference"] for row in staff.dashboard()["my_work"]}

		tvm = self._as("Rijo Thomas")
		tvm_work = {row["reference"] for row in staff.dashboard()["my_work"]}

		self.assertFalse(kochi_work & tvm_work, "two branches saw the same rows")
		self.assertEqual(staff.session_context()["branch"], "Thiruvananthapuram")
		self.assertNotEqual(kochi, tvm)

	def test_branch_activity_never_leaves_the_branch(self):
		self._as("Reshma K")
		for row in staff.dashboard()["branch_activity"]:
			self.assertEqual(
				frappe.db.get_value("Service Job Card", row["reference"], "branch"), "Kochi"
			)

	def test_there_is_always_a_notice(self):
		self._as("Vipin S")
		notices = staff.dashboard()["notices"]
		self.assertTrue(notices)
		for notice in notices:
			self.assertIn(notice["tone"], ("good", "warn", "bad"))

	def test_attendance_summary_is_for_the_signed_in_employee(self):
		self._as("Sajeer K")
		summary = staff.my_attendance_summary()
		for key in ("marked", "present", "absent", "percent"):
			self.assertIn(key, summary)
		self.assertLessEqual(summary["present"], summary["marked"])
