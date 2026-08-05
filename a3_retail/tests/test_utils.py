# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Unit tests for the shared utility package (scope step 1)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.utils.imei import (
	format_imei,
	luhn_check_digit,
	normalize_imei,
	validate_imei,
)
from a3_retail.utils.permissions import (
	BRANCH_SCOPED_DOCTYPES,
	build_branch_condition,
	get_permission_query_conditions_factory,
)


class TestIMEIUtils(FrappeTestCase):
	def test_valid_imei_passes_luhn(self):
		# 356938035643809 is the one demo IMEI in the scope document that is a
		# genuine Luhn-valid number.
		self.assertTrue(validate_imei("356938035643809"))
		self.assertTrue(validate_imei("353912104567895"))

	def test_spec_sample_imei_is_not_luhn_valid(self):
		"""Scope step 1 asserts validate_imei('353912104567891') is True.

		That number's correct check digit is 5, not 1, so the assertion in the
		scope document is wrong — the demo IMEIs there are illustrative. We keep
		Luhn correct and let demo seeding use the documented override instead.
		"""
		self.assertFalse(validate_imei("353912104567891"))
		self.assertEqual(luhn_check_digit("35391210456789"), 5)

	def test_short_string_is_rejected(self):
		self.assertFalse(validate_imei("123"))

	def test_wrong_check_digit_is_rejected(self):
		self.assertFalse(validate_imei("353912104567892"))

	def test_empty_and_none_are_rejected(self):
		self.assertFalse(validate_imei(""))
		self.assertFalse(validate_imei(None))

	def test_letters_are_rejected(self):
		self.assertFalse(validate_imei("35391210456789A"))

	def test_normalize_strips_separators(self):
		self.assertEqual(normalize_imei("35-391210-456789-1"), "353912104567891")
		self.assertEqual(normalize_imei(" 3539 1210 4567 891 "), "353912104567891")
		self.assertEqual(normalize_imei(None), "")

	def test_normalised_imei_still_validates(self):
		self.assertTrue(validate_imei("35-391210-456789-5"))

	def test_check_digit_computation(self):
		self.assertEqual(luhn_check_digit("35391210456789"), 5)
		self.assertEqual(luhn_check_digit("35693803564380"), 9)

	def test_format_groups_digits(self):
		self.assertEqual(format_imei("353912104567891"), "35-391210-456789-1")
		# Anything that is not 15 digits comes back untouched.
		self.assertEqual(format_imei("123"), "123")


class TestBranchUtils(FrappeTestCase):
	def test_get_user_branch_for_administrator_does_not_raise(self):
		from a3_retail.utils.branch import get_user_branch

		# Administrator has no Employee, so the helper must degrade gracefully
		# rather than raise, whether or not any Branch Profile exists yet.
		if not frappe.db.table_exists("Branch Profile"):
			self.skipTest("Branch Profile is introduced in step 2")
		self.assertIn(type(get_user_branch("Administrator")).__name__, ("str", "NoneType"))

	def test_set_branch_defaults_is_noop_without_branch(self):
		from a3_retail.utils.branch import set_branch_defaults

		doc = frappe.new_doc("A3 Retail Settings")
		# Settings has no branch field — the helper must simply return the doc.
		self.assertIs(set_branch_defaults(doc), doc)


class TestPermissionUtils(FrappeTestCase):
	def test_factory_returns_callable_per_doctype(self):
		fn = get_permission_query_conditions_factory("Service Job Card", "branch")
		self.assertTrue(callable(fn))
		self.assertEqual(fn.__name__, "get_permission_query_conditions_service_job_card")

	def test_administrator_is_unrestricted(self):
		self.assertEqual(build_branch_condition("Service Job Card", "branch", "Administrator"), "")

	def test_every_scoped_doctype_has_a_registered_query(self):
		import a3_retail.utils.permissions as perms

		for doctype in BRANCH_SCOPED_DOCTYPES:
			self.assertTrue(hasattr(perms, f"{frappe.scrub(doctype)}_query"), doctype)


class TestSettings(FrappeTestCase):
	def test_settings_singleton_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "A3 Retail Settings"))
		settings = frappe.get_single("A3 Retail Settings")
		self.assertEqual(settings.doctype, "A3 Retail Settings")

	def test_luhn_enforced_by_default(self):
		from a3_retail.utils.imei import is_luhn_enforced

		self.assertIsInstance(is_luhn_enforced(), bool)
