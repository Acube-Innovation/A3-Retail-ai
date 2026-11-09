# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Ten things the shop asked for, and the rules that keep them true.

Each of these started as a counter not being able to finish a job: a customer
from the next state who could not be billed at all, a Print button that opened
a tab instead of the printer, an Edit form that quietly wiped the address it
was supposed to be showing. What is held here is the rule behind each, not the
screen — the screens are checked by `test_screen_wiring`.
"""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.api import pos, purchases


def _js(name: str) -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", name),
	            encoding="utf-8").read()


def _page(name: str) -> str:
	return open(frappe.get_app_path("a3_retail", "www", "retail", name),
	            encoding="utf-8").read()


class TestBillingAcrossAStateLine(FrappeTestCase):
	"""9 · a customer from another state has to be billable."""

	def test_a_state_code_is_two_digits_however_it_was_written(self):
		self.assertEqual(pos._state_code("32"), "32")
		self.assertEqual(pos._state_code(32), "32")
		self.assertEqual(pos._state_code("9"), "09")
		self.assertEqual(pos._state_code("33-Tamil Nadu"), "33")
		self.assertIsNone(pos._state_code(""))
		self.assertIsNone(pos._state_code(None))

	def test_a_state_name_resolves_to_its_gst_number(self):
		self.assertEqual(pos._state_code_for("Kerala"), "32")
		self.assertEqual(pos._state_code_for("Tamil Nadu"), "33")
		self.assertEqual(pos._state_code_for("tamil nadu"), "33")
		self.assertIsNone(pos._state_code_for(""))
		self.assertIsNone(pos._state_code_for("Nowhere"))

	def test_place_of_supply_is_read_before_anything_else(self):
		"""India Compliance works it out; where it has, that is the answer."""
		invoice = frappe._dict(customer=None, customer_address=None,
		                       billing_address_gstin=None,
		                       place_of_supply="33-Tamil Nadu")
		self.assertEqual(pos._supply_state_code(invoice), "33")

	def test_a_registered_buyer_is_taxed_on_their_registration(self):
		invoice = frappe._dict(customer=None, customer_address=None,
		                       place_of_supply=None,
		                       billing_address_gstin="33AAAAA0000A1Z5")
		self.assertEqual(pos._supply_state_code(invoice), "33")

	def test_a_walk_in_is_taxed_on_where_the_goods_go(self):
		"""The bug: a buyer with no GSTIN was read as local whatever their
		address said, so an out-of-state sale was billed CGST+SGST and India
		Compliance refused to save it."""
		address = frappe.get_doc({
			"doctype": "Address", "address_title": "A3 Test Out Of State",
			"address_type": "Billing", "address_line1": "1 Test Rd",
			"city": "Chennai", "state": "Tamil Nadu", "pincode": "600001",
			"country": "India",
		})
		address.flags.ignore_mandatory = True
		address.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Address", address.name, force=1)

		invoice = frappe._dict(customer=None, customer_address=address.name,
		                       place_of_supply=None, billing_address_gstin=None)
		self.assertEqual(pos._supply_state_code(invoice), "33")

	def test_nothing_known_is_treated_as_a_local_sale(self):
		"""Which it almost always is — a walk-in who gave only a phone number."""
		invoice = frappe._dict(customer=None, customer_address=None,
		                       place_of_supply=None, billing_address_gstin=None)
		self.assertIsNone(pos._supply_state_code(invoice))
		self.assertFalse(pos._is_inter_state(invoice, "PhoneXpert Sales PSLA"))

	def test_a_repair_checks_the_same_direction_as_a_sale(self):
		"""A device left by somebody from another state is an inter-state
		supply too, whatever template the counter picked at booking."""
		import inspect

		from a3_retail.api import service

		source = inspect.getsource(service._apply_service_gst)
		self.assertIn("_is_inter_state", source)
		self.assertIn("Out-state", source)

	def test_the_repair_bill_is_taxed_after_erpnext_fills_the_blanks(self):
		"""`set_missing_values` re-reads the template off the POS profile, so
		choosing one before it runs is choosing one that gets overwritten."""
		import inspect

		from a3_retail.api import service

		source = inspect.getsource(service.generate_invoice) \
			if hasattr(service, "generate_invoice") else ""
		if not source:
			source = open(frappe.get_app_path("a3_retail", "api", "service.py"),
			              encoding="utf-8").read()
		before = source.index("invoice.set_missing_values()")
		after = source.index("_apply_service_gst(invoice, doc)")
		self.assertLess(before, after)


class TestWhatTheCustomerFormShows(FrappeTestCase):
	"""10 · Edit has to open on what is held, not on blanks."""

	def test_the_profile_hands_back_the_address_in_pieces(self):
		from a3_retail.api import customer_desk

		import inspect

		source = inspect.getsource(customer_desk.profile)
		self.assertIn("address_parts", source)
		self.assertIn('"gstin"', source)

	def test_the_edit_form_fills_every_box_it_will_later_send(self):
		"""Anything Save sends has to be filled first. A box left empty is not
		a gap on the screen — it is an empty value on its way to the record."""
		body = _js("a3_customers.js")
		sends = ("address_line1", "city", "state", "pincode")
		for field in ("c-address", "c-city", "c-state", "c-pin"):
			self.assertIn(f'$("{field}").value = ', body, field)
		for field in sends:
			self.assertIn(field, body)

	def test_an_empty_box_never_wipes_a_pin_code_already_held(self):
		import inspect

		source = inspect.getsource(pos._save_address)
		self.assertIn("doc.pincode = pincode or doc.pincode", source)


class TestPuttingAPurchaseAside(FrappeTestCase):
	"""6 · a rep with forty lines and a customer walking in at line twelve."""

	def test_one_builder_serves_both_doors(self):
		import inspect

		for fn in (purchases.create, purchases.save_draft):
			self.assertIn("_build(data, employee", inspect.getsource(fn))

	def test_a_held_bill_is_not_asked_for_what_is_still_missing(self):
		import inspect

		source = inspect.getsource(purchases._build)
		self.assertIn("if complete:", source)
		self.assertIn("HELD_MARKER", source)

	def test_the_marker_never_reaches_a_posted_bill(self):
		"""India Compliance wants a bill number on every save, so a held one
		carries a marker. Submitting goes back through the real check."""
		import inspect

		source = inspect.getsource(purchases._build)
		self.assertIn("if bill_no.startswith(HELD_MARKER):", source)
		self.assertIn('bill_no = ""', source)

	def test_the_screen_never_shows_the_marker_back(self):
		import inspect

		self.assertIn("HELD_MARKER", inspect.getsource(purchases.load_draft))

	def test_a_draft_belongs_to_the_branch_that_started_it(self):
		import inspect

		source = inspect.getsource(purchases._draft_doc)
		self.assertIn("docstatus", source)
		self.assertIn("PermissionError", source)

	def test_the_screen_offers_both_hold_and_the_held_list(self):
		page = _page("purchase_entry.html")
		self.assertIn('id="p-hold"', page)
		self.assertIn('id="p-drafts"', page)
		self.assertIn('id="drafts-modal"', page)
		body = _js("a3_purchase_entry.js")
		self.assertIn("purchases.save_draft", body)
		self.assertIn("purchases.drafts", body)
		self.assertIn("purchases.load_draft", body)
		self.assertIn("purchases.discard_draft", body)


class TestPressingPrint(FrappeTestCase):
	"""3 · 4 · 8 — Print means the printer dialog, not a tab."""

	def test_the_application_has_one_way_to_print(self):
		helper = _js("a3_branch.js")
		for name in ("function printDoc", "function printUrl", "function printParts",
		             "function viewDoc"):
			self.assertIn(name, helper)
		self.assertIn("trigger_print=1", helper)
		self.assertIn("printDoc, viewDoc, printUrl, printParts", helper)

	def test_it_prints_without_opening_a_tab(self):
		helper = _js("a3_branch.js")
		printer = helper[helper.index("function printDoc"):]
		printer = printer[:printer.index("function viewDoc")]
		self.assertIn("createElement(\"iframe\")", printer)
		self.assertNotIn("window.open", printer)

	def test_every_till_screen_prints_through_it(self):
		for script in ("a3_bills.js", "a3_invoice.js", "a3_pos.js",
		               "a3_service.js", "a3_booking.js", "a3_debit_notes.js"):
			self.assertIn("A3.printDoc", _js(script), script)

	def test_both_papers_are_offered_on_a_repair(self):
		"""8 · the same choice the sales till gives."""
		page = _page("service.html")
		self.assertIn('id="done-print"', page)
		self.assertIn('id="done-thermal"', page)
		self.assertIn("Job Card Receipt (Thermal)", _js("a3_service.js"))

	def test_the_repair_bill_names_a_format_that_exists(self):
		"""`Service Tax Invoice` is the template file. The format is called
		`Service Invoice`, and naming the wrong one printed every repair bill
		on ERPNext's standard sheet."""
		api = open(frappe.get_app_path("a3_retail", "api", "service_pos.py"),
		           encoding="utf-8").read()
		self.assertIn("format=Service%20Invoice", api)
		self.assertNotIn("format=Service%20Tax%20Invoice", api)

	def test_a_debit_note_can_be_shown_as_the_bill_it_is(self):
		"""2 · the supplier asks for the paper copy as often as the shop
		files it."""
		page = _page("debit_notes.html")
		self.assertIn('id="bill-modal"', page)
		self.assertIn('id="bill-print"', page)
		self.assertIn('id="bill-view"', page)
		body = _js("a3_debit_notes.js")
		self.assertIn("A3 Purchase Invoice", body)
		self.assertIn("A3.viewDoc", body)


class TestTheFormatsThoseButtonsName(FrappeTestCase):
	"""A button that names a format nobody installed prints the wrong sheet."""

	def test_every_format_the_till_asks_for_is_on_the_site(self):
		wanted = {
			"Retail Tax Invoice": "Sales Invoice",
			"Retail Receipt (Thermal)": "Sales Invoice",
			"Service Invoice": "Sales Invoice",
			"Job Card Acknowledgement": "Service Job Card",
			"Job Card Receipt (Thermal)": "Service Job Card",
			"Job Card Label": "Service Job Card",
			"A3 Purchase Invoice": "Purchase Invoice",
		}
		for name, doctype in wanted.items():
			self.assertTrue(
				frappe.db.exists("Print Format", {"name": name, "doc_type": doctype}),
				f"{name} is not installed for {doctype}")
