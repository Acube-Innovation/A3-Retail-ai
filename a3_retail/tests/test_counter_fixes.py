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
		self.assertIn("size: 80mm {{ height or 150 }}mm", thermal)

		setup = open(frappe.get_app_path("a3_retail", "setup", "print_formats.py"),
		             encoding="utf-8").read()
		self.assertNotIn("@page { size: 80mm auto", setup)
		# One slip's worth, not two. Anywhere this fallback wins the shop used
		# to get a receipt with a blank slip hanging off the end of it.
		self.assertIn("size: 80mm 150mm", setup)
		self.assertNotIn("size: 80mm 297mm", setup)
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


class TestTheDeviceSticker(FrappeTestCase):
	"""The label that goes on the customer's phone while it is on the bench."""

	def _label(self) -> str:
		return open(frappe.get_app_path("a3_retail", "templates", "print_formats",
		                                "job_card_label.html"), encoding="utf-8").read()

	def test_one_barcode_helper_not_two(self):
		"""`print_helpers` carried two `a3_barcode` functions and the second
		shadowed the first, so every label was drawn by the wrong one."""
		source = open(frappe.get_app_path("a3_retail", "print_helpers.py"),
		              encoding="utf-8").read()
		self.assertEqual(source.count("\ndef a3_barcode("), 1)

	def test_the_barcode_carries_the_short_number(self):
		from a3_retail.print_helpers import a3_scan_code

		self.assertEqual(a3_scan_code("JC-SVP-26-00053"), "26-00053")
		self.assertEqual(a3_scan_code("JC-SLP-26-000123"), "26-000123")
		# Anything not shaped that way is left whole rather than guessed at.
		self.assertEqual(a3_scan_code("ODD"), "ODD")
		self.assertEqual(a3_scan_code(""), "")

	def test_the_short_number_still_finds_the_job_card(self):
		"""Every screen searches document numbers by what they contain, and
		`JC-SVP-26-00053` contains `26-00053`."""
		from a3_retail.print_helpers import a3_scan_code

		for name in frappe.get_all("Service Job Card", pluck="name", limit=20):
			self.assertIn(a3_scan_code(name), name)

	def test_the_short_number_is_still_unique(self):
		from a3_retail.print_helpers import a3_scan_code

		names = frappe.get_all("Service Job Card", pluck="name", limit=0)
		if not names:
			self.skipTest("no job cards on this site")
		codes = [a3_scan_code(n) for n in names]
		self.assertEqual(len(set(codes)), len(codes))

	def test_the_bars_are_wide_enough_for_a_label_printer(self):
		"""0.25mm is the usual floor for Code 128, and it is what lets a plain
		203 dpi printer lay each bar down as exactly two dots."""
		from a3_retail.print_helpers import a3_barcode_module_mm

		# 38mm of the 40mm sticker, as the template asks for.
		module = a3_barcode_module_mm("26-00053", 38)
		self.assertGreaterEqual(module, 0.25)
		dots_203 = module / (25.4 / 203)
		dots_300 = module / (25.4 / 300)
		self.assertGreaterEqual(dots_203, 2.0)
		self.assertGreaterEqual(dots_300, 3.0)

	def test_the_whole_number_is_still_printed_for_a_person(self):
		self.assertIn("{{ doc.name }}", self._label())

	def test_the_sticker_is_small_enough_for_a_phone(self):
		label = self._label()
		self.assertIn("@page { size: 40mm 20mm; margin: 0; }", label)
		self.assertIn("width: 40mm; height: 20mm", label)

	def test_the_bars_are_drawn_to_size_not_stretched(self):
		"""Forcing an `<img>` to a width and a height squashes the bars; the
		symbol is drawn at the width it will be printed at instead."""
		label = self._label()
		self.assertIn("a3_barcode(a3_scan_code(doc.name), 8, 38)", label)
		self.assertIn("width: 38mm; height: auto", label)

	def test_a_label_does_not_get_the_roll_s_stylesheet(self):
		"""The 80mm roll's CSS pins `.print-format` to 76mm. On a 40mm sticker
		that is a container twice the width of the paper, and the browser
		shrinks the lot to fit."""
		setup = open(frappe.get_app_path("a3_retail", "setup", "print_formats.py"),
		             encoding="utf-8").read()
		self.assertIn("LABEL_CSS", setup)
		self.assertIn("LABEL_CSS if size in LABEL_SIZES", setup)
		self.assertNotIn("width: 76mm", setup.split("LABEL_CSS")[1].split('"""')[1])

	def test_the_format_is_registered_at_the_sticker_s_size(self):
		setup = open(frappe.get_app_path("a3_retail", "setup", "print_formats.py"),
		             encoding="utf-8").read()
		self.assertIn('"job_card_label", "40x20mm"', setup)
		self.assertIn('LABEL_SIZES = {"40x20mm"}', setup)


class TestTheThermalSlip(FrappeTestCase):
	"""The receipt, in the shape PhoneXpert's customers already know it.

	It reproduces what myBillBook printed for years. A customer comparing an
	old slip with a new one should not be able to tell which software wrote it.
	"""

	def _receipt(self) -> str:
		return open(frappe.get_app_path("a3_retail", "templates", "print_formats",
		                                "pos_receipt.html"), encoding="utf-8").read()

	def test_it_carries_every_block_the_old_slip_had(self):
		body = self._receipt()
		for piece in ("TAX INVOICE", "Invoice No", "Bill To", "Place of Supply",
		              "Qty", "Rate", "Amt", "Sub Total", "Taxable Amount",
		              "Balance Amount", "Terms and conditions",
		              "Thank you for your purchase"):
			self.assertIn(piece, body, piece)

	def test_the_face_is_proportional_not_monospace(self):
		"""Courier is about 40% wider per character, so an item name wrapped
		twice as often and every wrap is another line of roll."""
		body = self._receipt()
		self.assertIn("font-family: Helvetica, Arial, sans-serif", body)
		# The declaration, not the comment beside it explaining why.
		self.assertNotIn("font-family: \"DejaVu Sans Mono\"", body)

	def test_it_beats_frappe_s_cell_padding(self):
		"""Frappe forces 6px on every cell with `!important` — 3.2mm of air a
		row, which over a receipt is centimetres of roll."""
		body = self._receipt()
		self.assertIn("padding: 0.15mm 0 !important", body)

	def test_the_page_has_no_margin_for_a_browser_header(self):
		"""Chrome prints the date across the top and the URL along the bottom
		whenever the page leaves it room — somebody else's address on the
		shop's bill."""
		body = self._receipt()
		self.assertIn("mm; margin: 0; }", body)

	def test_the_slip_measures_its_own_length(self):
		"""No formula gets it right: what makes one receipt longer than another
		is how many lines the branch's terms run to and how often a name wraps.
		Estimating split the total onto a second slip or fed blank roll."""
		body = self._receipt()
		self.assertIn('querySelector(".r")', body)
		self.assertIn("getBoundingClientRect().height", body)
		self.assertIn("@page { size: 80mm ", body)
		# Into the body, where it beats the format's own rule.
		self.assertIn("document.body.appendChild(sheet)", body)

	def test_gst_is_labelled_the_way_a_customer_reads_it(self):
		from a3_retail.print_helpers import a3_gst_lines

		doc = frappe._dict(taxes=[
			frappe._dict(account_head="Output Tax CGST - PT", rate=9, tax_amount=22.88),
			frappe._dict(account_head="Output Tax SGST - PT", rate=9, tax_amount=22.88),
		])
		self.assertEqual([label for label, _a in a3_gst_lines(doc)],
		                 ["CGST @9%", "SGST @9%"])

	def test_an_igst_bill_says_igst(self):
		from a3_retail.print_helpers import a3_gst_lines

		doc = frappe._dict(taxes=[
			frappe._dict(account_head="Output Tax IGST - PT", rate=18, tax_amount=152.54)])
		self.assertEqual([label for label, _a in a3_gst_lines(doc)], ["IGST @18%"])

	def test_a_line_shows_the_rate_it_carries(self):
		from a3_retail.print_helpers import a3_line_gst_rate

		doc = frappe._dict(net_total=12711.01, taxes=[
			frappe._dict(account_head="Output Tax CGST - PT", tax_amount=1144.0),
			frappe._dict(account_head="Output Tax SGST - PT", tax_amount=1144.0),
		])
		self.assertEqual(a3_line_gst_rate(frappe._dict(), doc), 18.0)
		# Nothing to work from is no guess at all.
		self.assertEqual(a3_line_gst_rate(frappe._dict()), 0.0)

	def test_place_of_supply_reads_as_a_place(self):
		from a3_retail.print_helpers import a3_place_of_supply

		self.assertEqual(a3_place_of_supply(frappe._dict(place_of_supply="32-Kerala")),
		                 "Kerala")
		self.assertEqual(a3_place_of_supply(frappe._dict(place_of_supply="")), "")

	def test_the_terms_come_from_the_same_place_as_the_a4_sheet(self):
		"""Two slips for one sale must not say different things."""
		self.assertIn('profile.get("invoice_terms") or a3_terms(doc)', self._receipt())


class TestOpeningABranch(FrappeTestCase):
	"""What a new counter needs, and how much of it it makes for itself."""

	def test_a_branch_name_comes_apart_the_same_way_everywhere(self):
		"""One definition, on the doctype. The patch that backfilled the
		existing branches calls this rather than keeping its own copy."""
		from a3_retail.a3_retail_operations.doctype.branch_profile.branch_profile import (
			site_of,
		)
		from a3_retail.patches import branch_sites_and_counter_switching as patch

		self.assertEqual(site_of("PhoneXpert Sales UK"), "UK")
		self.assertEqual(site_of("PhoneXpert Accessories Neyyattinkara"), "Neyyattinkara")
		self.assertEqual(patch._site_of("PhoneXpert Services PSLA"), "PSLA")

	def test_a_new_profile_fills_its_own_site_in(self):
		"""The backfill patch runs once. A branch opened after it would never
		get a site, and its staff would never see the counter picker."""
		import inspect

		from a3_retail.a3_retail_operations.doctype.branch_profile import branch_profile

		self.assertIn("self.set_site()",
		              inspect.getsource(branch_profile.BranchProfile.validate))
		source = inspect.getsource(branch_profile.BranchProfile.set_site)
		# Never over a site somebody typed.
		self.assertIn('if (self.site or "").strip():', source)

	def test_a_new_warehouse_is_told_its_stock_account(self):
		"""Left blank, ERPNext works it out from the company default on every
		purchase and says so in the middle of whatever dialog the counter is
		in. The patch that named the existing eleven runs once."""
		import inspect

		from a3_retail.a3_retail_operations.doctype.branch_profile import branch_profile

		source = inspect.getsource(branch_profile.BranchProfile.create_branch_warehouses)
		self.assertIn("default_inventory_account", source)

	def test_whoever_bills_a_repair_can_reach_a_pos_profile(self):
		"""ERPNext lists POS Profiles under the user's own permissions while
		pricing an invoice. A service counter bills repairs, so the roles that
		finish one need the same select the sales counter has."""
		from a3_retail.setup.permissions import PERMISSION_MATRIX

		raisers = {role for role, flags in PERMISSION_MATRIX["Sales Invoice"].items()
		           if "C" in flags}
		reachable = set(PERMISSION_MATRIX["POS Profile"])
		missing = {r for r in raisers if r not in reachable
		           and not PERMISSION_MATRIX["POS Profile"].get(r)}
		# Accounts Manager reads it outright rather than by select.
		missing -= {"Accounts Manager"}
		self.assertEqual(missing, set(), f"cannot reach a POS Profile: {missing}")
