# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Advances, service invoicing and OTP delivery (scope step 9, section 3.5)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api.service import (
	create_job_card,
	dashboard_counters,
	deliver_job_card,
	take_advance,
)
from a3_retail.tests.fixtures import ensure_branch
from a3_retail.tests.test_job_card import make_job_card


def ready_job_card(with_labour=True):
	"""A submitted job card walked all the way to Ready for Delivery."""
	doc = make_job_card(warranty_type="Out of Warranty")
	if with_labour:
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
	doc.insert(ignore_permissions=True)
	doc.submit()

	for status in (st.UNDER_DIAGNOSIS, st.IN_PROGRESS, st.REPAIR_COMPLETED, st.QC_PASSED,
	               st.READY_FOR_DELIVERY):
		doc.status = status
		doc.save(ignore_permissions=True)

	doc.reload()
	return doc


class TestAdvances(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_advance_creates_a_submitted_payment_entry(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()

		result = take_advance(doc.name, 2000, "Cash")
		payment = frappe.get_doc("Payment Entry", result["payment_entry"])

		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(payment.payment_type, "Receive")
		self.assertEqual(flt(payment.paid_amount), 2000.0)
		self.assertEqual(payment.party, doc.customer)

	def test_advance_is_stamped_on_the_job_card(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		take_advance(doc.name, 2000, "Cash")

		doc.reload()
		self.assertEqual(flt(doc.advance_amount), 2000.0)
		self.assertTrue(doc.advance_payment_entry)
		self.assertEqual(doc.payment_status, "Partly Paid (Advance)")

	def test_payment_entry_links_back_to_the_job_card(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		result = take_advance(doc.name, 500, "Cash")

		linked = frappe.db.get_value("Payment Entry", result["payment_entry"], "a3_service_job_card")
		self.assertEqual(linked, doc.name)

	def test_payment_entry_carries_the_branch_dimension(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		result = take_advance(doc.name, 500, "Cash")

		self.assertEqual(frappe.db.get_value("Payment Entry", result["payment_entry"], "branch"), "Kochi")

	def test_two_advances_accumulate(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		take_advance(doc.name, 1000, "Cash")
		take_advance(doc.name, 500, "Cash")

		doc.reload()
		self.assertEqual(flt(doc.advance_amount), 1500.0)

	def test_zero_advance_is_rejected(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertRaises(frappe.ValidationError, take_advance, doc.name, 0, "Cash")


class TestDelivery(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_otp_mismatch_blocks_delivery(self):
		doc = ready_job_card()
		self.assertRaises(
			frappe.ValidationError, deliver_job_card, doc.name, "000000", "Rahul", None, 1
		)
		doc.reload()
		self.assertEqual(doc.status, st.READY_FOR_DELIVERY)

	def test_correct_otp_delivers(self):
		doc = ready_job_card()
		result = deliver_job_card(doc.name, doc.delivery_otp, receiver="Rahul Krishnan",
		                          accessories_returned=1)

		self.assertEqual(result["status"], st.DELIVERED)
		doc.reload()
		self.assertTrue(doc.otp_verified)
		self.assertTrue(doc.delivered_on)
		self.assertEqual(doc.receiver_name, "Rahul Krishnan")

	def test_accessories_not_returned_blocks_delivery(self):
		doc = ready_job_card()
		self.assertRaises(
			frappe.ValidationError,
			deliver_job_card, doc.name, doc.delivery_otp, "Rahul", None, 0,
		)

	def test_delivery_before_ready_is_blocked(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertRaises(frappe.ValidationError, deliver_job_card, doc.name, "123456")

	def test_delivery_collects_the_balance(self):
		doc = ready_job_card()
		result = deliver_job_card(
			doc.name, doc.delivery_otp, receiver="Rahul", accessories_returned=1,
			collect_amount=826, mode_of_payment="Cash",
		)
		self.assertTrue(result["payment_entry"])

		payment = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(flt(payment.paid_amount), 826.0)

	def test_serial_service_counters_increment_on_delivery(self):
		serial_name = "356938035643809"
		if not frappe.db.exists("Serial No", serial_name):
			serial = frappe.new_doc("Serial No")
			serial.item_code = "MOB-SAM-A55-8-128-BLU"
			serial.a3_imei_1 = serial_name
			serial.flags.ignore_permissions = True
			serial.insert(ignore_permissions=True)

		before = frappe.db.get_value("Serial No", serial_name, "a3_service_count") or 0

		doc = ready_job_card()
		deliver_job_card(doc.name, doc.delivery_otp, receiver="Rahul", accessories_returned=1)

		after = frappe.db.get_value("Serial No", serial_name, "a3_service_count") or 0
		self.assertEqual(after, before + 1)


class TestReceptionApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_create_job_card_from_payload(self):
		result = create_job_card(
			{
				"branch": "Kochi",
				"mobile_no": "9847012345",
				"customer_name": "Rahul Krishnan",
				"device_type": "Mobile",
				"brand": "Samsung",
				"device_model": "Samsung Galaxy A55",
				"imei_1": "356938035643809",
				"complaint_description": "Display flickering",
				"repair_category": "Display",
				"data_loss_consent": 1,
				"customer_signature": "data:image/png;base64,iVBORw0KGgo=",
				"device_photo_1": "/files/x.jpg",
				"accessories": [{"accessory": "Charger", "received": 1, "condition": "Good"}],
			}
		)

		self.assertTrue(result["job_card"].startswith("JC-KCH-"))
		doc = frappe.get_doc("Service Job Card", result["job_card"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.status, st.OPEN)
		self.assertEqual(len(doc.device_condition_checklist), 1)

	def test_create_job_card_with_advance(self):
		result = create_job_card(
			{
				"branch": "Kochi",
				"mobile_no": "9847012345",
				"customer_name": "Rahul Krishnan",
				"brand": "Samsung",
				"device_model": "Samsung Galaxy A55",
				"imei_1": "356938035643809",
				"complaint_description": "Battery drains",
				"data_loss_consent": 1,
				"customer_signature": "sig",
				"device_photo_1": "/files/x.jpg",
				"advance_amount": 1000,
				"advance_mode": "Cash",
			}
		)
		self.assertTrue(result.get("payment_entry"))

	def test_dashboard_counters_shape(self):
		counters = dashboard_counters("Kochi")
		for key in ("today_in", "delivered_today", "pending", "ready", "delayed"):
			self.assertIn(key, counters)
			self.assertIsInstance(counters[key], int)

	def test_lookup_customer_returns_profile(self):
		from a3_retail.api.service import lookup_customer

		result = lookup_customer("9847012345")
		self.assertEqual(result.get("mobile_no"), "9847012345")
		self.assertIn("past_jobs", result)

	def test_lookup_unknown_mobile(self):
		from a3_retail.api.service import lookup_customer

		result = lookup_customer("9000000001")
		self.assertFalse(result.get("found", False))
