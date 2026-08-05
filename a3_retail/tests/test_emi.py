# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""EMI applications, documents and financier settlement (scope step 15, doc 04)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import (
	APPROVED,
	DISBURSED,
	DOCS_PENDING,
	READY,
	SETTLED,
	EMIApplication,
	eligible_schemes,
)
from a3_retail.tests.fixtures import ensure_branch


def make_application(**overrides):
	branch = ensure_branch("Kochi", "KCH")
	customer = frappe.db.get_value("Customer", {"a3_mobile_no": "9847012345"}, "name") or frappe.db.get_value(
		"Customer", {}, "name"
	)

	doc = frappe.new_doc("EMI Application")
	doc.branch = branch.branch
	doc.customer = customer
	doc.application_date = nowdate()
	doc.employment_type = overrides.pop("employment_type", "Salaried")
	doc.monthly_income = 45000
	doc.pan_number = overrides.pop("pan_number", "ABCDE1234F")
	doc.aadhaar_last4 = "1234"
	doc.finance_partner = overrides.pop("finance_partner", "Bajaj Finserv")
	doc.emi_scheme = overrides.pop("emi_scheme", "Bajaj 6M No Cost")
	doc.invoice_total = overrides.pop("invoice_total", 39999)
	doc.down_payment = overrides.pop("down_payment", 4000)
	doc.append("items", {"item_code": "MOB-SAM-A55-8-128-BLU", "qty": 1, "rate": 39999})
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	return doc


def complete_documents(doc):
	for row in doc.get("documents") or []:
		if row.is_mandatory:
			row.is_received = 1
			row.attachment = "/files/dummy.pdf"
	return doc


class TestEMIMaths(FrappeTestCase):
	def test_no_cost_emi_is_loan_over_tenure(self):
		self.assertEqual(EMIApplication.compute_emi(36000, 6, 0), 6000.0)

	def test_interest_bearing_emi_exceeds_simple_division(self):
		emi = EMIApplication.compute_emi(17199, 12, 16)
		self.assertGreater(emi, 17199 / 12)
		self.assertLess(emi, 17199 / 12 * 1.2)

	def test_zero_tenure_is_zero(self):
		self.assertEqual(EMIApplication.compute_emi(10000, 0, 0), 0.0)

	def test_zero_loan_is_zero(self):
		self.assertEqual(EMIApplication.compute_emi(0, 12, 16), 0.0)


class TestEMIApplication(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_loan_is_invoice_less_down_payment(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)

		self.assertEqual(flt(doc.loan_amount), 35999.0)
		self.assertEqual(flt(doc.emi_amount), round(35999 / 6, 2))
		self.assertEqual(doc.tenure_months, 6)

	def test_costs_are_computed_from_partner_and_scheme(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)

		# Bajaj MDR 2.5%, scheme subvention 5%.
		self.assertEqual(flt(doc.mdr_amount), round(35999 * 0.025, 2))
		self.assertEqual(flt(doc.merchant_subvention_cost), round(35999 * 0.05, 2))
		self.assertEqual(
			flt(doc.net_realisable),
			round(35999 - flt(doc.mdr_amount) - flt(doc.merchant_subvention_cost), 2),
		)

	def test_invalid_pan_is_rejected(self):
		doc = make_application(pan_number="12345ABCDE")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_below_minimum_down_payment_is_rejected(self):
		# Bajaj 6M No Cost wants 10% down.
		doc = make_application(down_payment=100)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_invoice_below_scheme_range_is_rejected(self):
		doc = make_application(invoice_total=5000, down_payment=2000)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_brand_restriction_is_enforced(self):
		# IDFC's scheme only covers Apple; the cart is a Samsung.
		doc = make_application(
			finance_partner="IDFC First Bank",
			emi_scheme="IDFC 12M Manufacturer Subvented",
			invoice_total=69900,
			down_payment=0,
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_checklist_is_populated_from_the_partner(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)

		self.assertTrue(doc.documents)
		self.assertTrue(any(row.is_mandatory for row in doc.documents))

	def test_status_reflects_document_completeness(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.status, DOCS_PENDING)
		self.assertFalse(doc.all_documents_received)

		complete_documents(doc)
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.status, READY)
		self.assertTrue(doc.all_documents_received)

	def test_missing_documents_are_listed(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.missing_documents())

	def test_submit_without_documents_is_blocked(self):
		doc = make_application()
		doc.insert(ignore_permissions=True)
		doc.status = "Submitted to Financier"
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_approval_requires_partner_reference(self):
		doc = make_application()
		complete_documents(doc)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = APPROVED
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_approval_with_full_details_succeeds(self):
		doc = make_application()
		complete_documents(doc)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = APPROVED
		doc.partner_application_no = "BFL7789231"
		doc.approved_loan_amount = 35999
		doc.loan_account_number = "LN-0001"
		doc.save(ignore_permissions=True)

		self.assertEqual(doc.status, APPROVED)

	def test_rejection_needs_a_reason(self):
		doc = make_application()
		complete_documents(doc)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.status = "Rejected"
		self.assertRaises(frappe.ValidationError, doc.save)


class TestEligibleSchemes(FrappeTestCase):
	def test_schemes_are_filtered_by_ticket_size(self):
		schemes = eligible_schemes(invoice_total=39999)
		self.assertTrue(schemes)
		for scheme in schemes:
			self.assertLessEqual(flt(scheme["min_invoice_amount"]), 39999)

	def test_a_tiny_ticket_excludes_large_schemes(self):
		names = {s["name"] for s in eligible_schemes(invoice_total=6000)}
		self.assertNotIn("Bajaj 9M No Cost", names)

	def test_suggested_down_payment_and_emi_are_returned(self):
		schemes = eligible_schemes(finance_partner="Bajaj Finserv", invoice_total=39999)
		bajaj = next(s for s in schemes if s["name"] == "Bajaj 6M No Cost")
		self.assertEqual(flt(bajaj["suggested_down_payment"]), 3999.9)
		self.assertGreater(flt(bajaj["emi_amount"]), 0)

	def test_brand_filter_narrows_the_list(self):
		names = {s["name"] for s in eligible_schemes(invoice_total=69900, brand="Xiaomi")}
		# The IDFC scheme is Apple-only.
		self.assertNotIn("IDFC 12M Manufacturer Subvented", names)


class TestFinancierSettlement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _disbursed_application(self):
		doc = make_application()
		complete_documents(doc)
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.status = APPROVED
		doc.partner_application_no = "BFL-TEST"
		doc.approved_loan_amount = flt(doc.loan_amount)
		doc.loan_account_number = "LN-TEST"
		doc.save(ignore_permissions=True)
		doc.status = DISBURSED
		doc.disbursement_date = nowdate()
		doc.save(ignore_permissions=True)
		return doc

	def _settlement(self, application):
		from a3_retail.setup.accounts import get_abbr, get_company

		company = get_company()
		abbr = get_abbr(company)

		doc = frappe.new_doc("Financier Settlement")
		doc.finance_partner = "Bajaj Finserv"
		doc.from_date = add_days(nowdate(), -30)
		doc.to_date = nowdate()
		doc.company = company
		doc.bank_account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
		)
		doc.append("applications", {"emi_application": application.name})
		doc.flags.ignore_permissions = True
		return doc

	def test_get_pending_applications_finds_disbursed_ones(self):
		application = self._disbursed_application()

		doc = self._settlement(application)
		doc.applications = []
		doc.insert(ignore_permissions=True)
		added = doc.get_pending_applications()

		self.assertGreaterEqual(added, 1)
		self.assertIn(application.name, [row.emi_application for row in doc.applications])

	def test_totals_net_off_mdr_gst_and_subvention(self):
		application = self._disbursed_application()
		doc = self._settlement(application)
		doc.net_received = 0
		doc.insert(ignore_permissions=True)

		loan = flt(application.loan_amount)
		mdr = flt(application.mdr_amount)
		self.assertEqual(flt(doc.gross_amount), loan)
		self.assertEqual(flt(doc.mdr_amount), mdr)
		self.assertEqual(flt(doc.gst_on_mdr), round(mdr * 0.18, 2))

		expected = round(loan - mdr - round(mdr * 0.18, 2) - flt(application.merchant_subvention_cost), 2)
		self.assertEqual(flt(doc.net_expected), expected)

	def test_matching_receipt_reconciles_with_zero_variance(self):
		application = self._disbursed_application()
		doc = self._settlement(application)
		doc.insert(ignore_permissions=True)
		doc.net_received = flt(doc.net_expected)
		doc.save(ignore_permissions=True)

		self.assertEqual(flt(doc.variance), 0.0)
		self.assertEqual(doc.status, "Reconciled")

	def test_short_receipt_is_flagged_under_query(self):
		application = self._disbursed_application()
		doc = self._settlement(application)
		doc.insert(ignore_permissions=True)
		doc.net_received = flt(doc.net_expected) - 1500
		doc.save(ignore_permissions=True)

		self.assertEqual(flt(doc.variance), -1500.0)
		self.assertEqual(doc.status, "Variance - Under Query")

	def test_submit_posts_a_journal_and_settles_the_application(self):
		application = self._disbursed_application()
		doc = self._settlement(application)
		doc.insert(ignore_permissions=True)
		doc.net_received = flt(doc.net_expected)
		doc.save(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertTrue(doc.journal_entry)
		entry = frappe.get_doc("Journal Entry", doc.journal_entry)
		self.assertEqual(entry.docstatus, 1)
		# A journal entry always balances.
		self.assertEqual(
			round(sum(flt(r.debit_in_account_currency) for r in entry.accounts), 2),
			round(sum(flt(r.credit_in_account_currency) for r in entry.accounts), 2),
		)

		self.assertEqual(
			frappe.db.get_value("EMI Application", application.name, "status"), SETTLED
		)

	def test_reversed_period_is_rejected(self):
		application = self._disbursed_application()
		doc = self._settlement(application)
		doc.from_date = nowdate()
		doc.to_date = add_days(nowdate(), -10)
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestFinanceMasters(FrappeTestCase):
	def test_five_partners_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Finance Partner"), 5)

	def test_seven_schemes_seeded(self):
		self.assertGreaterEqual(frappe.db.count("EMI Scheme"), 7)

	def test_sixteen_document_types_seeded(self):
		self.assertGreaterEqual(frappe.db.count("EMI Document Type"), 16)

	def test_each_partner_has_a_unique_payment_mode(self):
		modes = frappe.get_all("Finance Partner", pluck="mode_of_payment")
		self.assertEqual(len(modes), len(set(modes)))

	def test_cost_fields_are_permlevel_gated(self):
		meta = frappe.get_meta("EMI Application")
		for fieldname in ("merchant_subvention_cost", "mdr_amount", "net_realisable"):
			self.assertEqual(meta.get_field(fieldname).permlevel, 1, fieldname)
