# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Device exchange, grading and margin-scheme resale (scope step 14, 2.4)."""

import itertools

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from a3_retail.tests.fixtures import ensure_branch
from a3_retail.utils.imei import luhn_check_digit

# Submitting an exchange writes a Purchase Receipt, and ERPNext commits while
# reposting stock — so tests cannot share one IMEI. Each gets its own.
_imei_counter = itertools.count(1)


def next_imei() -> str:
	prefix = f"3530111012345{next(_imei_counter):01d}"[:14].ljust(14, "0")
	return prefix + str(luhn_check_digit(prefix))


def make_exchange(**overrides):
	branch = ensure_branch("Kochi", "KCH")
	customer = frappe.db.get_value("Customer", {"a3_mobile_no": "9847012345"}, "name") or frappe.db.get_value(
		"Customer", {}, "name"
	)

	doc = frappe.new_doc("Device Exchange")
	doc.branch = branch.branch
	doc.customer = customer
	doc.exchange_date = nowdate()
	doc.old_brand = "Apple"
	doc.old_model = "Apple iPhone 12"
	doc.old_imei = overrides.pop("old_imei", next_imei())
	doc.base_value = overrides.pop("base_value", 22000)
	doc.has_box = 1
	doc.has_charger = 1
	doc.has_bill = 1
	doc.id_proof_type = "Aadhaar"
	doc.id_proof_number_last4 = "1234"
	doc.imei_check_done = 1
	doc.declaration_signed = "data:image/png;base64,iVBORw0KGgo="

	grading = overrides.pop("grading", [])
	doc.update(overrides)
	for row in grading:
		doc.append("grading_parameters", row)

	doc.flags.ignore_permissions = True
	return doc


class TestGrading(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	# No commit here: FrappeTestCase rolls each test back, and committing would
	# leak the exchange (and its stock) into the site.

	def test_pristine_device_grades_a(self):
		doc = make_exchange()
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.grade, "A - Like New")
		self.assertEqual(flt(doc.deductions), 0.0)

	def test_deductions_lower_the_grade(self):
		doc = make_exchange(
			grading=[
				{"parameter": "Display Condition", "deduction_percent": 10},
				{"parameter": "Battery Health", "deduction_percent": 8},
			]
		)
		doc.insert(ignore_permissions=True)

		# 18% off 22,000 = 3,960 and a score of 82 -> grade B.
		self.assertEqual(flt(doc.deductions), 3960.0)
		self.assertEqual(doc.grade, "B - Good")

	def test_missing_accessories_cost_the_customer(self):
		doc = make_exchange(has_box=0, has_charger=0, has_bill=0)
		doc.insert(ignore_permissions=True)
		# 2% + 3% + 2% = 7% of 22,000.
		self.assertEqual(flt(doc.deductions), 1540.0)

	def test_heavy_damage_grades_d(self):
		doc = make_exchange(
			grading=[
				{"parameter": "Display Condition", "deduction_percent": 40},
				{"parameter": "Water Damage", "deduction_percent": 25},
			]
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.grade, "D - Poor / Spares")

	def test_final_value_is_base_minus_deductions_plus_bonus(self):
		doc = make_exchange(grading=[{"parameter": "Body Condition", "deduction_percent": 10}])
		doc.insert(ignore_permissions=True)

		expected = 22000 - 2200 + flt(doc.exchange_bonus)
		self.assertEqual(flt(doc.final_exchange_value), expected)

	def test_value_never_goes_negative(self):
		doc = make_exchange(grading=[{"parameter": "Water Damage", "deduction_percent": 150}])
		doc.insert(ignore_permissions=True)
		self.assertGreaterEqual(flt(doc.final_exchange_value), 0.0)

	def test_invalid_imei_is_rejected(self):
		doc = make_exchange(old_imei="353011101234567")  # wrong check digit
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestExchangeSubmission(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()


	def test_blacklist_check_is_mandatory(self):
		doc = make_exchange(imei_check_done=0)
		doc.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, doc.submit)

	def test_signed_declaration_is_mandatory(self):
		doc = make_exchange(declaration_signed=None)
		doc.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, doc.submit)

	def test_submit_creates_a_margin_scheme_used_item(self):
		doc = make_exchange()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertTrue(doc.used_item_code)
		item = frappe.get_doc("Item", doc.used_item_code)
		self.assertTrue(item.a3_is_margin_scheme)
		self.assertTrue(item.a3_is_device)
		self.assertTrue(item.has_serial_no)
		self.assertEqual(item.item_group, "Used Devices")

	def test_submit_brings_the_device_into_stock(self):
		doc = make_exchange()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertTrue(doc.purchase_receipt)
		receipt = frappe.get_doc("Purchase Receipt", doc.purchase_receipt)
		self.assertEqual(receipt.docstatus, 1)
		self.assertIn("Used Devices", receipt.items[0].warehouse)
		self.assertEqual(flt(receipt.items[0].rate), flt(doc.final_exchange_value))

	def test_serial_carries_the_original_imei_and_cost(self):
		doc = make_exchange()
		imei = doc.old_imei
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertEqual(doc.used_serial_no, imei)
		serial = frappe.get_doc("Serial No", imei)
		self.assertTrue(serial.a3_is_exchanged_device)
		self.assertEqual(flt(serial.a3_purchase_cost), flt(doc.final_exchange_value))

	def test_same_imei_cannot_be_taken_in_twice(self):
		first = make_exchange()
		first.insert(ignore_permissions=True)
		first.submit()

		second = make_exchange(old_imei=first.old_imei)
		self.assertRaises(frappe.ValidationError, second.insert)

	def test_status_moves_to_accepted(self):
		doc = make_exchange()
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.status, "Valued")
		doc.submit()
		doc.reload()
		self.assertEqual(doc.status, "Accepted")


class TestMarginOnResale(FrappeTestCase):
	"""Scope 2.4: resale of an exchanged device is taxed on the margin only."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_resale_taxes_only_the_margin(self):
		from a3_retail.overrides.transactions import apply_margin_scheme

		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": frappe.db.get_value("Customer", {}, "name"),
				"items": [
					{
						"item_code": "MOB-SAM-A55-8-128-BLU",
						"qty": 1,
						"rate": 24000,
						"amount": 24000,
						"a3_is_margin_scheme": 1,
						"a3_purchase_cost": 20500,
					}
				],
			}
		)
		doc.calculate_taxes_and_totals = lambda: None
		apply_margin_scheme(doc)

		# GST applies to 3,500, not 24,000.
		self.assertEqual(flt(doc.items[0].a3_margin_value), 3500.0)
		self.assertEqual(flt(doc.items[0].net_amount), 3500.0)
