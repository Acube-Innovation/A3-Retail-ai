# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Reception Desk page registration and its API contract (scope step 10, 3.9)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.tests.fixtures import ensure_branch

RESTRICTED_ROLES = {"Reception Executive", "Branch Manager", "Service Manager", "A3 Retail Admin"}


class TestReceptionDeskPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_page_is_registered(self):
		self.assertTrue(frappe.db.exists("Page", "a3-reception-desk"))

	def test_page_is_restricted_to_the_right_roles(self):
		"""Scope step 10: the desk is not open to every logged-in user."""
		# Page.roles is a `Has Role` child table.
		roles = set(
			frappe.get_all(
				"Has Role",
				filters={"parent": "a3-reception-desk", "parenttype": "Page"},
				pluck="role",
			)
		)
		self.assertTrue(roles)
		self.assertTrue(RESTRICTED_ROLES.issubset(roles), roles)
		self.assertNotIn("Guest", roles)

	def test_every_desk_endpoint_is_whitelisted(self):
		"""The six endpoints the desk calls must be reachable over /api/method."""
		from a3_retail.api import service

		for name in ("lookup_customer", "lookup_imei", "create_job_card", "take_advance",
		             "deliver_job_card", "dashboard_counters"):
			method = getattr(service, name)
			# frappe.whitelisted holds the undecorated functions.
			target = getattr(method, "__func__", method)
			self.assertIn(target, frappe.whitelisted, f"{name} is not whitelisted")

	def test_endpoints_check_permissions(self):
		"""Each endpoint must call a permission helper, not rely on @whitelist."""
		import inspect

		from a3_retail.api import service

		for name in ("lookup_customer", "create_job_card", "take_advance", "deliver_job_card",
		             "dashboard_counters"):
			source = inspect.getsource(getattr(service, name))
			self.assertTrue(
				"require_permission" in source or "require_role" in source,
				f"{name} has no explicit permission check",
			)
