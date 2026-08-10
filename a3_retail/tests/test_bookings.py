# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Service Bookings (`/retail/bookings`) and the messages the counter is given."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import bookings, service_pos
from a3_retail.tests.fixtures import ensure_branch

PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


def luhn(prefix: str) -> str:
	"""A 15-digit IMEI the job card will accept."""
	digits = [int(d) for d in prefix]
	total = 0
	for index, digit in enumerate(reversed(digits)):
		if index % 2 == 0:
			digit *= 2
			if digit > 9:
				digit -= 9
		total += digit
	return prefix + str((10 - total % 10) % 10)


class TestBookingPages(FrappeTestCase):
	def test_both_pages_are_standalone_documents(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("bookings.html", "bookings.py", "booking.html", "booking.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		for page, script in (("bookings.html", "a3_bookings.js"), ("booking.html", "a3_booking.js")):
			markup = open(os.path.join(folder, page)).read()
			self.assertIn("<!doctype html>", markup.lower())
			self.assertNotIn("{% extends", markup)
			self.assertIn(f"/assets/a3_retail/js/{script}", markup)
			self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_the_list_carries_the_filters_a_service_desk_works_by(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "bookings.html")
		).read()
		for piece in ("Service Bookings", "New Booking", "Export", "Refresh",
		              "Booking no, customer, phone, IMEI", "Where it is", "In the shop",
		              "Ready for delivery", "Technician", "Running late", "Clear filters"):
			self.assertIn(piece, markup, piece)

	def test_service_bookings_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "_sidebar.html")
		).read()
		self.assertIn('("bookings", "Service Bookings", "/retail/bookings"', sidebar)

	def test_the_counter_is_named_service_pos(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "_sidebar.html")
		).read()
		self.assertIn('("services", "Service POS", "/retail/service"', sidebar)
		self.assertNotIn('"Services"', sidebar)

	def test_there_is_one_print_implementation(self):
		"""The list, the booking page and the counter print the same sheet."""
		body = open(frappe.get_app_path("a3_retail", "api", "bookings.py")).read()
		self.assertIn("from a3_retail.api.service_pos import estimate_url", body)
		self.assertNotIn("Job%20Card%20Acknowledgement", body, "no second print route")

		for script in ("a3_bookings.js", "a3_booking.js"):
			page = open(frappe.get_app_path("a3_retail", "public", "js", script)).read()
			self.assertIn("bookings.print_url", page, script)

	def test_the_page_writes_no_lifecycle_of_its_own(self):
		"""Money, messages and delivery stay where they already live."""
		body = open(frappe.get_app_path("a3_retail", "api", "bookings.py")).read()
		for helper in ("take_advance", "generate_invoice", "resend_otp"):
			self.assertIn(f"import {helper}", body, helper)
		self.assertNotIn("frappe.new_doc(\"Payment Entry\")", body)
		self.assertNotIn("frappe.new_doc(\"Sales Invoice\")", body)


class TestBookingsAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_list(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, bookings.list_bookings)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, bookings.bootstrap)


class TestBookingsList(FrappeTestCase):
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

	def test_the_list_starts_at_this_branch(self):
		boot = bookings.bootstrap()
		self.assertEqual(boot["branch"], "Kochi")
		self.assertIn(st.READY_FOR_DELIVERY, boot["statuses"])

		for row in bookings.list_bookings(page_size=20)["rows"]:
			self.assertEqual(row["branch"], "Kochi")

	def test_a_row_carries_every_column_the_table_shows(self):
		rows = bookings.list_bookings(page_size=5)["rows"]
		if not rows:
			self.skipTest("no bookings at this branch")
		for key in ("name", "status", "customer_name", "customer_mobile", "device", "imei_1",
		            "complaint_description", "technician_name", "estimated_delivery_date",
		            "grand_total", "advance_amount", "balance", "tone", "overdue"):
			self.assertIn(key, rows[0], key)

	def test_the_cards_and_the_table_count_the_same_bookings(self):
		cards = bookings.summary()
		listing = bookings.list_bookings(page_size=20)
		self.assertEqual(cards["total"]["count"], listing["total"])

	def test_ready_for_delivery_means_ready_for_delivery(self):
		for row in bookings.list_bookings({"status": "ready"}, page_size=20)["rows"]:
			self.assertEqual(row["status"], st.READY_FOR_DELIVERY)

	def test_the_search_looks_where_a_counter_would_look(self):
		rows = bookings.list_bookings(page_size=1)["rows"]
		if not rows:
			self.skipTest("no bookings at this branch")

		found = bookings.list_bookings({"query": rows[0]["name"]})["rows"]
		self.assertIn(rows[0]["name"], [row["name"] for row in found])

	def test_running_late_is_the_job_card_s_own_flag(self):
		for row in bookings.list_bookings({"delay": "delayed"}, page_size=20)["rows"]:
			self.assertTrue(row["overdue"], row["name"])

	def test_something_owed_means_something_owed(self):
		for row in bookings.list_bookings({"payment": "unpaid"}, page_size=20)["rows"]:
			self.assertGreater(flt(row["balance"]), 0, row["name"])

	def test_a_booking_from_another_branch_is_refused(self):
		other = frappe.db.get_value("Service Job Card", {"branch": ["!=", "Kochi"]}, "name")
		if not other:
			self.skipTest("no booking outside this branch")
		self.assertRaises(frappe.ValidationError, bookings.booking, other)

	def test_a_booking_that_does_not_exist_says_so_in_words(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			bookings.booking("JC-KCH-99-99999")
		self.assertIn("no booking numbered", str(caught.exception).lower())


class TestOneBooking(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

		rows = bookings.list_bookings(page_size=1)["rows"]
		if not rows:
			self.skipTest("no bookings at this branch")
		self.name = rows[0]["name"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_page_shows_the_device_the_work_and_the_money(self):
		card = bookings.booking(self.name)
		for key in ("customer", "device", "warranty", "parts", "labour", "totals", "payments",
		            "delivery", "activity", "can", "print_url", "counter_url"):
			self.assertIn(key, card, key)
		self.assertEqual(card["branch"], "Kochi")
		self.assertTrue(card["counter_url"].startswith("/retail/service?booking="))

	def test_the_totals_are_the_job_card_s_own(self):
		card = bookings.booking(self.name)
		doc = frappe.get_doc("Service Job Card", self.name)
		self.assertAlmostEqual(card["totals"]["grand_total"], flt(doc.grand_total), places=2)
		self.assertAlmostEqual(card["totals"]["balance"], flt(doc.outstanding_amount), places=2)

	def test_the_activity_reads_in_the_order_it_happened(self):
		events = bookings.activity(self.name)
		self.assertTrue(events)
		self.assertEqual(events[0]["kind"], "intake")
		stamps = [str(event["at"]) for event in events]
		self.assertEqual(stamps, sorted(stamps))

	def test_a_note_lands_on_the_timeline(self):
		before = len(bookings.activity(self.name))
		bookings.add_note(self.name, "Customer rang about this one.")

		events = bookings.activity(self.name)
		self.assertEqual(len(events), before + 1)
		self.assertIn("Customer rang about this one.",
		              [event["note"] for event in events if event["kind"] == "note"])

	def test_an_empty_note_is_refused_in_words(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			bookings.add_note(self.name, "   ")
		self.assertIn("write the note", str(caught.exception).lower())

	def test_money_taken_here_is_the_service_module_s_own_advance(self):
		doc = frappe.get_doc("Service Job Card", self.name)
		if flt(doc.outstanding_amount) <= 0:
			self.skipTest("nothing owed on this booking")

		result = bookings.collect(self.name, 100, "Cash")
		payment = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(payment.reference_no, self.name)
		self.assertEqual(payment.docstatus, 1)
		self.assertAlmostEqual(flt(payment.paid_amount), 100, places=2)

	def test_more_than_the_balance_is_refused_with_the_figure(self):
		doc = frappe.get_doc("Service Job Card", self.name)
		if flt(doc.outstanding_amount) <= 0:
			self.skipTest("nothing owed on this booking")

		with self.assertRaises(frappe.ValidationError) as caught:
			bookings.collect(self.name, flt(doc.outstanding_amount) + 5000, "Cash")
		self.assertIn("still owed", str(caught.exception).lower())

	def test_nothing_is_not_a_payment(self):
		self.assertRaises(frappe.ValidationError, bookings.collect, self.name, 0)


class TestTheCounterSaysWhy(FrappeTestCase):
	"""Every refusal at booking time names the problem and what to do next."""

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _payload(self, **overrides) -> dict:
		payload = {
			"mobile_no": "9847012345",
			"customer_name": "Rahul Krishnan",
			"imei_1": luhn("35933300000001"),
			"brand": "Xiaomi",
			"device_model": "Xiaomi Redmi Note 13",
			"device_type": "Mobile",
			"warranty_type": "Out of Warranty",
			"service_type": "battery",
			"complaint_description": "Battery drains in three hours.",
			"data_loss_consent": 1,
			"signature": PIXEL,
			"photos": [PIXEL],
			"items": [{"item_code": "SPR-BAT-N13", "item_name": "Battery", "kind": "Part",
			           "qty": 1, "rate": 1250}],
		}
		payload.update(overrides)
		return payload

	def _refusal(self, **overrides) -> str:
		with self.assertRaises(frappe.ValidationError) as caught:
			service_pos.save_booking(self._payload(**overrides))
		return str(caught.exception)

	def test_a_discount_is_asked_why_before_it_is_refused(self):
		message = self._refusal(discount_amount=100)
		self.assertIn("say why", message.lower())
		self.assertIn("100", message)

	def test_a_discount_with_a_reason_goes_through(self):
		result = service_pos.save_booking(self._payload(
			imei_1=luhn("35933300000002"), discount_amount=100,
			discount_reason="Regular customer"))
		self.assertEqual(
			frappe.db.get_value("Service Job Card", result["job_card"], "discount_reason"),
			"Regular customer",
		)

	def test_the_same_device_is_not_booked_in_twice(self):
		imei = luhn("35933300000003")
		first = service_pos.save_booking(self._payload(imei_1=imei))

		message = self._refusal(imei_1=imei)
		self.assertIn(first["job_card"], message)
		self.assertIn("already booked in", message.lower())

	def test_an_empty_line_is_named_by_its_number(self):
		message = self._refusal(items=[
			{"item_code": "SPR-BAT-N13", "kind": "Part", "qty": 1, "rate": 1250},
			{"item_code": "", "kind": "Service", "qty": 1, "rate": 300},
		])
		self.assertIn("line 2", message.lower())

	def test_a_part_that_is_no_longer_stocked_is_named(self):
		message = self._refusal(items=[
			{"item_code": "NO-SUCH-PART", "kind": "Part", "qty": 1, "rate": 10}])
		self.assertIn("NO-SUCH-PART", message)
		self.assertIn("catalogue", message.lower())

	def test_a_promise_already_missed_is_refused(self):
		message = self._refusal(expected_delivery=add_days(nowdate(), -3))
		self.assertIn("gone by", message.lower())

	def test_today_is_still_a_promise_that_can_be_kept(self):
		result = service_pos.save_booking(self._payload(
			imei_1=luhn("35933300000004"), expected_delivery=nowdate()))
		self.assertTrue(result["job_card"])

	def test_a_technician_from_another_branch_is_named(self):
		other = frappe.db.get_value(
			"Employee", {"branch": ["not in", ("Kochi", "")], "status": "Active"},
			["name", "employee_name", "branch"], as_dict=True)
		if not other:
			self.skipTest("no employee outside this branch")

		message = self._refusal(technician=other.name)
		self.assertIn(other.employee_name, message)
		self.assertIn(other.branch, message)

	def test_an_advance_bigger_than_the_repair_is_refused_with_both_figures(self):
		message = self._refusal(imei_1=luhn("35933300000005"), advance_amount=99999)
		self.assertIn("99,999", message)
		self.assertIn("1,475", message)  # 1250 + 18% GST

	def test_the_reasons_are_written_for_the_person_at_the_counter(self):
		"""No rule numbers, no field names, no exception classes."""
		for message in (self._refusal(discount_amount=100),
		                self._refusal(items=[{"item_code": "", "kind": "Part"}]),
		                self._refusal(expected_delivery=add_days(nowdate(), -3))):
			self.assertNotIn("ValidationError", message)
			self.assertNotIn("_", message.split(" ")[0])
			self.assertGreater(len(message.split(" ")), 6, message)


class TestTheAlertsAreVisible(FrappeTestCase):
	"""The counter's screen raises a refusal where somebody will see it."""

	def test_the_shared_client_turns_a_bare_exception_into_a_sentence(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_branch.js")).read()
		self.assertIn("ValidationError:", body)
		self.assertIn("TimestampMismatchError:", body)
		self.assertIn("function toast", body)

	def test_the_counter_raises_an_alert_and_not_only_a_line_of_red_type(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_service.js")).read()
		self.assertIn("A3.toast", body)
		self.assertIn("function stop(", body)
		self.assertIn("discount-reason", body)

	def test_the_counter_asks_for_the_discount_reason_on_the_screen(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "service.html")
		).read()
		self.assertIn('id="discount-reason"', markup)
		self.assertIn('id="discount-reason-row"', markup)

	def test_a_booking_can_be_opened_back_at_the_counter(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_service.js")).read()
		self.assertIn('params.get("booking")', body)
