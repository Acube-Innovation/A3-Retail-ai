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


class TestTheSheetAndTheRoll(FrappeTestCase):
	"""1 · 4 — the paper the bill comes out on."""

	def _format(self, name: str) -> str:
		return open(frappe.get_app_path("a3_retail", "templates", "print_formats", name),
		            encoding="utf-8").read()

	def test_the_invoice_measures_its_own_blank(self):
		"""The browser prints this now, and a figure calibrated against
		wkhtmltopdf left 53mm of white at the foot of every bill. The blank is
		its own table so the slack has nowhere else to go — stretching the
		items table instead put it into the SUB TOTAL row."""
		body = self._format("retail_tax_invoice.html")
		self.assertIn('class="sheet gap"', body)
		self.assertIn(".mbb > table.gap { flex: 1 1 auto; }", body)
		self.assertIn("min-height: calc(297mm - 12mm)", body)

	def test_the_blank_is_not_inside_the_items_table(self):
		body = self._format("retail_tax_invoice.html")
		items = body[body.index('class="sheet items"'):]
		items = items[:items.index('class="sheet gap"')]
		self.assertNotIn('class="fill"', items)

	def test_wkhtmltopdf_still_gets_its_measured_height(self):
		"""`download_pdf` — the copy that goes out by WhatsApp — has no
		flexbox to read, so the figure stays."""
		body = self._format("retail_tax_invoice.html")
		self.assertIn("fill_height", body)
		self.assertIn('style="height:{{ fill_height }}px"', body)

	def test_the_three_stacked_tables_share_one_set_of_columns(self):
		body = self._format("retail_tax_invoice.html")
		self.assertEqual(body.count("<colgroup>"), 3)

	def test_a_thermal_page_names_a_real_height(self):
		"""`size: 80mm auto` is not valid CSS, so a browser drops it and prints
		the slip on whatever paper it was last set to — A4, in the shop's
		case."""
		from a3_retail import print_helpers

		# The rule itself, not the comment next to it explaining why.
		thermal = self._format("a3_thermal.html")
		self.assertNotIn("@page { size: 80mm auto", thermal)
		self.assertIn("size: 80mm {{ height or 297 }}mm", thermal)

		setup = open(frappe.get_app_path("a3_retail", "setup", "print_formats.py"),
		             encoding="utf-8").read()
		self.assertNotIn("@page { size: 80mm auto", setup)
		self.assertIn("size: 80mm 297mm", setup)
		self.assertTrue(hasattr(print_helpers, "a3_thermal_height"))

	def test_the_roll_is_long_enough_for_what_is_on_it(self):
		from a3_retail.print_helpers import a3_thermal_height

		short = frappe._dict(items=[frappe._dict(item_code="X")], payments=[], taxes=[])
		long = frappe._dict(items=[frappe._dict(item_code="X")] * 12, payments=[], taxes=[])
		self.assertGreaterEqual(a3_thermal_height(short), 120)
		self.assertGreater(a3_thermal_height(long), a3_thermal_height(short))
		self.assertLessEqual(a3_thermal_height(long), 900)

	def test_a_figure_on_the_roll_never_wraps(self):
		""""₹ 1,200.00" broken over two lines reads as two amounts."""
		thermal = self._format("a3_thermal.html")
		self.assertIn("white-space: nowrap", thermal)
		self.assertIn("table-layout: fixed", thermal)
		receipt = self._format("pos_receipt.html")
		self.assertIn("<colgroup>", receipt)
		self.assertIn('"{:g}".format(row.qty|float)', receipt)


class TestWorkingTheOtherCounter(FrappeTestCase):
	"""7 · two tills in one shop, and one person working both."""

	def test_a_branch_knows_which_shop_it_stands_in(self):
		self.assertTrue(frappe.db.has_column("Branch Profile", "site"))

	def test_the_site_is_read_off_the_branch_name(self):
		from a3_retail.patches import branch_sites_and_counter_switching as sites

		self.assertEqual(sites._site_of("PhoneXpert Sales UK"), "UK")
		self.assertEqual(sites._site_of("PhoneXpert Accessories UK"), "UK")
		self.assertEqual(sites._site_of("PhoneXpert Services PSLA"), "PSLA")
		# Its own place, with nothing to switch to.
		self.assertEqual(sites._site_of("PhoneXpert Distribution"), "Distribution")
		self.assertIsNone(sites._site_of("PhoneXpert"))

	def test_permission_is_asked_for_before_anything_is_offered(self):
		"""The flag is the gate; the site only says where it reaches."""
		import inspect

		from a3_retail.api import staff

		source = inspect.getsource(staff._counters_at_the_same_site)
		self.assertIn("a3_can_switch_counter", source)
		self.assertIn('"site"', source)
		# And never beyond the person's own site.
		self.assertIn('filters={"site": site', source)

	def test_a_till_without_the_flag_sees_only_its_own_branch(self):
		from a3_retail.api import staff

		self.assertEqual(
			staff._counters_at_the_same_site({"name": "NO-SUCH-EMPLOYEE"}, "PhoneXpert Sales UK"),
			[])

	def test_the_picker_is_already_on_the_screens(self):
		"""Nothing new to draw: the top bar has had a branch picker all along,
		shown when the session says there is more than one to pick."""
		helper = _js("a3_branch.js")
		self.assertIn("mountBranchPicker", helper)
		self.assertIn("staff.switch_branch", helper)
		self.assertIn("can_switch_branch", helper)


class TestTheAppleShelf(FrappeTestCase):
	"""5 · an iPhone that cannot be matched to the piece that was sold."""

	def test_scope_is_the_shop_s_own_filing_not_the_item_name(self):
		"""Reading names would have swept in BOAT AIRPODS and IPHONE PREMIUM
		TEMPERED GLASS — a screen protector with 211 on the shelf."""
		from a3_retail.patches import apple_items_serialised as apple

		self.assertEqual(apple.GROUPS, ("APPLE", "APPLE EARPODS", "APPLE ADAPTOR"))
		self.assertEqual(apple.BRAND, "Apple")
		items = apple._apple_items()
		for name in items:
			group = frappe.db.get_value("Item", name, "item_group")
			brand = frappe.db.get_value("Item", name, "brand")
			self.assertTrue(group in apple.GROUPS or brand == apple.BRAND, name)

	def test_a_screen_guard_is_never_in_scope(self):
		from a3_retail.patches import apple_items_serialised as apple

		for name in apple._apple_items():
			self.assertNotIn("TEMPERED", (name or "").upper())

	def test_a_charge_is_not_a_thing_with_a_serial_number(self):
		from a3_retail.patches import apple_items_serialised as apple

		if frappe.db.exists("Item", "CARD CHARGES"):
			self.assertTrue(apple._is_a_charge("CARD CHARGES"))

	def test_stock_on_the_shelf_is_left_alone(self):
		"""Those pieces were counted in without IMEIs and could never produce
		one. `can_serialise` is the gate, and the patch names what it skipped."""
		import inspect

		from a3_retail.patches import apple_items_serialised as apple

		source = inspect.getsource(apple.execute)
		self.assertIn("can_serialise(item)", source)
		self.assertIn("on_hand(item)", source)
		self.assertIn("still holding stock", source)

	def test_both_patches_run_on_a_deploy(self):
		registered = open(frappe.get_app_path("a3_retail", "patches.txt")).read()
		self.assertIn("a3_retail.patches.apple_items_serialised", registered)
		self.assertIn("a3_retail.patches.branch_sites_and_counter_switching", registered)
