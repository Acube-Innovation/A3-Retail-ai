# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The service bill, in the shape of the pad the counter has used for years.

The shop asked for its own printed service bill rather than something in the
house style: the same fields in the same order, the same three lines of what
it does, the same two signatures, and the same five terms in Malayalam with an
English reading under each.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


def _template() -> str:
	return open(frappe.get_app_path("a3_retail", "templates", "print_formats",
	                                "job_card_acknowledgement.html"),
	            encoding="utf-8").read()


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


class TestTheFieldsOnThePad(FrappeTestCase):
	def test_every_line_of_the_pad_is_on_the_bill(self):
		body = _template()
		for label in ("Name", "Place", "Contact No", "Company Name", "Model No",
		              "Symptom", "IMEI/Sl. No", "Battery", "Sim Tray",
		              "Customer No", "Advance", "We Provided", "Pattern, Password",
		              "Risk Informed", "Work Order No.",
		              "Nature of complaint as reported by Customer"):
			self.assertIn(label, body, f"the pad's {label!r} line is missing")

	def test_the_three_lines_of_what_the_shop_does(self):
		body = _template()
		for line in ("Mobile Phone servicing (Both Hardware &amp; Software) Glass works",
		             "Chiplevel Servicing, Display Replacing, Battery Replacing",
		             "Liquid Damage Repairing, Official Country Unlocking, Software Solution"):
			self.assertIn(line, body)

	def test_both_signatures_and_the_declaration(self):
		body = _template()
		self.assertIn("Received by", body)
		self.assertEqual(body.count("Customer's Signature"), 2)
		self.assertIn("I have received the equipment in satisfactory working conditions", body)

	def test_the_bill_number_is_bold_and_red(self):
		body = _template()
		rule = body[body.index(".sb-no {"):]
		rule = rule[:rule.index("}")]
		self.assertIn("#d81f26", rule)
		self.assertIn("font-weight: 800", rule)
		self.assertIn('<span class="sb-no">{{ doc.name }}</span>', body)


class TestTheTerms(FrappeTestCase):
	def test_five_terms_in_both_languages(self):
		from a3_retail.print_helpers import a3_service_terms

		terms = a3_service_terms()
		self.assertEqual(len(terms), 5)
		for malayalam, english in terms:
			self.assertTrue(malayalam.strip(), "a term has no Malayalam")
			self.assertTrue(english.strip(), "a term has no English")
			# Malayalam occupies U+0D00–U+0D7F; this is what tells the two apart
			# rather than trusting the order they were written in.
			self.assertTrue(any("ഀ" <= ch <= "ൿ" for ch in malayalam))
			self.assertFalse(any("ഀ" <= ch <= "ൿ" for ch in english))

	def test_the_english_sits_under_the_malayalam(self):
		body = _template()
		block = body[body.index("{% for ml, en in a3_service_terms(doc) %}"):]
		block = block[:block.index("{% endfor %}")]
		self.assertLess(block.index('class="sb-ml"'), block.index('class="sb-en"'))

	def test_a_malayalam_font_is_named(self):
		"""Without one the terms print as empty boxes."""
		body = _template()
		self.assertIn("Noto Sans Malayalam", body)


class TestWhereTheHeadingComesFrom(FrappeTestCase):
	def test_the_head_is_the_branch_s_own(self):
		"""So a second service counter prints its own name and number, not
		Parassala's."""
		body = _template()
		self.assertIn("a3_branch_profile(doc.get(\"branch\"))", body)
		self.assertIn("profile.get(\"service_tagline\")", body)
		self.assertNotIn("Karakonam Road", body)
		self.assertNotIn("9447929607", body)

	def test_the_branch_profile_carries_a_tagline(self):
		self.assertTrue(frappe.get_meta("Branch Profile").has_field("service_tagline"))

	def test_the_helper_hands_the_tagline_over(self):
		self.assertIn('"service_tagline"', _source("print_helpers.py"))


class TestNamePlaceAndNumber(FrappeTestCase):
	def test_name_and_number_are_mandatory_on_the_card(self):
		meta = frappe.get_meta("Service Job Card")
		self.assertTrue(meta.get_field("customer_name").reqd)
		self.assertTrue(meta.get_field("customer_mobile").reqd)

	def test_place_is_asked_for_when_booking_in(self):
		"""Not on the doctype — cards booked before this existed have no place
		and must still be able to move through their own statuses."""
		meta = frappe.get_meta("Service Job Card")
		self.assertTrue(meta.has_field("place"))
		self.assertFalse(meta.get_field("place").reqd)

		booking = _source("api", "service_pos.py")
		self.assertIn('place = (data.get("place") or "").strip()', booking)
		self.assertIn("Place needed", booking)

	def test_an_older_card_without_a_place_still_saves(self):
		card = frappe.db.sql("""select name from `tabService Job Card`
		                        where ifnull(place,'') = '' limit 1""")
		if not card:
			self.skipTest("every card on this site carries a place")
		doc = frappe.get_doc("Service Job Card", card[0][0])
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)   # rolled back by the test runner

	def test_the_counter_is_asked_before_the_save_goes_out(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_service.js"),
		            encoding="utf-8").read()
		self.assertIn('$("svc-place")', body)
		self.assertIn("The service bill asks for a place.", body)
		self.assertIn('place: $("svc-place")', body)

	def test_the_box_is_on_the_booking_screen(self):
		page = open(frappe.get_app_path("a3_retail", "www", "retail", "service.html"),
		            encoding="utf-8").read()
		self.assertIn('id="svc-place"', page)


class TestTheBillRenders(FrappeTestCase):
	def test_a_real_card_fills_the_pad(self):
		from a3_retail.print_helpers import (a3_branch_profile, a3_received_by,
		                                     a3_reported_issues)

		card = frappe.db.get_value("Service Job Card", {"docstatus": ["<", 2]}, "name")
		if not card:
			self.skipTest("no job card on this site")
		doc = frappe.get_doc("Service Job Card", card)

		self.assertTrue(doc.customer_name)
		self.assertTrue(doc.customer_mobile)
		# The helpers the pad calls must answer for a real card rather than throw.
		self.assertIsInstance(a3_received_by(doc), str)
		self.assertIsInstance(a3_reported_issues(doc), str)
		self.assertIsInstance(a3_branch_profile(doc.branch), dict)

	def test_the_format_is_registered_at_a_full_sheet(self):
		setup = _source("setup", "print_formats.py")
		self.assertIn('"job_card_acknowledgement", "A4"', setup)
