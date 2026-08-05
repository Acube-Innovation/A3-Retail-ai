# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Warranty registrations, plans and claims (scope step 16, doc 05)."""

import itertools

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, flt, getdate, nowdate

from a3_retail.a3_retail_warranty.doctype.warranty_registration.warranty_registration import (
	ACTIVE,
	EXPIRED,
	EXPIRING_SOON,
	FULLY_CLAIMED,
	VOID,
	attach_plan,
	check,
	hash_token,
	recompute_statuses,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_customer, ensure_sales_invoice
from a3_retail.utils.imei import luhn_check_digit

_counter = itertools.count(1)


def next_imei() -> str:
	prefix = f"35693803564{next(_counter):03d}"[:14].ljust(14, "0")
	return prefix + str(luhn_check_digit(prefix))


def make_serial(imei: str, item_code: str = "MOB-SAM-A55-8-128-BLU") -> str:
	if frappe.db.exists("Serial No", imei):
		return imei
	doc = frappe.new_doc("Serial No")
	doc.item_code = item_code
	doc.a3_imei_1 = imei
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def make_registration(**overrides):
	branch = ensure_branch("Kochi", "KCH")
	customer = ensure_customer()
	imei = overrides.pop("imei", next_imei())
	serial = make_serial(imei)

	doc = frappe.new_doc("Warranty Registration")
	doc.customer = customer
	doc.branch = branch.branch
	doc.serial_no = serial
	doc.sales_invoice = overrides.pop("sales_invoice", None) or _dummy_invoice_name()
	doc.purchase_date = overrides.pop("purchase_date", nowdate())
	doc.device_value = overrides.pop("device_value", 39999)
	doc.brand_warranty_months = overrides.pop("brand_warranty_months", 12)
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	return doc


def _dummy_invoice_name():
	"""A registration always comes from a sale, so tests need a real invoice."""
	return ensure_sales_invoice()


class TestPlanMasters(FrappeTestCase):
	def test_four_plans_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Extended Warranty Plan"), 4)

	def test_screen_plan_covers_only_the_display(self):
		components = frappe.get_all(
			"Warranty Coverage Item",
			filters={"parent": "Screen Protect 12M", "is_covered": 1},
			pluck="component",
		)
		self.assertEqual(components, ["Display"])

	def test_incentive_fields_are_permlevel_gated(self):
		meta = frappe.get_meta("Extended Warranty Plan")
		for fieldname in ("technician_incentive", "sales_incentive"):
			self.assertEqual(meta.get_field(fieldname).permlevel, 1, fieldname)


class TestRegistrationDates(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_brand_warranty_expiry_is_purchase_plus_months(self):
		doc = make_registration(purchase_date="2026-04-12", brand_warranty_months=12)
		doc.insert(ignore_permissions=True)
		self.assertEqual(str(doc.brand_warranty_expiry), "2027-04-12")

	def test_plan_starting_at_purchase(self):
		doc = make_registration(purchase_date="2026-05-20", ew_plan="EW + Screen Combo 24M")
		doc.insert(ignore_permissions=True)

		self.assertEqual(str(doc.ew_start_date), "2026-05-20")
		self.assertEqual(str(doc.ew_expiry_date), "2028-05-20")

	def test_plan_starting_after_brand_warranty(self):
		doc = make_registration(purchase_date="2026-04-12", ew_plan="EW 12 Months Standard")
		doc.insert(ignore_permissions=True)

		# Brand cover ends 2027-04-12, so the plan runs from the next day.
		self.assertEqual(str(doc.ew_start_date), "2027-04-13")
		self.assertEqual(str(doc.ew_expiry_date), "2028-04-13")

	def test_waiting_period_delays_the_start(self):
		doc = make_registration(purchase_date="2026-06-15", ew_plan="Screen Protect 12M")
		doc.insert(ignore_permissions=True)
		# 15-day waiting period on screen plans.
		self.assertEqual(str(doc.ew_start_date), "2026-06-30")

	def test_claim_cap_is_a_percentage_of_device_value(self):
		doc = make_registration(ew_plan="EW 12 Months Standard", device_value=39999)
		doc.insert(ignore_permissions=True)
		# 80% cap.
		self.assertEqual(flt(doc.claim_value_cap), round(39999 * 0.8, 2))
		self.assertEqual(doc.max_claims, 2)


class TestRegistrationStatus(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_fresh_registration_is_active(self):
		doc = make_registration()
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.status, ACTIVE)

	def test_expiring_within_thirty_days(self):
		doc = make_registration(
			purchase_date=add_months(nowdate(), -12), brand_warranty_months=12
		)
		doc.insert(ignore_permissions=True)
		self.assertIn(doc.status, (EXPIRING_SOON, EXPIRED))

	def test_past_expiry_is_expired(self):
		doc = make_registration(purchase_date="2020-01-01", brand_warranty_months=12)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.status, EXPIRED)

	def test_effective_expiry_is_the_later_cover(self):
		doc = make_registration(purchase_date=nowdate(), ew_plan="EW + Screen Combo 24M")
		doc.insert(ignore_permissions=True)
		self.assertEqual(getdate(doc.effective_expiry()), getdate(doc.ew_expiry_date))

	def test_scheduler_recomputes_statuses(self):
		doc = make_registration()
		doc.insert(ignore_permissions=True)
		doc.submit()

		frappe.db.set_value("Warranty Registration", doc.name, "brand_warranty_expiry",
		                    add_days(nowdate(), -1))
		recompute_statuses()
		self.assertEqual(frappe.db.get_value("Warranty Registration", doc.name, "status"), EXPIRED)


class TestClaims(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _plan_registration(self, plan="EW 12 Months Standard"):
		doc = make_registration(purchase_date=nowdate(), ew_plan=plan, device_value=39999)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc

	def test_covered_component_passes(self):
		doc = self._plan_registration()
		self.assertTrue(doc.covers("Display"))

	def test_uncovered_component_is_refused(self):
		doc = self._plan_registration(plan="Screen Protect 12M")
		self.assertFalse(doc.covers("Battery"))
		self.assertRaises(frappe.ValidationError, doc.check_claim, 1000, "Battery")

	def test_claim_within_cap_is_allowed(self):
		doc = self._plan_registration()
		doc.check_claim(5000, "Display")  # must not raise

	def test_claim_beyond_cap_is_refused(self):
		doc = self._plan_registration()
		self.assertRaises(frappe.ValidationError, doc.check_claim, 999999, "Display")

	def test_recording_a_claim_increments_usage(self):
		doc = self._plan_registration()
		job = frappe.db.get_value("Service Job Card", {"docstatus": 1}, "name")
		doc.record_claim(job, 5000)

		doc.reload()
		self.assertEqual(doc.claims_used, 1)
		self.assertEqual(flt(doc.claim_value_used), 5000.0)
		self.assertEqual(len(doc.claims), 1)

	def test_exhausting_claims_marks_fully_claimed(self):
		doc = self._plan_registration(plan="Screen Protect 12M")  # max 1 claim
		job = frappe.db.get_value("Service Job Card", {"docstatus": 1}, "name")
		doc.record_claim(job, 1000)

		doc.reload()
		self.assertEqual(doc.status, FULLY_CLAIMED)
		self.assertRaises(frappe.ValidationError, doc.check_claim, 500, "Display")

	def test_void_registration_refuses_claims(self):
		doc = self._plan_registration()
		doc.db_set("status", VOID, update_modified=False)
		doc.db_set("void_reason", "Third-party Repair", update_modified=False)
		doc.reload()
		self.assertRaises(frappe.ValidationError, doc.check_claim, 100, "Display")


class TestCertificateAndSerial(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_submit_issues_a_hashed_certificate_token(self):
		doc = make_registration()
		doc.insert(ignore_permissions=True)
		doc.submit()

		token = doc.flags.certificate_token
		doc.reload()
		self.assertTrue(token)
		self.assertEqual(doc.certificate_token_hash, hash_token(token))
		self.assertIn(token, doc.certificate_url)
		self.assertEqual(doc.certificate_no, doc.name)

	def test_submit_stamps_the_serial(self):
		doc = make_registration(purchase_date=nowdate(), ew_plan="EW + Screen Combo 24M")
		doc.insert(ignore_permissions=True)
		doc.submit()

		serial = frappe.get_doc("Serial No", doc.serial_no)
		self.assertEqual(serial.a3_ew_registration, doc.name)
		self.assertEqual(str(serial.a3_ew_expiry), str(doc.ew_expiry_date))

	def test_attach_plan_within_the_window(self):
		doc = make_registration(purchase_date=nowdate())
		doc.insert(ignore_permissions=True)
		doc.submit()

		attach_plan(doc.serial_no, "EW 12 Months Standard")
		doc.reload()
		self.assertEqual(doc.ew_plan, "EW 12 Months Standard")

	def test_attach_plan_outside_the_window_is_refused(self):
		doc = make_registration(purchase_date=add_days(nowdate(), -60))
		doc.insert(ignore_permissions=True)
		doc.submit()

		self.assertRaises(
			frappe.ValidationError, attach_plan, doc.serial_no, "Screen Protect 12M"
		)

	def test_attaching_twice_is_refused(self):
		doc = make_registration(purchase_date=nowdate(), ew_plan="EW 12 Months Standard")
		doc.insert(ignore_permissions=True)
		doc.submit()

		self.assertRaises(
			frappe.ValidationError, attach_plan, doc.serial_no, "Screen Protect 12M"
		)


class TestWarrantyCheckApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_unknown_imei_reports_not_found(self):
		result = check("999999999999999")
		self.assertFalse(result["found"])

	def test_known_device_returns_the_contract_shape(self):
		doc = make_registration(purchase_date=nowdate(), ew_plan="EW + Screen Combo 24M")
		doc.insert(ignore_permissions=True)
		doc.submit()

		result = check(doc.imei_1)
		self.assertTrue(result["found"])
		for key in ("imei", "item_code", "device", "brand_warranty_expiry", "extended_warranty",
		            "state", "service_history"):
			self.assertIn(key, result)

		self.assertEqual(result["extended_warranty"]["plan"], "EW + Screen Combo 24M")
		self.assertEqual(result["extended_warranty"]["max_claims"], 3)


class TestOEMReturns(FrappeTestCase):
	def _make_return(self, **overrides):
		doc = frappe.new_doc("OEM Warranty Return")
		doc.supplier = frappe.db.get_value("Supplier", {}, "name")
		doc.branch = "Kochi"
		doc.return_type = "Defective Part Return"
		doc.dispatch_date = nowdate()
		doc.append("items", {"item_code": "SPR-DSP-A55", "qty": 2, "claim_value": 16800})
		doc.update(overrides)
		doc.flags.ignore_permissions = True
		return doc

	def test_total_is_summed_from_rows(self):
		doc = self._make_return()
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.total_claim_value), 16800.0)

	def test_credit_above_claim_is_rejected(self):
		doc = self._make_return()
		doc.credit_amount = 20000
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_full_credit_marks_credit_received(self):
		doc = self._make_return()
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.credit_amount = 16800
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.status, "Credit Received")

	def test_partial_credit_marks_partially_credited(self):
		doc = self._make_return()
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.credit_amount = 8400
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.status, "Partially Credited")

	def test_submit_sets_dispatched(self):
		doc = self._make_return()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, "Dispatched")
