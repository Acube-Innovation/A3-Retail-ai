# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Item / IMEI / Customer masters (scope step 4, sections 1.2 – 1.4)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.api.customer import get_or_create, normalize_mobile, validate_mobile
from a3_retail.overrides.serial_no import resolve_warranty_state
from a3_retail.tests.fixtures import ensure_branch, ensure_company
from a3_retail.utils.gst import gstin_check_digit, is_valid_gstin, normalize_gstin

# Luhn-valid IMEIs for tests (the scope document's samples are not).
VALID_IMEI = "356938035643809"
VALID_IMEI_2 = "353912104567895"


class TestItemCustomFields(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_company()

	def test_device_fields_exist_on_item(self):
		meta = frappe.get_meta("Item")
		for fieldname in (
			"a3_is_device",
			"a3_device_model",
			"a3_brand_warranty_months",
			"a3_is_ew_plan",
			"a3_is_service_item",
			"a3_min_selling_price",
			"a3_is_margin_scheme",
		):
			self.assertTrue(meta.has_field(fieldname), f"Item.{fieldname} is missing")

	def test_cost_fields_are_permlevel_one(self):
		meta = frappe.get_meta("Item")
		for fieldname in ("a3_min_selling_price", "a3_sales_spiff"):
			self.assertEqual(meta.get_field(fieldname).permlevel, 1, fieldname)

	def test_every_device_item_is_serialized(self):
		"""Scope 1.5: devices must carry serial numbers."""
		rows = frappe.get_all("Item", filters={"a3_is_device": 1, "has_serial_no": 0}, pluck="name")
		self.assertEqual(rows, [], f"device items without serial tracking: {rows}")

	def test_serial_no_register_fields_exist(self):
		meta = frappe.get_meta("Serial No")
		for fieldname in ("a3_imei_1", "a3_imei_2", "a3_warranty_state", "a3_service_count"):
			self.assertTrue(meta.has_field(fieldname), f"Serial No.{fieldname} is missing")


class TestSerialNoIMEI(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = ensure_branch("Kochi", "KCH")
		cls.item = "MOB-SAM-A55-8-128-BLU"

	def tearDown(self):
		for imei in (VALID_IMEI, VALID_IMEI_2):
			if frappe.db.exists("Serial No", imei):
				frappe.delete_doc("Serial No", imei, force=1, ignore_permissions=True)

	def _make_serial(self, imei):
		# ERPNext v15 refuses a warehouse on a directly-created Serial No — the
		# warehouse is owned by the Stock Ledger. Registration-only creation is
		# what the IMEI register needs here.
		doc = frappe.new_doc("Serial No")
		doc.item_code = self.item
		doc.a3_imei_1 = imei
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return doc

	def test_serial_is_named_after_the_imei(self):
		serial = self._make_serial(VALID_IMEI)
		self.assertEqual(serial.name, VALID_IMEI)
		self.assertEqual(serial.a3_warranty_state, "Not Sold")

	def test_invalid_imei_is_rejected(self):
		doc = frappe.new_doc("Serial No")
		doc.item_code = self.item
		doc.a3_imei_1 = "353912104567891"  # correct check digit is 5, not 1
		doc.flags.ignore_permissions = True
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_duplicate_imei_is_rejected(self):
		self._make_serial(VALID_IMEI)
		duplicate = frappe.new_doc("Serial No")
		duplicate.item_code = self.item
		duplicate.a3_imei_1 = VALID_IMEI
		duplicate.flags.ignore_permissions = True
		self.assertRaises(Exception, duplicate.insert)

	def test_same_imei_in_both_slots_is_rejected(self):
		doc = frappe.new_doc("Serial No")
		doc.item_code = self.item
		doc.a3_imei_1 = VALID_IMEI
		doc.a3_imei_2 = VALID_IMEI
		doc.flags.ignore_permissions = True
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_override_checkbox_allows_non_luhn_imei(self):
		"""Scope 1.2: refurb stock can carry a non-standard IMEI, per record."""
		doc = frappe.new_doc("Serial No")
		doc.item_code = self.item
		doc.a3_imei_1 = "353912104567891"
		doc.a3_imei_override = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.name, "353912104567891")
		frappe.delete_doc("Serial No", doc.name, force=1, ignore_permissions=True)

	def test_bypass_flag_allows_non_luhn_imei(self):
		"""Demo seeding and refurb stock use the documented override (scope 1.2)."""
		frappe.flags.a3_bypass_imei_check = True
		try:
			doc = frappe.new_doc("Serial No")
			doc.item_code = self.item
			doc.a3_imei_1 = "353912104567891"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			self.assertEqual(doc.name, "353912104567891")
			frappe.delete_doc("Serial No", doc.name, force=1, ignore_permissions=True)
		finally:
			frappe.flags.a3_bypass_imei_check = False

	def test_brand_warranty_expiry_is_computed(self):
		serial = self._make_serial(VALID_IMEI)
		serial.a3_activation_date = "2026-04-12"
		serial.save(ignore_permissions=True)
		self.assertEqual(str(serial.a3_brand_warranty_expiry), "2027-04-12")

	def test_warranty_state_resolution(self):
		self.assertEqual(resolve_warranty_state({}), "Not Sold")
		self.assertEqual(resolve_warranty_state({"a3_warranty_state": "Void"}), "Void")
		self.assertEqual(
			resolve_warranty_state(
				{"a3_activation_date": "2026-01-01", "a3_brand_warranty_expiry": "2099-01-01"}
			),
			"In Warranty",
		)
		self.assertEqual(
			resolve_warranty_state(
				{
					"a3_activation_date": "2020-01-01",
					"a3_brand_warranty_expiry": "2021-01-01",
					"a3_ew_expiry": "2099-01-01",
				}
			),
			"In Extended Warranty",
		)
		self.assertEqual(
			resolve_warranty_state(
				{"a3_activation_date": "2020-01-01", "a3_brand_warranty_expiry": "2021-01-01"}
			),
			"Out of Warranty",
		)


class TestCustomerAPI(FrappeTestCase):
	MOBILE = "9876500011"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")

	def tearDown(self):
		name = frappe.db.get_value("Customer", {"a3_mobile_no": self.MOBILE}, "name")
		if name:
			frappe.delete_doc("Customer", name, force=1, ignore_permissions=True)

	def test_mobile_normalisation(self):
		self.assertEqual(normalize_mobile("+91 98470 12345"), "9847012345")
		self.assertEqual(normalize_mobile("098470-12345"), "9847012345")
		self.assertEqual(normalize_mobile(None), "")

	def test_invalid_mobile_is_rejected(self):
		self.assertRaises(frappe.ValidationError, validate_mobile, "12345")
		self.assertRaises(frappe.ValidationError, validate_mobile, "1234567890")

	def test_get_or_create_creates_once(self):
		first = get_or_create(self.MOBILE, "Test Walk-in", branch="Kochi")
		second = get_or_create(self.MOBILE, "Someone Else", branch="Kochi")
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(second["customer_name"], "Test Walk-in")

	def test_created_customer_carries_defaults(self):
		profile = get_or_create(self.MOBILE, "Test Walk-in", branch="Kochi")
		self.assertEqual(profile["mobile_no"], self.MOBILE)
		self.assertEqual(profile["whatsapp_no"], self.MOBILE)
		self.assertEqual(profile["source_branch"], "Kochi")
		self.assertTrue(profile["marketing_optin"])

	def test_create_requires_a_name(self):
		self.assertRaises(frappe.ValidationError, get_or_create, self.MOBILE)

	def test_demo_mobile_numbers_are_unique(self):
		"""Scope 1.5: the mobile number is the primary search key."""
		rows = frappe.db.sql(
			"""select a3_mobile_no, count(*) c from `tabCustomer`
			   where ifnull(a3_mobile_no,'') != '' group by a3_mobile_no having c > 1"""
		)
		self.assertFalse(rows, f"duplicate mobile numbers: {rows}")


class TestGSTINHelpers(FrappeTestCase):
	def test_check_digit_matches_india_compliance(self):
		from india_compliance.gst_india.utils import validate_gstin_check_digit

		fixed = normalize_gstin("32AABCM1234K1Z5")
		# Should not raise.
		validate_gstin_check_digit(fixed)
		self.assertTrue(is_valid_gstin(fixed))

	def test_scope_sample_gstin_is_invalid_as_printed(self):
		self.assertFalse(is_valid_gstin("32AABCM1234K1Z5"))
		self.assertEqual(gstin_check_digit("32AABCM1234K1Z"), "V")

	def test_normalize_is_idempotent(self):
		once = normalize_gstin("32AABCM1234K1Z5")
		self.assertEqual(normalize_gstin(once), once)
