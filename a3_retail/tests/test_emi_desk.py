# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""EMI Management — the financing workspace at `/branch/emi`."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.api import emi
from a3_retail.tests.fixtures import ensure_branch

TABS = ("overview", "applications", "schemes", "financiers", "sales", "settlements",
        "documents", "reconciliation")


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestEMIPage(FrappeTestCase):
	def test_the_page_is_one_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("emi.html", "emi.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "emi.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_emi.js", markup)
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_the_page_says_what_it_is_for(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "emi.html")).read()
		self.assertIn("EMI Management", markup)
		self.assertIn("Manage financing partners, schemes, applications and settlements", markup)
		self.assertIn("New EMI Application", markup)

	def test_every_tab_the_spec_asked_for_is_on_the_page(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "emi.html")).read()
		for tab in TABS:
			self.assertIn(f'("{tab}"', markup, tab)

	def test_emi_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")).read()
		self.assertIn('("emi", "EMI", "/branch/emi"', sidebar)

	def test_no_second_sales_or_accounting_system(self):
		"""Every write goes through a document ERPNext or the app already owns."""
		body = open(frappe.get_app_path("a3_retail", "api", "emi.py")).read()
		for forbidden in ("frappe.new_doc(\"Sales Invoice\")", "frappe.new_doc(\"Journal Entry\")",
		                  "frappe.new_doc(\"Payment Entry\")", "tabGL Entry"):
			self.assertNotIn(forbidden, body, forbidden)
		for delegated in ("record_decision", "submit_to_financier", "get_pending_applications"):
			self.assertIn(delegated, body, delegated)

	def test_no_financier_is_hard_coded(self):
		"""Partner names live in the master, never in the code or the markup."""
		for path in (frappe.get_app_path("a3_retail", "api", "emi.py"),
		             frappe.get_app_path("a3_retail", "public", "js", "a3_emi.js"),
		             os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "emi.html")):
			body = open(path).read()
			for partner in ("Bajaj", "Home Credit", "TVS Credit", "IDFC", "HDFC", "ZestMoney"):
				self.assertNotIn(partner, body, f"{partner} named in {os.path.basename(path)}")

	def test_credentials_never_reach_the_browser(self):
		body = open(frappe.get_app_path("a3_retail", "api", "emi.py")).read()
		self.assertNotIn("api_key", body.split("def save_partner")[0],
		                 "no endpoint reads the stored key")
		self.assertIn("API credentials are not set from this screen", body)


class TestEMIAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_desk(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, emi.kpis)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, emi.bootstrap)


class TestEMIWorkspace(FrappeTestCase):
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

	def test_the_desk_starts_with_the_masters_not_a_hard_coded_list(self):
		boot = emi.bootstrap()
		self.assertEqual(boot["branch"], "Kochi")
		self.assertEqual(
			{row["name"] for row in boot["partners"]},
			set(frappe.get_all("Finance Partner", filters={"is_active": 1}, pluck="name")),
		)
		self.assertIn("apply", boot["can"])

	def test_every_tab_answers(self):
		for name in TABS:
			result = emi.tab(name)
			self.assertIsInstance(result, dict, name)
			self.assertTrue("rows" in result or "pending" in result, name)

	def test_an_unknown_tab_says_so(self):
		self.assertRaises(frappe.ValidationError, emi.tab, "nonsense")

	def test_the_cards_and_the_applications_tab_agree(self):
		cards = emi.kpis()
		pending = emi.tab("applications", {"status": "pending"}, page_size=100)
		self.assertEqual(cards["pending"]["value"], pending["total"])

	def test_the_financier_summary_only_counts_this_branch(self):
		rows = emi.financiers_summary()
		listed = emi.tab("applications", page_size=100)["total"]
		self.assertLessEqual(sum(row["applications"] for row in rows), listed)

	def test_applications_are_this_branch_s_own(self):
		for row in emi.tab("applications", page_size=50)["rows"]:
			self.assertEqual(row["branch"], "Kochi", row["name"])

	def test_a_row_carries_every_column_the_table_shows(self):
		rows = emi.tab("applications", page_size=5)["rows"]
		if not rows:
			self.skipTest("no applications at this branch")
		for key in ("name", "application_date", "customer_name", "customer_mobile",
		            "sales_invoice", "finance_partner", "emi_scheme", "loan_amount",
		            "down_payment", "emi_amount", "tenure_months", "status", "branch",
		            "sales_person", "tone"):
			self.assertIn(key, rows[0], key)

	def test_an_application_from_another_branch_is_refused(self):
		other = frappe.db.get_value(
			"EMI Application", {"branch": ["not in", ("Kochi", "")]}, "name")
		if not other:
			self.skipTest("no application outside this branch")
		self.assertRaises(frappe.ValidationError, emi.application, other)

	def test_a_missing_application_says_so_in_words(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			emi.application("EMI-99-99999")
		self.assertIn("no application numbered", str(caught.exception).lower())


class TestOneApplication(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

		rows = emi.tab("applications", page_size=1)["rows"]
		if not rows:
			self.skipTest("no applications at this branch")
		self.name = rows[0]["name"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_view_shows_the_customer_the_purchase_the_loan_and_the_paperwork(self):
		card = emi.application(self.name)
		for key in ("customer", "purchase", "finance", "loan", "progress", "documents",
		            "timeline", "can", "print_url"):
			self.assertIn(key, card, key)

	def test_sensitive_numbers_are_masked(self):
		"""A PAN on a screen anybody can walk past is a PAN in the wild."""
		doc = frappe.get_doc("EMI Application", self.name)
		if not doc.pan_number:
			self.skipTest("no PAN recorded on this application")

		shown = emi.application(self.name)["customer"]["pan"]
		self.assertNotEqual(shown, doc.pan_number)
		self.assertTrue(shown.endswith(doc.pan_number[-4:]))

	def test_the_aadhaar_is_never_more_than_four_digits(self):
		card = emi.application(self.name)
		if not card["customer"]["aadhaar"]:
			self.skipTest("no Aadhaar recorded")
		self.assertIn("XXXX", card["customer"]["aadhaar"])

	def test_the_timeline_reads_in_the_order_it_happened(self):
		events = emi.timeline(self.name)
		self.assertTrue(events)
		stamps = [str(event["at"]) for event in events]
		self.assertEqual(stamps, sorted(stamps))

	def test_the_print_route_is_the_application_s_own_format(self):
		url = emi.print_url(self.name)
		self.assertIn("download_pdf", url)
		self.assertIn("EMI+Application+Form", url.replace("%20", "+"))

	def test_a_note_lands_on_the_timeline(self):
		before = len(emi.timeline(self.name))
		emi.add_note(self.name, "Customer rang about this one.")
		self.assertEqual(len(emi.timeline(self.name)), before + 1)


class TestEligibleSchemes(FrappeTestCase):
	"""The service the Sales POS consumes."""

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_scheme_outside_its_ticket_range_is_not_offered(self):
		for scheme in emi.eligible_schemes(invoice_total=5000):
			self.assertLessEqual(flt(scheme.get("min_invoice_amount")), 5000, scheme["name"])

	def test_an_inactive_scheme_is_never_offered(self):
		offered = {scheme["name"] for scheme in emi.eligible_schemes(invoice_total=50000)}
		for name in frappe.get_all("EMI Scheme", filters={"is_active": 0}, pluck="name"):
			self.assertNotIn(name, offered)

	def test_a_lapsed_scheme_is_never_offered(self):
		scheme = frappe.get_all("EMI Scheme", filters={"is_active": 1}, limit=1)
		if not scheme:
			self.skipTest("no schemes configured")

		doc = frappe.get_doc("EMI Scheme", scheme[0].name)
		original = doc.valid_upto
		doc.valid_upto = add_days(nowdate(), -1)
		doc.save(ignore_permissions=True)
		try:
			offered = {row["name"] for row in emi.eligible_schemes(invoice_total=50000)}
			self.assertNotIn(doc.name, offered)
		finally:
			doc.valid_upto = original
			doc.save(ignore_permissions=True)

	def test_every_quote_says_it_is_indicative(self):
		"""The shop's arithmetic is not an offer of finance."""
		for scheme in emi.eligible_schemes(invoice_total=50000):
			self.assertTrue(scheme["indicative"], scheme["name"])
			self.assertIn("emi_amount", scheme)
			self.assertIn("customer_payable_today", scheme)

	def test_the_quote_is_the_job_card_s_own_arithmetic(self):
		from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import (
			EMIApplication,
		)

		for scheme in emi.eligible_schemes(invoice_total=50000):
			expected = EMIApplication.compute_emi(
				scheme["loan_amount"], scheme["tenure_months"],
				flt(scheme["interest_rate"]), scheme.get("interest_type") or "Flat")
			self.assertAlmostEqual(scheme["emi_amount"], round(expected, 2), places=2)

	def test_the_calculator_is_marked_indicative_too(self):
		result = emi.calculate(price=79999, down_payment=10000, tenure_months=12)
		self.assertTrue(result["indicative"])
		self.assertEqual(result["loan_amount"], 69999)
		self.assertAlmostEqual(result["emi_amount"], round(69999 / 12, 2), places=2)


class TestWritingAnApplication(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

		self.scheme = frappe.db.get_value(
			"EMI Scheme", {"is_active": 1, "min_invoice_amount": ["<=", 50000]},
			["name", "finance_partner", "down_payment_percent", "min_down_payment"], as_dict=True)
		if not self.scheme:
			self.skipTest("no scheme fits the test basket")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _payload(self, **overrides) -> dict:
		down = max(flt(self.scheme.min_down_payment), 50000 * flt(self.scheme.down_payment_percent) / 100)
		payload = {
			"mobile_no": "9847012345",
			"customer_name": "Rahul Krishnan",
			"employment_type": "Salaried",
			"monthly_income": 65000,
			"pan": "ABCDE1234F",
			"aadhaar_last4": "4321",
			"invoice_total": 50000,
			"partner": self.scheme.finance_partner,
			"scheme": self.scheme.name,
			"down_payment": down,
		}
		payload.update(overrides)
		return payload

	def test_a_draft_is_created_with_the_checklist_the_scheme_asks_for(self):
		result = emi.save_application(self._payload())
		doc = frappe.get_doc("EMI Application", result["application"])

		self.assertEqual(doc.branch, "Kochi")
		self.assertEqual(doc.emi_scheme, self.scheme.name)
		self.assertTrue(doc.get("documents"), "a checklist was raised")

	def test_nothing_to_finance_is_refused_in_words(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			emi.save_application(self._payload(invoice_total=0))
		self.assertIn("what does the purchase come to", str(caught.exception).lower())

	def test_the_kyc_a_financier_needs_is_asked_for_in_words(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			emi.save_application(self._payload(pan="", aadhaar_last4=""))
		message = str(caught.exception).lower()
		self.assertIn("pan", message)
		self.assertIn("aadhaar", message)
		self.assertNotIn("value missing", message)

	def test_a_scheme_without_a_financier_is_refused(self):
		self.assertRaises(frappe.ValidationError, emi.save_application,
		                  self._payload(partner=None, scheme=None))

	def test_an_application_cannot_be_submitted_with_documents_missing(self):
		result = emi.save_application(self._payload())
		with self.assertRaises(frappe.ValidationError) as caught:
			emi.submit_application(result["application"])
		self.assertIn("missing", str(caught.exception).lower())

	def test_a_settled_application_cannot_be_cancelled(self):
		settled = frappe.db.get_value(
			"EMI Application", {"branch": "Kochi", "status": "Settled"}, "name")
		if not settled:
			self.skipTest("nothing settled at this branch")
		self.assertRaises(frappe.ValidationError, emi.cancel_application, settled)

	def test_an_invoiced_application_cannot_be_cancelled_on_its_own(self):
		invoiced = frappe.db.get_value(
			"EMI Application",
			{"branch": "Kochi", "sales_invoice": ["not in", ("", None)], "docstatus": 1}, "name")
		if not invoiced:
			self.skipTest("no application carries an invoice")
		with self.assertRaises(frappe.ValidationError) as caught:
			emi.cancel_application(invoiced)
		self.assertIn("invoice", str(caught.exception).lower())


class TestSettlement(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_settlement_tab_carries_the_four_cards(self):
		data = emi.tab("settlements")
		for key in ("expected", "received", "pending", "disputed"):
			self.assertIn(key, data["cards"], key)

	def test_a_settlement_reads_the_applications_it_covers(self):
		name = frappe.db.get_value("Financier Settlement", {}, "name")
		if not name:
			self.skipTest("no settlement seeded")

		data = emi.settlement(name)
		self.assertEqual(len(data["rows"]),
		                 frappe.db.count("Financier Settlement Item", {"parent": name}))
		self.assertIn("Financier+Settlement+Statement",
		              data["print_url"].replace("%20", "+"))

	def test_a_settlement_with_nothing_outstanding_says_so(self):
		partner = frappe.db.get_value("Finance Partner", {"is_active": 1}, "name")
		if not partner:
			self.skipTest("no partners configured")
		if not frappe.has_permission("Financier Settlement", "create"):
			self.skipTest("this person cannot open a settlement")

		with self.assertRaises(frappe.ValidationError) as caught:
			emi.draft_settlement(partner, "2001-01-01", "2001-01-31")
		self.assertIn("nothing outstanding", str(caught.exception).lower())


class TestElsewhereInTheApp(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_customer_page_shows_a_customer_s_financing(self):
		from a3_retail.api import customer_desk

		customer = frappe.db.get_value("EMI Application", {"branch": "Kochi"}, "customer")
		if not customer:
			self.skipTest("no application to read")

		rows = customer_desk.tab(customer, "emi")
		self.assertTrue(rows)
		self.assertTrue(rows[0]["link"].startswith("/branch/emi?application="))

	def test_the_customer_page_lists_the_tab(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_customers.js")).read()
		self.assertIn('["emi", "EMI History"]', body)

	def test_the_counter_offers_finance_through_this_module(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_pos.js")).read()
		self.assertIn("a3_retail.api.emi.eligible_schemes", body)
		self.assertIn("a3_retail.api.emi.save_application", body)

	def test_the_reports_module_lists_the_emi_reports(self):
		from a3_retail.api import reports

		for name in ("EMI Sales by Branch", "Financier Performance", "EMI Scheme Performance",
		             "EMI Pending Approval", "EMI Commission and Subvention",
		             "Outstanding Financier Settlement", "EMI Cancellation Register",
		             "Salesperson EMI Sales"):
			self.assertIn(name, reports.DESCRIPTIONS, name)
			self.assertTrue(frappe.db.exists("Report", name), name)

	def test_every_emi_report_actually_runs(self):
		from frappe.desk.query_report import run as run_report

		for name in ("EMI Sales by Branch", "Financier Performance", "EMI Pending Approval",
		             "Outstanding Financier Settlement"):
			result = run_report(name, filters={"from_date": "2026-01-01", "to_date": "2026-12-31"},
			                    ignore_prepared_report=True)
			self.assertTrue(result["columns"], name)


class TestSchemeAndPartnerMasters(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_a_scheme_carries_its_own_document_requirements(self):
		"""Two schemes from one financier can want different paperwork."""
		self.assertTrue(frappe.get_meta("EMI Scheme").has_field("required_documents"))
		self.assertTrue(frappe.get_meta("EMI Scheme").has_field("documentation_fee"))
		self.assertTrue(frappe.get_meta("EMI Scheme").has_field("customer_subvention_percent"))

	def test_a_financier_is_configured_per_branch(self):
		meta = frappe.get_meta("Partner Branch Code")
		for field in ("branch", "merchant_id", "terminal_id", "dealer_code",
		              "settlement_account", "is_active"):
			self.assertTrue(meta.has_field(field), field)

	def test_the_application_records_what_the_customer_pays_today(self):
		meta = frappe.get_meta("EMI Application")
		for field in ("documentation_fee", "other_charges", "last_emi_date",
		              "customer_payable_today"):
			self.assertTrue(meta.has_field(field), field)

	def test_a_scheme_s_own_checklist_beats_the_partner_s(self):
		scheme = frappe.db.get_value("EMI Scheme", {"is_active": 1}, "name")
		document = frappe.db.get_value("EMI Document Type", {}, "name")
		if not scheme or not document:
			self.skipTest("no scheme or document type seeded")

		doc = frappe.get_doc("EMI Scheme", scheme)
		doc.set("required_documents", [{"document_type": document, "is_mandatory": 1}])
		doc.save(ignore_permissions=True)
		try:
			application = frappe.new_doc("EMI Application")
			application.branch = "Kochi"
			application.customer = frappe.db.get_value("Customer", {}, "name")
			application.employment_type = "Salaried"
			application.finance_partner = doc.finance_partner
			application.emi_scheme = doc.name
			application.populate_checklist()
			self.assertEqual([row.document_type for row in application.documents], [document])
		finally:
			doc.set("required_documents", [])
			doc.save(ignore_permissions=True)
