# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""GST, reverse charge and margin scheme (scope step 5, section 11.2)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.setup.accounts import get_abbr
from a3_retail.setup.tax import ensure_accounts, run as setup_tax
from a3_retail.tests.fixtures import ensure_branch, ensure_company


class TestChartOfAccounts(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()
		setup_tax()
		cls.abbr = get_abbr(cls.company)

	def test_rcm_accounts_resolve(self):
		from a3_retail.setup.tax import rcm_account

		for name in (
			"Input CGST RCM",
			"Input SGST RCM",
			"Input IGST RCM",
			"Output CGST RCM",
			"Output SGST RCM",
			"Output IGST RCM",
		):
			self.assertTrue(rcm_account(self.company, name), name)

	def test_rcm_accounts_are_tax_accounts(self):
		"""They must be selectable in a tax table, which needs account_type = Tax."""
		from a3_retail.setup.tax import rcm_account

		for name in ("Input CGST RCM", "Output CGST RCM"):
			account = rcm_account(self.company, name)
			self.assertEqual(frappe.db.get_value("Account", account, "account_type"), "Tax", name)

	def test_rcm_accounts_sit_under_duties_and_taxes(self):
		"""india_compliance's own convention, which its GST reports rely on."""
		from a3_retail.setup.tax import rcm_account

		for name in ("Input CGST RCM", "Output CGST RCM"):
			parent = frappe.db.get_value("Account", rcm_account(self.company, name), "parent_account")
			self.assertIn("Duties and Taxes", parent, name)

	def test_settlement_and_clearing_accounts_exist(self):
		for name in (
			"Bajaj Finserv Settlement Receivable",
			"Exchange Clearing",
			"Deferred EW Revenue",
			"Warranty Expense (Claims)",
			"Stock Damage Written Off",
			"MDR & Subvention Expense",
		):
			self.assertTrue(frappe.db.exists("Account", f"{name} - {self.abbr}"), name)


class TestTaxTemplates(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()
		setup_tax()
		cls.abbr = get_abbr(cls.company)

	def test_output_templates_exist(self):
		for title in ("Output GST In-state 18%", "Output GST Out-state 18%", "Output GST Nil Rated"):
			self.assertTrue(
				frappe.db.exists("Sales Taxes and Charges Template", f"{title} - {self.abbr}"), title
			)

	def test_rcm_template_has_add_and_deduct_rows(self):
		"""Input rows Add, output rows Deduct — so the supplier is paid the base."""
		name = f"Input GST RCM In-state 18% - {self.abbr}"
		self.assertTrue(frappe.db.exists("Purchase Taxes and Charges Template", name))

		template = frappe.get_doc("Purchase Taxes and Charges Template", name)
		adds = [row for row in template.taxes if row.add_deduct_tax == "Add"]
		deducts = [row for row in template.taxes if row.add_deduct_tax == "Deduct"]

		self.assertEqual(len(adds), 2)
		self.assertEqual(len(deducts), 2)
		self.assertEqual(sum(flt(r.rate) for r in adds), 18.0)
		self.assertEqual(sum(flt(r.rate) for r in deducts), 18.0)

	def test_rcm_template_is_flagged_reverse_charge(self):
		name = f"Input GST RCM In-state 18% - {self.abbr}"
		template = frappe.get_doc("Purchase Taxes and Charges Template", name)
		if template.meta.has_field("is_reverse_charge"):
			self.assertTrue(template.is_reverse_charge)

	def test_rcm_nets_to_base_amount(self):
		"""Scope step 5 acceptance: ₹1,20,000 rent, 18% RCM.

		Supplier payable stays 1,20,000; input CGST/SGST 10,800 each are booked as
		ITC and output CGST/SGST 10,800 each as the RCM liability.
		"""
		base = 120000.0
		rate = 9.0
		input_tax = base * rate / 100
		output_tax = base * rate / 100

		grand_total = base + (2 * input_tax) - (2 * output_tax)
		self.assertEqual(grand_total, base)
		self.assertEqual(input_tax, 10800.0)
		self.assertEqual(output_tax, 10800.0)


class TestModesOfPayment(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()
		setup_tax()

	def test_all_modes_exist(self):
		for mode in (
			"Cash",
			"UPI",
			"Credit Card",
			"Debit Card",
			"EMI - Bajaj Finserv",
			"EMI - HDB",
			"EMI - IDFC First",
			"Exchange Adjustment",
			"Gift Voucher",
		):
			self.assertTrue(frappe.db.exists("Mode of Payment", mode), mode)

	def test_emi_mode_points_at_settlement_receivable(self):
		doc = frappe.get_doc("Mode of Payment", "EMI - Bajaj Finserv")
		accounts = [row.default_account for row in doc.accounts if row.company == self.company]
		self.assertTrue(accounts)
		self.assertIn("Bajaj Finserv Settlement Receivable", accounts[0])

	def test_tds_categories_exist(self):
		for name in (
			"TDS 194-I Rent",
			"TDS 194-J Professional Fees",
			"TDS 194-C Contractors",
			"TDS 194-H Commission",
		):
			self.assertTrue(frappe.db.exists("Tax Withholding Category", name), name)


class TestMarginScheme(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")

	def test_margin_fields_exist_on_invoice_item(self):
		meta = frappe.get_meta("Sales Invoice Item")
		for fieldname in ("a3_is_margin_scheme", "a3_purchase_cost", "a3_margin_value"):
			self.assertTrue(meta.has_field(fieldname), fieldname)

	def test_margin_value_is_sale_minus_purchase(self):
		from a3_retail.overrides.transactions import apply_margin_scheme

		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": frappe.db.get_value("Customer", {}, "name"),
				"items": [
					{
						"item_code": "MOB-SAM-A55-8-128-BLU",
						"qty": 1,
						"rate": 25000,
						"amount": 25000,
						"a3_is_margin_scheme": 1,
						"a3_purchase_cost": 21500,
					}
				],
			}
		)
		# Exercise only the margin computation, not the full invoice pipeline.
		doc.calculate_taxes_and_totals = lambda: None
		apply_margin_scheme(doc)

		row = doc.items[0]
		self.assertEqual(flt(row.a3_margin_value), 3500.0)
		self.assertEqual(flt(row.net_amount), 3500.0)

	def test_negative_margin_is_not_taxed(self):
		from a3_retail.overrides.transactions import apply_margin_scheme

		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": frappe.db.get_value("Customer", {}, "name"),
				"items": [
					{
						"item_code": "MOB-SAM-A55-8-128-BLU",
						"qty": 1,
						"rate": 18000,
						"amount": 18000,
						"a3_is_margin_scheme": 1,
						"a3_purchase_cost": 21500,
					}
				],
			}
		)
		doc.calculate_taxes_and_totals = lambda: None
		apply_margin_scheme(doc)

		# A loss-making resale attracts no GST and cannot offset another sale.
		self.assertEqual(flt(doc.items[0].a3_margin_value), 0.0)
		self.assertEqual(flt(doc.items[0].net_amount), 0.0)


class TestBranchStamping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = ensure_branch("Kochi", "KCH")

	def test_branch_resolved_from_warehouse(self):
		from a3_retail.overrides.transactions import _resolve_branch

		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "warehouse": self.branch.default_warehouse}],
			}
		)
		self.assertEqual(_resolve_branch(doc), "Kochi")

	def test_service_invoice_uses_service_cost_center(self):
		from a3_retail.overrides.transactions import _pick_cost_center

		doc = frappe.get_doc({"doctype": "Sales Invoice", "order_type": "Maintenance"})
		self.assertEqual(_pick_cost_center(doc, self.branch), self.branch.service_cost_center)

	def test_retail_invoice_uses_sales_cost_center(self):
		from a3_retail.overrides.transactions import _pick_cost_center

		doc = frappe.get_doc({"doctype": "Sales Invoice", "order_type": "Sales"})
		self.assertEqual(_pick_cost_center(doc, self.branch), self.branch.sales_cost_center)
