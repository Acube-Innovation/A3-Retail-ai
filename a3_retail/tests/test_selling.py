# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Selling guards, IMEI capture and serial stamping (scope step 12, 2.1–2.5)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from a3_retail.overrides.sales_invoice import (
	suggest_ew_plans,
	validate_device_serials,
	validate_minimum_price,
	validate_pos_serial,
)
from a3_retail.tests.fixtures import ensure_branch

DEVICE = "MOB-SAM-A55-8-128-BLU"
ACCESSORY = "ACC-TGL-A55"
IMEI = "356938035643809"


def draft_invoice(items, **overrides):
	"""An unsaved Sales Invoice used to exercise the validators directly."""
	branch = ensure_branch("Kochi", "KCH")
	customer = frappe.db.get_value("Customer", {"a3_mobile_no": "9847012345"}, "name") or frappe.db.get_value(
		"Customer", {}, "name"
	)

	doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": customer,
			"company": branch.company,
			"posting_date": nowdate(),
			"branch": branch.branch,
			"items": items,
			**overrides,
		}
	)
	return doc


class TestDeviceSerialGuard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_device_line_without_a_serial_is_rejected(self):
		doc = draft_invoice([{"item_code": DEVICE, "qty": 1, "rate": 39999}])
		self.assertRaises(frappe.ValidationError, validate_device_serials, doc)

	def test_device_line_with_a_serial_passes(self):
		doc = draft_invoice([{"item_code": DEVICE, "qty": 1, "rate": 39999, "serial_no": IMEI}])
		validate_device_serials(doc)  # must not raise

	def test_serial_count_must_match_quantity(self):
		doc = draft_invoice([{"item_code": DEVICE, "qty": 2, "rate": 39999, "serial_no": IMEI}])
		self.assertRaises(frappe.ValidationError, validate_device_serials, doc)

	def test_accessory_needs_no_serial(self):
		doc = draft_invoice([{"item_code": ACCESSORY, "qty": 3, "rate": 299}])
		validate_device_serials(doc)

	def test_returns_are_exempt(self):
		doc = draft_invoice([{"item_code": DEVICE, "qty": -1, "rate": 39999}], is_return=1)
		validate_device_serials(doc)

	def test_comma_separated_serials_are_parsed(self):
		doc = draft_invoice(
			[{"item_code": DEVICE, "qty": 2, "rate": 39999, "serial_no": f"{IMEI},353912104567895"}]
		)
		validate_device_serials(doc)


class TestMinimumPriceGuard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_minimum_price_is_seeded(self):
		self.assertGreater(flt(frappe.db.get_value("Item", DEVICE, "a3_min_selling_price")), 0)

	def test_below_minimum_is_blocked_for_a_branch_user(self):
		minimum = flt(frappe.db.get_value("Item", DEVICE, "a3_min_selling_price"))
		doc = draft_invoice([{"item_code": DEVICE, "qty": 1, "rate": minimum - 1000, "serial_no": IMEI}])

		# Administrator may override, so check as a plain Sales Executive.
		frappe.set_user("Administrator")
		user = "a3test.selling@example.com"
		if not frappe.db.exists("User", user):
			u = frappe.new_doc("User")
			u.email = user
			u.first_name = "Selling"
			u.send_welcome_email = 0
			u.append("roles", {"role": "Sales Executive"})
			u.flags.ignore_permissions = True
			u.insert(ignore_permissions=True)

		try:
			frappe.set_user(user)
			self.assertRaises(frappe.ValidationError, validate_minimum_price, doc)
		finally:
			frappe.set_user("Administrator")

	def test_branch_manager_may_sell_below_minimum(self):
		minimum = flt(frappe.db.get_value("Item", DEVICE, "a3_min_selling_price"))
		doc = draft_invoice([{"item_code": DEVICE, "qty": 1, "rate": minimum - 1000, "serial_no": IMEI}])
		# Administrator holds every role.
		validate_minimum_price(doc)

	def test_at_or_above_minimum_passes(self):
		minimum = flt(frappe.db.get_value("Item", DEVICE, "a3_min_selling_price"))
		doc = draft_invoice([{"item_code": DEVICE, "qty": 1, "rate": minimum, "serial_no": IMEI}])
		validate_minimum_price(doc)


class TestPosHelpers(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_unknown_imei_is_refused(self):
		result = validate_pos_serial(DEVICE, "999999999999999", self.branch.default_warehouse)
		self.assertFalse(result["valid"])
		self.assertIn("not in stock", result["reason"])

	def test_serial_of_a_different_item_is_refused(self):
		if not frappe.db.exists("Serial No", IMEI):
			serial = frappe.new_doc("Serial No")
			serial.item_code = DEVICE
			serial.a3_imei_1 = IMEI
			serial.flags.ignore_permissions = True
			serial.insert(ignore_permissions=True)

		result = validate_pos_serial("MOB-APL-15-128-BLK", IMEI, self.branch.default_warehouse)
		self.assertFalse(result["valid"])
		self.assertIn("belongs to", result["reason"])

	def test_ew_plans_are_suggested_for_devices(self):
		plans = suggest_ew_plans(DEVICE)
		self.assertTrue(plans)
		self.assertTrue(all(p.get("plan_item") for p in plans))

	def test_no_plans_for_an_accessory(self):
		self.assertEqual(suggest_ew_plans(ACCESSORY), [])

	def test_availability_matrix_shape(self):
		from a3_retail.api.stock import availability_matrix

		rows = availability_matrix(DEVICE)
		self.assertIsInstance(rows, list)
		for row in rows:
			self.assertIn("branch", row)
			self.assertIn("available", row)

	def test_item_search_returns_branch_quantity(self):
		from a3_retail.api.stock import search_items

		rows = search_items("Galaxy", branch="Kochi")
		self.assertTrue(rows)
		self.assertIn("branch_qty", rows[0])


class TestEwAttachFlag(FrappeTestCase):
	def test_flag_is_set_when_a_plan_is_on_the_invoice(self):
		from a3_retail.overrides.sales_invoice import flag_extended_warranty

		doc = draft_invoice(
			[
				{"item_code": DEVICE, "qty": 1, "rate": 39999, "serial_no": IMEI},
				{"item_code": "EW-PLAN-12M", "qty": 1, "rate": 1999},
			]
		)
		flag_extended_warranty(doc)
		self.assertTrue(doc.a3_ew_attached)

	def test_flag_is_clear_without_a_plan(self):
		from a3_retail.overrides.sales_invoice import flag_extended_warranty

		doc = draft_invoice([{"item_code": ACCESSORY, "qty": 1, "rate": 299}])
		flag_extended_warranty(doc)
		self.assertFalse(doc.a3_ew_attached)
