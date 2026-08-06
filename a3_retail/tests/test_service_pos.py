# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""The service counter in the branch app (`/branch/service`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import service_pos
from a3_retail.tests.fixtures import ensure_branch

# A 1×1 PNG stands in for the counter's camera and the signature pad.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


def luhn(base14: str) -> str:
	"""A 15-digit IMEI the job card will accept."""
	total = 0
	for index, char in enumerate(base14[::-1]):
		digit = int(char)
		if index % 2 == 0:
			digit *= 2
			digit = digit - 9 if digit > 9 else digit
		total += digit
	return base14 + str((10 - total % 10) % 10)


class TestServicePage(FrappeTestCase):
	def test_the_page_is_a_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("service.html", "service.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "service.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_service.js", markup)

	def test_the_three_steps_are_on_the_screen(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "service.html")
		).read()
		for step in ("Service Booking", "Invoice", "Delivery"):
			self.assertIn(step, markup, step)
		for panel in ("Customer & Device", "Service Details", "Items / Parts / Services",
		              "Billing Summary", "Service Status", "Customer Communication"):
			self.assertIn(panel, markup, panel)
		for key in ("F5", "F6", "F7"):
			self.assertIn(key, markup, key)

	def test_the_page_carries_its_assets_with_a_version(self):
		"""A counter must not be left looking at a stale stylesheet."""
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "service.html")
		).read()
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_services_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("services", "Services", "/branch/service"', sidebar)


class TestServiceAccess(FrappeTestCase):
	def test_a_guest_cannot_reach_the_counter(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, service_pos.bootstrap)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, service_pos.bootstrap)


class TestServiceCounter(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------- bootstrap
	def test_the_screen_starts_with_what_a_counter_needs(self):
		boot = service_pos.bootstrap()
		self.assertEqual(boot["branch"], "Kochi")
		self.assertEqual(len(boot["service_types"]), 6)
		self.assertTrue(boot["issues"])
		self.assertIn("Out of Warranty", boot["warranty_types"])

	def test_the_six_tiles_map_to_repair_categories_the_job_card_knows(self):
		options = frappe.get_meta("Service Job Card").get_field("repair_category").options.split("\n")
		for key, _label, category, _icon in service_pos.SERVICE_TYPES:
			self.assertIn(category, options, key)

	def test_technicians_are_this_branch_only(self):
		for row in service_pos.technicians():
			self.assertEqual(
				frappe.db.get_value("Technician Profile", {"employee": row["employee"]}, "branch"),
				"Kochi",
			)

	# ---------------------------------------------------------------- device
	def test_a_handset_we_sold_answers_with_its_own_sale(self):
		serial = frappe.db.get_value(
			"Serial No", {"item_code": "MOB-APL-15-128-BLK"}, "name", order_by="creation"
		)
		if not serial:
			self.skipTest("no seeded handsets")

		found = service_pos.device(serial)
		self.assertTrue(found["known"])
		self.assertEqual(found["imei_1"], serial)
		self.assertTrue(found["device_model"], "the counter cannot book a repair without a model")
		self.assertIn(found["warranty_type"],
		              ("Brand Warranty", "Extended Warranty", "Out of Warranty"))

	def test_a_handset_we_never_sold_still_opens_a_card(self):
		found = service_pos.device(luhn("35911100000000"))
		self.assertFalse(found["known"])
		self.assertEqual(found["warranty_type"], "Out of Warranty")

	def test_the_model_list_is_there_for_a_device_we_did_not_sell(self):
		self.assertTrue(service_pos.device_models())

	# ----------------------------------------------------------------- lines
	def test_the_line_picker_offers_parts_labour_and_accessories(self):
		kinds = {row["kind"] for row in service_pos.search_items(limit=60)}
		self.assertIn("Part", kinds)
		self.assertIn("Service", kinds)

	def test_a_line_carries_the_hsn_the_invoice_will_print(self):
		rows = service_pos.search_items(query="Battery")
		self.assertTrue(rows)
		self.assertTrue(rows[0]["hsn"])

	# -------------------------------------------------------------- intake
	def _book(self, **overrides) -> dict:
		payload = {
			"mobile_no": "9847012345",
			"customer_name": "Rahul Krishnan",
			"imei_1": luhn("35922200000001"),
			"brand": "Xiaomi",
			"device_model": "Xiaomi Redmi Note 13",
			"device_type": "Mobile",
			"warranty_type": "Out of Warranty",
			"service_type": "battery",
			"complaint_description": "Battery drains in three hours.",
			"priority": "Normal",
			"data_loss_consent": 1,
			"signature": PIXEL,
			"photos": [PIXEL],
			"items": [
				{"item_code": "SPR-BAT-N13", "item_name": "Battery", "kind": "Part",
				 "qty": 1, "rate": 1250},
				{"item_code": "SRV-LAB-L2", "item_name": "Labour", "kind": "Service",
				 "qty": 1, "rate": 600},
			],
		}
		payload.update(overrides)
		return service_pos.save_booking(payload)

	def test_a_repair_needs_the_complaint_in_the_customer_s_words(self):
		self.assertRaises(frappe.ValidationError, self._book, complaint_description="  ")

	def test_a_repair_needs_a_model(self):
		self.assertRaises(frappe.ValidationError, self._book, device_model=None)

	def test_booking_splits_parts_from_labour(self):
		result = self._book(imei_1=luhn("35922200000002"))
		card = frappe.get_doc("Service Job Card", result["job_card"])

		self.assertEqual([row.item_code for row in card.parts], ["SPR-BAT-N13"])
		self.assertEqual([row.service_item for row in card.labour], ["SRV-LAB-L2"])
		self.assertEqual(flt(card.parts_total), 1250)
		self.assertEqual(flt(card.labour_total), 600)
		self.assertEqual(card.status, "Open")

	def test_the_card_carries_the_signature_and_the_photo(self):
		result = self._book(imei_1=luhn("35922200000003"))
		card = frappe.get_doc("Service Job Card", result["job_card"])
		self.assertTrue(card.customer_signature)
		self.assertTrue(card.device_photo_1)

	def test_the_tile_becomes_the_repair_category(self):
		result = self._book(imei_1=luhn("35922200000004"), service_type="screen")
		self.assertEqual(
			frappe.db.get_value("Service Job Card", result["job_card"], "repair_category"),
			"Display",
		)

	def test_an_advance_is_taken_and_the_balance_says_what_is_left(self):
		result = self._book(imei_1=luhn("35922200000005"), advance_amount=500)
		self.assertTrue(result["payment_entry"])
		self.assertAlmostEqual(
			result["balance"], flt(result["customer_payable"]) - 500, places=2
		)

	def test_a_promised_date_becomes_the_end_of_that_day(self):
		result = self._book(imei_1=luhn("35922200000006"), expected_delivery="2030-01-31")
		self.assertIn("2030-01-31 18:00", str(result["promised"]))

	def test_the_result_hands_back_a_printable_acknowledgement(self):
		result = self._book(imei_1=luhn("35922200000007"))
		self.assertIn("download_pdf", result["print_url"])
		self.assertIn("Job%20Card%20Acknowledgement", result["print_url"])

	# ------------------------------------------------------------- billing
	def test_the_service_invoice_carries_gst(self):
		"""The card quotes a figure with tax on it; the invoice must match."""
		booked = self._book(imei_1=luhn("35922200000008"))
		result = service_pos.generate_invoice(booked["job_card"])

		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertGreater(flt(invoice.total_taxes_and_charges), 0)
		self.assertEqual(flt(invoice.net_total), 1850)

	def test_the_invoice_posts_to_the_branch_cost_center(self):
		booked = self._book(imei_1=luhn("35922200000009"))
		result = service_pos.generate_invoice(booked["job_card"])
		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])

		centers = {row.cost_center for row in invoice.items} | {
			row.cost_center for row in invoice.taxes
		}
		self.assertTrue(centers)
		for center in centers:
			self.assertIn("Kochi", center)

	def test_the_counter_can_read_back_the_invoice_it_raised(self):
		"""Strict user permissions make an unstamped cost center unreadable."""
		booked = self._book(imei_1=luhn("35922200000010"))
		result = service_pos.generate_invoice(booked["job_card"])
		self.assertTrue(frappe.has_permission("Sales Invoice", "read", result["sales_invoice"]))

	# ------------------------------------------------------------ delivery
	def test_a_repair_that_is_not_ready_cannot_be_handed_over(self):
		booked = self._book(imei_1=luhn("35922200000011"))
		self.assertRaises(
			frappe.ValidationError, service_pos.mark_delivered, booked["job_card"], "000000"
		)

	def test_a_card_from_another_branch_is_refused(self):
		other = frappe.db.get_value(
			"Service Job Card", {"branch": ["!=", "Kochi"], "docstatus": 1}, "name"
		)
		if not other:
			self.skipTest("no job card outside Kochi")
		self.assertRaises(frappe.ValidationError, service_pos.booking, other)

	# --------------------------------------------------------- reloading
	def test_a_card_reloads_into_the_screen_with_its_lines(self):
		booked = self._book(imei_1=luhn("35922200000012"))
		card = service_pos.booking(booked["job_card"])

		self.assertEqual(card["job_card"], booked["job_card"])
		kinds = {line["kind"] for line in card["items"]}
		self.assertEqual(kinds, {"Part", "Service"})

	def test_scanning_a_job_card_number_reopens_it(self):
		booked = self._book(imei_1=luhn("35922200000013"))
		found = service_pos.device(booked["job_card"])
		self.assertEqual(found["job_card"], booked["job_card"])

	def test_recent_bookings_are_this_branch_only(self):
		self._book(imei_1=luhn("35922200000014"))
		rows = service_pos.recent_bookings()
		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(
				frappe.db.get_value("Service Job Card", row["name"], "branch"), "Kochi"
			)


class TestCounterPermissions(FrappeTestCase):
	"""What the counter must be able to do, and what stays closed to it."""

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_counter_can_take_an_advance(self):
		self.assertTrue(frappe.has_permission("Payment Entry", "create"))

	def test_the_counter_can_open_a_job_card(self):
		self.assertTrue(frappe.has_permission("Service Job Card", "create"))

	def test_the_ledger_stays_closed(self):
		"""A manager may look at a journal; nobody at a counter writes one."""
		self.assertFalse(frappe.has_permission("GL Entry", "read"))
		self.assertFalse(frappe.has_permission("Journal Entry", "create"))
		self.assertFalse(frappe.has_permission("Account", "read"))
