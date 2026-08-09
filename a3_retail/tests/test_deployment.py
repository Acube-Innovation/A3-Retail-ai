# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Installing this app somewhere else.

The app has only ever lived on one site, so these are the checks that stand in
for a fresh install: that the installer is idempotent, that it creates no
tenant's data, that it survives an app it can do without, and that every
customisation is built in code rather than exported from somebody's database.
"""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail import hooks
from a3_retail.setup import custom_fields, install_defaults


class TestRequiredApps(FrappeTestCase):
	def test_the_app_declares_what_it_cannot_run_without(self):
		"""erpnext for the ledgers, india_compliance for GST, hrms for attendance."""
		self.assertEqual(
			hooks.required_apps,
			["frappe/erpnext", "india_compliance", "frappe/hrms"],
		)

	def test_required_apps_name_apps_not_repositories(self):
		"""The trap: `parse_app_name` resolves a *repo* name, and two differ.

		india-compliance's repository is "india-compliance" but its app is
		"india_compliance"; frappe/health's app is "healthcare". An entry that
		resolves to a repo name makes `install_app` chase a module that is not
		there, and the install dies on a fresh site.
		"""
		from frappe.installer import parse_app_name

		for entry in hooks.required_apps:
			self.assertIn(parse_app_name(entry), frappe.get_all_apps(), entry)

	def test_those_apps_are_installed_here(self):
		installed = set(frappe.get_installed_apps())
		for app in ("erpnext", "india_compliance", "hrms"):
			self.assertIn(app, installed, app)


class TestNoFixtures(FrappeTestCase):
	"""Every customisation is built by a setup module, never exported as data."""

	def test_the_app_ships_no_fixtures(self):
		self.assertFalse(hasattr(hooks, "fixtures"),
		                 "fixtures give each record a second source that drifts")
		self.assertFalse(
			os.path.exists(frappe.get_app_path("a3_retail", "fixtures")),
			"a fixtures folder would ship one site's data to another",
		)

	def test_nothing_was_made_through_the_desk(self):
		"""A doctype created in a browser is invisible to git and to a new site."""
		self.assertEqual(frappe.get_all("DocType", filters={"custom": 1}, pluck="name"), [])

	def test_what_fixtures_used_to_carry_is_built_in_code(self):
		for doctype in ("Custom Field", "Print Format", "Number Card", "Dashboard Chart",
		                "Workspace"):
			self.assertGreater(
				frappe.db.count(doctype, {"module": ["like", "A3%"]}), 0,
				f"{doctype} should be created by a setup module",
			)


class TestInstallerIsSafeToRerun(FrappeTestCase):
	"""`after_migrate` runs the whole installer on every deploy."""

	def _snapshot(self) -> dict:
		return {
			doctype: frappe.db.count(doctype, {"module": ["like", "A3%"]})
			for doctype in ("Custom Field", "Print Format", "Number Card", "Dashboard Chart",
			                "Workspace")
		}

	def test_running_it_twice_changes_nothing(self):
		before = self._snapshot()
		install_defaults.run()
		self.assertEqual(self._snapshot(), before)

	def test_it_creates_no_tenant_data(self):
		"""A customer's site must come up empty: no company, no branch, no customer."""
		counts = {name: frappe.db.count(name) for name in ("Company", "Branch", "Customer")}
		install_defaults.run()
		self.assertEqual({name: frappe.db.count(name)
		                  for name in ("Company", "Branch", "Customer")}, counts)

	def test_the_demo_company_is_not_part_of_the_install_path(self):
		"""setup/company.py names a demo tenant; the installer must never call it."""
		body = open(frappe.get_app_path("a3_retail", "setup", "install_defaults.py")).read()
		self.assertNotIn("company", body.split("def run()")[1].split("def ")[0],
		                 "install_defaults.run() must not bootstrap a company")

		installer = open(frappe.get_app_path("a3_retail", "install.py")).read()
		after_install = installer.split("def after_install()")[1].split("def ")[0]
		self.assertNotIn("setup_company", after_install)


class TestSurvivesAMissingApp(FrappeTestCase):
	"""Custom fields are the one install step that dies on an absent doctype."""

	def test_fields_for_an_uninstalled_doctype_are_skipped(self):
		group = {
			"Item": [{"fieldname": "a3_probe", "label": "Probe", "fieldtype": "Data"}],
			"Doctype From An App That Is Not Here": [
				{"fieldname": "a3_probe", "label": "Probe", "fieldtype": "Data"}],
		}
		self.assertEqual(list(custom_fields._installed_only(group)), ["Item"])

	def test_frappe_itself_would_have_thrown(self):
		"""Why the filter exists: create_custom_fields does not check first."""
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		with self.assertRaises(frappe.LinkValidationError):
			create_custom_fields(
				{"Doctype From An App That Is Not Here": [
					{"fieldname": "a3_probe", "label": "Probe", "fieldtype": "Data"}]},
				ignore_validate=True, update=True,
			)

	def test_the_hr_group_names_doctypes_from_hrms(self):
		"""If this ever becomes empty, the guard above is protecting nothing."""
		self.assertTrue({"Attendance", "Employee Checkin"} <= set(custom_fields.HR_FIELDS))


class TestTheDocsMatchTheApp(FrappeTestCase):
	def test_deployment_and_architecture_are_written_down(self):
		root = os.path.dirname(os.path.dirname(frappe.get_app_path("a3_retail")))
		for name in ("docs/DEPLOYMENT.md", "docs/ARCHITECTURE.md", "CLAUDE.md"):
			self.assertTrue(os.path.exists(os.path.join(root, "a3_retail", name)), name)

	def test_the_runbook_names_the_apps_the_hooks_require(self):
		root = os.path.dirname(os.path.dirname(frappe.get_app_path("a3_retail")))
		runbook = open(os.path.join(root, "a3_retail", "docs", "DEPLOYMENT.md")).read()
		for app in ("erpnext", "india-compliance", "hrms"):
			self.assertIn(app, runbook, app)
