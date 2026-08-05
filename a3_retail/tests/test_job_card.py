# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Service Job Card: state machine, warranty detection and totals (scope step 7)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, flt, now_datetime, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.a3_retail_service.doctype.service_job_card.service_job_card import (
	escalation_for,
	flag_delayed_job_cards,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_company

VALID_IMEI = "356938035643809"
IN_WARRANTY_IMEI = "353912104567895"


def make_job_card(**overrides):
	"""Draft job card with the mandatory intake fields filled in."""
	branch = ensure_branch("Kochi", "KCH")
	customer = frappe.db.get_value("Customer", {"a3_mobile_no": "9847012345"}, "name") or frappe.db.get_value(
		"Customer", {}, "name"
	)

	doc = frappe.new_doc("Service Job Card")
	doc.branch = branch.branch
	doc.customer = customer
	doc.device_type = "Mobile"
	doc.brand = "Samsung"
	doc.device_model = "Samsung Galaxy A55"
	doc.imei_1 = VALID_IMEI
	doc.complaint_description = "Display flickering"
	doc.repair_category = "Display"
	doc.received_on = now_datetime()
	doc.data_loss_consent = 1
	doc.customer_signature = "data:image/png;base64,iVBORw0KGgo="
	doc.device_photo_1 = "/files/test-device.jpg"
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	return doc


class TestJobCardLifecycle(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_company()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_naming_series_carries_the_branch_code(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("JC-KCH-"), doc.name)

	def test_submit_moves_draft_to_open(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, st.OPEN)

	def test_happy_path_open_to_delivered(self):
		"""Scope 3.3: the full allowed route through the state machine."""
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()

		route = [
			st.UNDER_DIAGNOSIS,
			st.ESTIMATE_PENDING,
			st.ESTIMATE_SENT,
			st.ESTIMATE_APPROVED,
			st.IN_PROGRESS,
			st.REPAIR_COMPLETED,
			st.QC_PASSED,
			st.READY_FOR_DELIVERY,
			st.DELIVERED,
		]
		for status in route:
			doc.status = status
			doc.save(ignore_permissions=True)
			self.assertEqual(doc.status, status)

		self.assertTrue(doc.delivered_on)
		self.assertTrue(doc.ready_on)

	def test_invalid_transition_is_rejected(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()

		# Open -> Delivered skips the entire repair, and must be refused.
		doc.status = st.DELIVERED
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_every_transition_is_logged(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = st.UNDER_DIAGNOSIS
		doc.save(ignore_permissions=True)
		doc.status = st.IN_PROGRESS
		doc.save(ignore_permissions=True)

		doc.reload()
		logged = [(row.from_status, row.to_status) for row in doc.status_log]
		self.assertIn((st.OPEN, st.UNDER_DIAGNOSIS), logged)
		self.assertIn((st.UNDER_DIAGNOSIS, st.IN_PROGRESS), logged)
		for row in doc.status_log:
			self.assertIsNotNone(row.duration_hours)

	def test_ready_for_delivery_generates_an_otp(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()
		for status in (st.UNDER_DIAGNOSIS, st.IN_PROGRESS, st.REPAIR_COMPLETED, st.QC_PASSED,
		               st.READY_FOR_DELIVERY):
			doc.status = status
			doc.save(ignore_permissions=True)

		self.assertRegex(doc.delivery_otp or "", r"^\d{6}$")
		self.assertFalse(doc.otp_verified)

	def test_not_repairable_zeroes_labour(self):
		doc = make_job_card()
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.status = st.UNDER_DIAGNOSIS
		doc.save(ignore_permissions=True)
		doc.status = st.NOT_REPAIRABLE
		doc.save(ignore_permissions=True)

		self.assertEqual(flt(doc.labour[0].amount), 0.0)

	def test_submitting_without_consent_is_blocked(self):
		doc = make_job_card(data_loss_consent=0, data_backup_required=0)
		doc.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, doc.submit)


class TestJobCardValidation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_mobile_without_imei_is_rejected(self):
		doc = make_job_card(imei_1=None)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_invalid_imei_is_rejected(self):
		doc = make_job_card(imei_1="353912104567891")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_earbuds_do_not_need_an_imei(self):
		doc = make_job_card(device_type="Earbuds", imei_1=None)
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name)

	def test_discount_needs_a_reason(self):
		doc = make_job_card()
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.discount_amount = 100
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_discount_cannot_exceed_the_total(self):
		doc = make_job_card()
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.discount_amount = 5000
		doc.discount_reason = "Goodwill"
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestJobCardTotals(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_parts_plus_labour_plus_gst(self):
		"""Scope 3.12 demo row: 8,400 parts + 700 labour + 18% = 10,738."""
		doc = make_job_card(warranty_type="Out of Warranty")
		doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.insert(ignore_permissions=True)

		self.assertEqual(flt(doc.parts_total), 8400.0)
		self.assertEqual(flt(doc.labour_total), 700.0)
		self.assertEqual(flt(doc.net_total), 9100.0)
		self.assertEqual(flt(doc.tax_amount), 1638.0)
		self.assertEqual(flt(doc.grand_total), 10738.0)
		self.assertEqual(flt(doc.customer_payable), 10738.0)

	def test_discount_reduces_the_taxable_base(self):
		doc = make_job_card(warranty_type="Out of Warranty")
		doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.discount_amount = 100
		doc.discount_reason = "Loyal customer"
		doc.insert(ignore_permissions=True)

		self.assertEqual(flt(doc.net_total), 9000.0)
		self.assertEqual(flt(doc.tax_amount), 1620.0)
		self.assertEqual(flt(doc.grand_total), 10620.0)

	def test_warranty_job_charges_the_customer_nothing(self):
		doc = make_job_card(warranty_type="Goodwill/Free")
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.insert(ignore_permissions=True)

		self.assertEqual(flt(doc.customer_payable), 0.0)
		self.assertEqual(flt(doc.warranty_borne_amount), flt(doc.grand_total))
		self.assertEqual(doc.payment_status, "Warranty - No Charge")

	def test_per_line_warranty_cover_is_honoured(self):
		doc = make_job_card(warranty_type="Out of Warranty")
		doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400, "is_warranty_covered": 1})
		doc.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		doc.insert(ignore_permissions=True)

		# 8,400 borne by warranty (+GST); the customer pays only the labour.
		self.assertEqual(flt(doc.warranty_borne_amount), 9912.0)
		self.assertEqual(flt(doc.customer_payable), 826.0)

	def test_customer_provided_part_is_free(self):
		doc = make_job_card(warranty_type="Out of Warranty")
		doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400, "is_customer_provided": 1})
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.parts_total), 0.0)

	def test_liquid_damage_voids_brand_warranty(self):
		doc = make_job_card(repair_category="Liquid Damage")
		doc.warranty_expiry_date = add_days(nowdate(), 90)
		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.warranty_type, "Out of Warranty")
		self.assertTrue(doc.is_chargeable)


class TestDelayFlagging(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_overdue_job_is_flagged(self):
		doc = make_job_card(received_on=add_to_date(now_datetime(), days=-10))
		doc.insert(ignore_permissions=True)
		doc.submit()

		frappe.db.set_value("Service Job Card", doc.name, "sla_due_on",
		                    add_to_date(now_datetime(), days=-5), update_modified=False)
		flag_delayed_job_cards()

		doc.reload()
		self.assertTrue(doc.is_delayed)
		self.assertGreater(flt(doc.delay_hours), 0)
		self.assertNotEqual(doc.escalation_level, "None")

	def test_on_time_job_is_not_flagged(self):
		doc = make_job_card()
		doc.insert(ignore_permissions=True)
		doc.submit()

		frappe.db.set_value("Service Job Card", doc.name, "sla_due_on",
		                    add_to_date(now_datetime(), days=5), update_modified=False)
		flag_delayed_job_cards()

		doc.reload()
		self.assertFalse(doc.is_delayed)

	def test_escalation_ladder(self):
		self.assertEqual(escalation_for(1), "None")
		self.assertEqual(escalation_for(13), "L1 - Service Manager")
		self.assertEqual(escalation_for(30), "L2 - Branch Manager")
		self.assertEqual(escalation_for(100), "L3 - Head Office")


class TestStateMachineMap(FrappeTestCase):
	def test_every_status_has_an_entry(self):
		for status in st.STATUSES:
			self.assertIn(status, st.ALLOWED, status)

	def test_terminal_states_have_no_successors(self):
		self.assertEqual(st.ALLOWED[st.CLOSED], ())
		self.assertEqual(st.ALLOWED[st.CANCELLED], ())

	def test_every_target_is_a_known_status(self):
		for source, targets in st.ALLOWED.items():
			for target in targets:
				self.assertIn(target, st.STATUSES, f"{source} -> {target}")

	def test_every_status_has_a_colour(self):
		for status in st.STATUSES:
			self.assertIn(status, st.STATUS_COLOURS, status)

	def test_can_transition_helper(self):
		self.assertTrue(st.can_transition(st.OPEN, st.UNDER_DIAGNOSIS))
		self.assertFalse(st.can_transition(st.OPEN, st.DELIVERED))
		# Saving without changing status is always allowed.
		self.assertTrue(st.can_transition(st.OPEN, st.OPEN))
