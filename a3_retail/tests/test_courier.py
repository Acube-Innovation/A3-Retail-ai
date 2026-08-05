# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Courier dispatch, freight and delay tracking (scope step 19, doc 07)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from a3_retail.a3_retail_operations.doctype.courier_dispatch.courier_dispatch import (
	DELIVERED,
	IN_TRANSIT,
	LOST,
	scan_delayed_dispatches,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_customer


def make_dispatch(**overrides):
	ensure_branch("Kochi", "KCH")
	doc = frappe.new_doc("Courier Dispatch")
	doc.dispatch_type = overrides.pop("dispatch_type", "Sales Delivery")
	doc.branch = "Kochi"
	doc.courier_partner = overrides.pop("courier_partner", "Blue Dart Express")
	doc.service_type = overrides.pop("service_type", "Air")
	doc.awb_no = overrides.pop("awb_no", f"BD{frappe.generate_hash(length=8).upper()}")
	doc.consignee_type = "Customer"
	doc.consignee = ensure_customer()
	doc.pincode = overrides.pop("pincode", "682030")
	doc.zone = overrides.pop("zone", "Within State")
	doc.dispatch_date = overrides.pop("dispatch_date", now_datetime())
	doc.weight_kg = overrides.pop("weight_kg", 0.4)
	doc.declared_value = overrides.pop("declared_value", 39999)
	items = overrides.pop("items", [{"description": "Galaxy A55", "qty": 1, "value": 39999}])
	doc.update(overrides)
	for row in items:
		doc.append("items", row)
	doc.flags.ignore_permissions = True
	return doc


class TestCourierPartners(FrappeTestCase):
	def test_five_partners_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Courier Partner"), 5)

	def test_rate_cards_are_present(self):
		rows = frappe.get_all("Courier Rate Card", filters={"parent": "Blue Dart Express"})
		self.assertTrue(rows)

	def test_own_rider_is_free(self):
		rate = frappe.db.get_value(
			"Courier Rate Card", {"parent": "Own Rider"}, "base_rate"
		)
		self.assertEqual(flt(rate), 0.0)


class TestFreightComputation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_within_slab_uses_the_base_rate(self):
		doc = make_dispatch(weight_kg=0.4)
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.freight_amount), 80.0)

	def test_overweight_adds_per_500g(self):
		doc = make_dispatch(weight_kg=1.4)
		doc.insert(ignore_permissions=True)
		# 0.5 kg slab at 80, plus 0.9 kg over => 2 units of 40.
		self.assertEqual(flt(doc.freight_amount), 160.0)

	def test_fuel_surcharge_and_gst_are_added(self):
		doc = make_dispatch(weight_kg=0.4)
		doc.insert(ignore_permissions=True)

		self.assertEqual(flt(doc.fuel_surcharge), 8.0)
		taxable = flt(doc.freight_amount) + flt(doc.fuel_surcharge)
		self.assertEqual(flt(doc.gst_amount), round(taxable * 0.18, 2))
		self.assertEqual(flt(doc.total_cost), round(taxable * 1.18, 2))

	def test_own_rider_costs_nothing(self):
		doc = make_dispatch(courier_partner="Own Rider", service_type="Same Day", weight_kg=1)
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.total_cost), 0.0)

	def test_explicit_freight_is_not_overwritten(self):
		doc = make_dispatch(freight_amount=250)
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.freight_amount), 250.0)


class TestZoneDerivation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _zone_for(self, pincode):
		doc = make_dispatch(pincode=pincode, zone=None)
		doc.derive_zone()
		return doc.zone

	def test_kerala_pincode_is_within_state(self):
		self.assertEqual(self._zone_for("682030"), "Within State")

	def test_metro_pincode(self):
		self.assertEqual(self._zone_for("560001"), "Metro")

	def test_far_pincode_is_rest_of_india(self):
		self.assertEqual(self._zone_for("302001"), "Rest of India")

	def test_explicit_zone_is_respected(self):
		doc = make_dispatch(zone="Metro", pincode="682030")
		doc.derive_zone()
		self.assertEqual(doc.zone, "Metro")


class TestDispatchLifecycle(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_expected_delivery_uses_the_partner_tat(self):
		doc = make_dispatch(dispatch_date=nowdate())
		doc.insert(ignore_permissions=True)
		self.assertEqual(getdate(doc.expected_delivery_date), getdate(add_days(nowdate(), 2)))

	def test_tracking_url_is_built_from_the_pattern(self):
		doc = make_dispatch(awb_no="BD778812345")
		doc.insert(ignore_permissions=True)
		self.assertIn("BD778812345", doc.tracking_url)
		self.assertTrue(doc.tracking_url.startswith("https://"))

	def test_consignee_details_are_pulled_from_the_customer(self):
		doc = make_dispatch()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.consignee_name)
		self.assertTrue(doc.consignee_mobile)

	def test_submit_without_an_awb_is_blocked(self):
		doc = make_dispatch(awb_no=None)
		doc.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, doc.submit)

	def test_own_rider_needs_no_awb(self):
		doc = make_dispatch(courier_partner="Own Rider", service_type="Same Day", awb_no=None)
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_on_time_delivery_has_no_delay(self):
		doc = make_dispatch()
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = DELIVERED
		doc.actual_delivery_date = now_datetime()
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.delay_days, 0)

	def test_late_delivery_records_the_delay(self):
		doc = make_dispatch(dispatch_date=add_days(nowdate(), -10))
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = DELIVERED
		doc.actual_delivery_date = now_datetime()
		doc.save(ignore_permissions=True)
		# Promised at dispatch + 2 days, delivered today => 8 days late.
		self.assertEqual(doc.delay_days, 8)


class TestDelayScanner(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_overdue_dispatch_is_flagged(self):
		doc = make_dispatch(dispatch_date=add_days(nowdate(), -10))
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.status = IN_TRANSIT
		doc.save(ignore_permissions=True)

		result = scan_delayed_dispatches()
		self.assertGreaterEqual(result["delayed"], 1)

		doc.reload()
		self.assertGreater(doc.delay_days, 0)

	def test_on_time_dispatch_is_not_flagged(self):
		doc = make_dispatch()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.status = IN_TRANSIT
		doc.save(ignore_permissions=True)

		scan_delayed_dispatches()
		doc.reload()
		self.assertEqual(doc.delay_days, 0)


class TestDispatchSideEffects(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_delivered_service_return_closes_the_job_card(self):
		from a3_retail.a3_retail_service.doctype.service_job_card import state as st
		from a3_retail.tests.test_service_flow import ready_job_card

		job = ready_job_card()
		doc = make_dispatch(
			dispatch_type="Service Device Return",
			reference_type="Service Job Card",
			reference_name=job.name,
		)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = DELIVERED
		doc.actual_delivery_date = now_datetime()
		doc.received_by = "Rahul Krishnan"
		doc.save(ignore_permissions=True)

		job.reload()
		self.assertEqual(job.status, st.DELIVERED)

	def test_lost_parcel_raises_a_damage_report(self):
		doc = make_dispatch(items=[{"item_code": "ACC-TGL-A55", "qty": 1, "value": 299}])
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = LOST
		doc.save(ignore_permissions=True)

		report = frappe.db.get_value(
			"Stock Damage Report",
			{"remarks": ["like", f"%{doc.name}%"]},
			["name", "responsibility", "recovery_mode"],
			as_dict=True,
		)
		self.assertTrue(report, "no damage report was raised for the lost parcel")
		self.assertEqual(report.responsibility, "Courier / Transporter")
		self.assertEqual(report.recovery_mode, "Courier Claim")


class TestDeliveryTripFields(FrappeTestCase):
	def test_trip_custom_fields_exist(self):
		meta = frappe.get_meta("Delivery Trip")
		for fieldname in ("a3_branch", "a3_trip_type", "a3_cod_collected", "a3_cod_deposited"):
			self.assertTrue(meta.has_field(fieldname), fieldname)

	def test_stop_custom_fields_exist(self):
		meta = frappe.get_meta("Delivery Stop")
		for fieldname in ("a3_job_card", "a3_otp", "a3_signature", "a3_failure_reason"):
			self.assertTrue(meta.has_field(fieldname), fieldname)
