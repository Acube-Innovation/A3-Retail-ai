# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Rounding the GST on a bill is the shop's call, not the installer's.

The installer used to set GST Settings → Round Off GST Values on every migrate,
so a deploy undid the shop's own choice each time. What is held here is that it
no longer does, and that nothing else in the app quietly asserts it either.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.setup import tax


class TestTheInstallerLeavesItAlone(FrappeTestCase):
	def test_the_installer_never_sets_the_round_off_flag(self):
		"""Read the installer's own source: the field must not be in the list
		it re-asserts on every migrate."""
		source = open(frappe.get_app_path("a3_retail", "setup", "tax.py"),
		              encoding="utf-8").read()
		body = source.split("def ensure_gst_settings")[1].split("\ndef ")[0]
		for line in body.splitlines():
			bare = line.split("#")[0]
			self.assertNotIn("round_off_gst_values", bare, line.strip())

	def test_running_the_installer_does_not_turn_it_on(self):
		before = frappe.db.get_single_value("GST Settings", "round_off_gst_values")
		try:
			frappe.db.set_single_value("GST Settings", "round_off_gst_values", 0)
			frappe.clear_document_cache("GST Settings", "GST Settings")
			tax.ensure_gst_settings()
			self.assertFalse(
				frappe.db.get_single_value("GST Settings", "round_off_gst_values"))
		finally:
			frappe.db.set_single_value("GST Settings", "round_off_gst_values", before)
			frappe.clear_document_cache("GST Settings", "GST Settings")

	def test_the_settings_the_installer_does_own_are_still_set(self):
		"""Taking one field out must not take the others with it."""
		source = open(frappe.get_app_path("a3_retail", "setup", "tax.py"),
		              encoding="utf-8").read()
		body = source.split("def ensure_gst_settings")[1].split("\ndef ")[0]
		for field in ("enable_e_invoice", "enable_e_waybill",
		              "enable_reverse_charge_in_sales"):
			self.assertIn(field, body)

	def test_nothing_else_in_the_app_sets_it(self):
		"""One place decides, and that place is the desk."""
		import os
		root = frappe.get_app_path("a3_retail")
		offenders = []
		for folder, _dirs, files in os.walk(root):
			if "tests" in folder or "__pycache__" in folder:
				continue
			for name in files:
				if not name.endswith(".py") or name == "gst_round_off_off.py":
					continue
				path = os.path.join(folder, name)
				with open(path, encoding="utf-8") as handle:
					for line in handle:
						bare = line.split("#")[0]
						if "round_off_gst_values" in bare:
							offenders.append(f"{path}: {line.strip()}")
		self.assertEqual(offenders, [])


class TestTheOneTimeSwitch(FrappeTestCase):
	def test_the_patch_runs_on_a_deploy(self):
		registered = open(frappe.get_app_path("a3_retail", "patches.txt")).read()
		self.assertIn("a3_retail.patches.gst_round_off_off", registered)

	def test_it_turns_the_flag_off_and_is_safe_to_run_again(self):
		from a3_retail.patches import gst_round_off_off

		before = frappe.db.get_single_value("GST Settings", "round_off_gst_values")
		# The patch commits, as a patch should. A test must not, or it writes
		# the site it is checking.
		commit = frappe.db.commit
		frappe.db.commit = lambda *a, **k: None
		try:
			frappe.db.set_single_value("GST Settings", "round_off_gst_values", 1)
			frappe.clear_document_cache("GST Settings", "GST Settings")
			gst_round_off_off.execute()
			self.assertFalse(
				frappe.db.get_single_value("GST Settings", "round_off_gst_values"))
			gst_round_off_off.execute()
			self.assertFalse(
				frappe.db.get_single_value("GST Settings", "round_off_gst_values"))
		finally:
			frappe.db.commit = commit
			frappe.db.set_single_value("GST Settings", "round_off_gst_values", before)
			frappe.clear_document_cache("GST Settings", "GST Settings")
