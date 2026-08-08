# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Print styles, letter heads, QR helpers and the 24 print formats (scope step 24, 13.3)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail import print_helpers as ph
from a3_retail.setup import print_formats as pf
from a3_retail.tests.fixtures import ensure_branch
from a3_retail.utils import qr

A4_FORMATS = [name for name, _dt, _tpl, size in pf.FORMATS if size != "80mm"]
THERMAL_FORMATS = [name for name, _dt, _tpl, size in pf.FORMATS if size == "80mm"]


class TestRegister(FrappeTestCase):
	def test_every_registered_format_exists(self):
		# Twenty-four at scope 13.3, plus the settlement statement the financing
		# desk prints.
		self.assertEqual(len(pf.FORMATS), 25)
		for name, doctype, _template, _size in pf.FORMATS:
			self.assertTrue(frappe.db.exists("Print Format", name), name)
			self.assertEqual(frappe.db.get_value("Print Format", name, "doc_type"), doctype, name)

	def test_every_format_belongs_to_an_a3_module(self):
		for name, *_ in pf.FORMATS:
			self.assertEqual(frappe.db.get_value("Print Format", name, "module"), pf.MODULE, name)

	def test_every_format_is_a_custom_jinja_format(self):
		for name, *_ in pf.FORMATS:
			row = frappe.db.get_value(
				"Print Format", name, ["print_format_type", "standard", "custom_format", "disabled"],
				as_dict=True,
			)
			self.assertEqual(row.print_format_type, "Jinja", name)
			self.assertEqual(row.standard, "No", name)
			self.assertTrue(row.custom_format, name)
			self.assertFalse(row.disabled, name)

	def test_html_points_at_a_template_on_disk(self):
		import os

		folder = frappe.get_app_path("a3_retail", "templates", "print_formats")
		for name, _doctype, template, _size in pf.FORMATS:
			html = frappe.db.get_value("Print Format", name, "html")
			self.assertIn(template, html, name)
			self.assertTrue(os.path.exists(os.path.join(folder, f"{template}.html")), template)

	def test_a4_formats_number_their_pages(self):
		for name in A4_FORMATS:
			self.assertEqual(
				frappe.db.get_value("Print Format", name, "page_number"), "Bottom Center", name
			)

	def test_thermal_formats_are_eighty_millimetres_wide(self):
		for name in THERMAL_FORMATS:
			row = frappe.db.get_value("Print Format", name, ["css", "margin_left", "page_number"],
			                          as_dict=True)
			self.assertIn("80mm", row.css, name)
			self.assertEqual(row.margin_left, 2, name)
			self.assertEqual(row.page_number, "Hide", name)

	def test_thermal_css_hides_the_letter_head(self):
		for name in THERMAL_FORMATS:
			self.assertIn("letter-head", frappe.db.get_value("Print Format", name, "css"), name)


class TestStylesAndLetterHeads(FrappeTestCase):
	def test_both_print_styles_exist(self):
		for name in (pf.A4_STYLE, pf.THERMAL_STYLE):
			self.assertTrue(frappe.db.exists("Print Style", name), name)

	def test_a4_style_is_the_default(self):
		self.assertEqual(frappe.db.get_single_value("Print Settings", "print_style"), pf.A4_STYLE)

	def test_header_and_footer_repeat(self):
		self.assertTrue(frappe.db.get_single_value("Print Settings", "repeat_header_footer"))

	def test_one_letter_head_per_branch(self):
		for branch in ("Kochi", "Thiruvananthapuram", "Kozhikode"):
			self.assertTrue(frappe.db.exists("Letter Head", f"{branch} Letter Head"), branch)

	def test_the_letter_head_carries_the_branch_gstin(self):
		content = frappe.db.get_value("Letter Head", "Kochi Letter Head", "content")
		self.assertIn("GSTIN", content)
		self.assertIn("Kochi", content)

	def test_a_default_letter_head_is_marked(self):
		self.assertTrue(frappe.db.exists("Letter Head", {"is_default": 1}))

	def test_branch_profile_points_at_its_letter_head(self):
		self.assertEqual(
			frappe.db.get_value("Branch Profile", {"branch": "Kochi"}, "letter_head"),
			"Kochi Letter Head",
		)


class TestBranchLetterHeadSelection(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_the_branch_letter_head_is_selected(self):
		name = frappe.db.get_value("Service Job Card", {"branch": "Kochi"}, "name")
		if not name:
			self.skipTest("no job card seeded")

		doc = frappe.get_doc("Service Job Card", name)
		doc.letter_head = None
		pf.apply_branch_letter_head(doc)
		self.assertEqual(doc.letter_head, "Kochi Letter Head")

	def test_an_explicit_choice_is_respected(self):
		doc = frappe.new_doc("Service Job Card")
		doc.branch = "Kochi"
		doc.letter_head = "A3 Retail Default"
		pf.apply_branch_letter_head(doc)
		self.assertEqual(doc.letter_head, "A3 Retail Default")

	def test_a_document_without_a_branch_is_left_alone(self):
		doc = frappe.new_doc("Service Job Card")
		pf.apply_branch_letter_head(doc)
		self.assertFalse(doc.get("letter_head"))


class TestQrHelpers(FrappeTestCase):
	def test_a_qr_is_a_png_data_uri(self):
		uri = qr.qr_data_uri("https://example.com")
		self.assertTrue(uri.startswith("data:image/png;base64,"))
		self.assertGreater(len(uri), 200)

	def test_empty_text_makes_no_code(self):
		self.assertEqual(qr.qr_data_uri(""), "")

	def test_tracking_url_by_doctype(self):
		job = frappe.new_doc("Service Job Card")
		job.name = "JC-KCH-0001"
		self.assertIn("/track-repair?job=JC-KCH-0001", qr.tracking_url(job))

		warranty = frappe.new_doc("Warranty Registration")
		warranty.name = "WR-0001"
		self.assertIn("/verify-warranty?ref=WR-0001", qr.tracking_url(warranty))

	def test_upi_uri_uses_the_configured_vpa(self):
		frappe.db.set_single_value("A3 Retail Settings", "upi_vpa", "mobileworld@upi")
		uri = qr.upi_uri(1250.50, "SINV-0001")
		self.assertIn("pa=mobileworld%40upi", uri)
		self.assertIn("am=1250.5", uri)
		self.assertIn("cu=INR", uri)

	def test_no_vpa_means_no_upi_code(self):
		saved = frappe.db.get_single_value("A3 Retail Settings", "upi_vpa")
		frappe.db.set_single_value("A3 Retail Settings", "upi_vpa", "")
		self.assertEqual(qr.upi_uri(100), "")
		frappe.db.set_single_value("A3 Retail Settings", "upi_vpa", saved)

	def test_payment_qr_prefers_the_signed_einvoice_code(self):
		invoice = frappe.new_doc("Sales Invoice")
		invoice.signed_qr_code = "eyJhbGciOiJSUzI1NiJ9.SIGNED"
		self.assertTrue(qr.einvoice_qr(invoice).startswith("data:image/png;base64,"))


class TestPrintHelpers(FrappeTestCase):
	def test_hsn_summary_totals_match_the_invoice(self):
		name = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "is_return": 0}, "name", order_by="modified desc"
		)
		if not name:
			self.skipTest("no invoice seeded")

		doc = frappe.get_doc("Sales Invoice", name)
		summary = ph.a3_hsn_summary(doc)
		self.assertTrue(summary)
		self.assertAlmostEqual(
			sum(row["taxable"] for row in summary), flt(doc.base_net_total), places=1
		)
		self.assertAlmostEqual(
			sum(row["total"] for row in summary), flt(doc.base_grand_total), places=0
		)

	def test_an_empty_document_has_no_hsn_rows(self):
		self.assertEqual(ph.a3_hsn_summary(frappe.new_doc("Sales Invoice")), [])

	def test_branch_profile_flattens_the_address(self):
		profile = ph.a3_branch_profile("Kochi")
		for key in ("branch", "address", "gstin", "phone", "letter_head"):
			self.assertIn(key, profile)

	def test_an_unknown_branch_returns_nothing(self):
		self.assertEqual(ph.a3_branch_profile("Nowhere"), {})

	def test_amount_in_words(self):
		self.assertIn("One Thousand, Two Hundred And Fifty", ph.a3_words(1250))

	def test_invoice_total_lines_include_every_tax(self):
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name",
		                           order_by="modified desc")
		if not name:
			self.skipTest("no invoice seeded")
		doc = frappe.get_doc("Sales Invoice", name)
		labels = [label for label, _amount in ph.a3_invoice_total_lines(doc)]
		self.assertIn("Net Total", labels)
		self.assertEqual(len(labels), len(ph.a3_tax_lines(doc)) + 1
		                 + (1 if flt(doc.discount_amount) else 0)
		                 + (1 if flt(doc.rounding_adjustment) else 0))


class TestRendering(FrappeTestCase):
	"""The scope's smoke test, run as HTML so the suite stays fast.

	`setup.print_formats.smoke_test()` does the same sweep through wkhtmltopdf;
	that needs a running web server, so it is a bench command rather than a test.
	"""

	def test_every_format_renders(self):
		result = pf.smoke_test(as_pdf=False, verbose=False)
		self.assertEqual(result["failed"], [])
		self.assertEqual(result["total"], 25)

	def test_a4_output_carries_the_page_counter(self):
		doc, _real = pf.sample_doc("Service Job Card")
		html = frappe.get_print("Service Job Card", doc.name,
		                        print_format="Job Card Acknowledgement", doc=doc)
		self.assertIn('id="footer-html"', html)
		self.assertIn('class="page"', html)
		self.assertIn('class="topage"', html)

	def test_thermal_output_has_no_letter_head(self):
		doc, _real = pf.sample_doc("Service Job Card")
		html = frappe.get_print("Service Job Card", doc.name,
		                        print_format="Job Card Receipt (Thermal)", doc=doc,
		                        no_letterhead=1)
		self.assertIn("80mm", html)
		self.assertNotIn("a3-letter-head", html)

	def test_the_invoice_shows_an_hsn_summary(self):
		doc, real = pf.sample_doc("Sales Invoice")
		if not real:
			self.skipTest("no invoice seeded")
		html = frappe.get_print("Sales Invoice", doc.name, print_format="Retail Tax Invoice",
		                        doc=doc)
		self.assertIn("HSN / SAC", html)
		self.assertIn("Grand Total", html)

	def test_the_job_card_receipt_carries_a_tracking_code(self):
		doc, _real = pf.sample_doc("Service Job Card")
		html = frappe.get_print("Service Job Card", doc.name,
		                        print_format="Job Card Receipt (Thermal)", doc=doc,
		                        no_letterhead=1)
		self.assertIn("data:image/png;base64,", html)
		self.assertIn("Track this repair", html)
