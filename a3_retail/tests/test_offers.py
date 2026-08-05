# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Seasonal offer campaigns and generated Pricing Rules (scope step 13, 2.3)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.a3_retail_sales.doctype.seasonal_offer_campaign.seasonal_offer_campaign import (
	ACTIVE,
	EXPIRED,
	PAUSED,
	PENDING,
	SCHEDULED,
	active_exchange_bonus,
	refresh_campaign_statuses,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_company


def make_campaign(**overrides):
	company = ensure_company()
	doc = frappe.new_doc("Seasonal Offer Campaign")
	doc.campaign_name = overrides.pop("campaign_name", f"Test Offer {frappe.generate_hash(length=6)}")
	doc.offer_type = overrides.pop("offer_type", "Flat Percentage")
	doc.company = company
	doc.apply_on = overrides.pop("apply_on", "Brand")
	doc.valid_from = overrides.pop("valid_from", add_days(nowdate(), -1))
	doc.valid_upto = overrides.pop("valid_upto", add_days(nowdate(), 20))
	doc.discount_percentage = overrides.pop("discount_percentage", 8)
	doc.requires_approval = overrides.pop("requires_approval", 0)
	rows = overrides.pop("rows", [{"brand": "Samsung", "discount_percentage": 8}])
	branches = overrides.pop("branches", [])
	doc.update(overrides)

	for row in rows:
		doc.append("items", row)
	for branch in branches:
		doc.append("applicable_branches", {"branch": branch, "is_included": 1})

	doc.flags.ignore_permissions = True
	return doc


class TestCampaignValidation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_end_date_before_start_is_rejected(self):
		doc = make_campaign(valid_from=nowdate(), valid_upto=add_days(nowdate(), -5))
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_scope_needs_rows_unless_entire_catalogue(self):
		doc = make_campaign(rows=[])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_entire_catalogue_needs_no_rows(self):
		doc = make_campaign(apply_on="Entire Catalogue", rows=[])
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name)

	def test_row_must_carry_the_field_for_the_scope(self):
		doc = make_campaign(apply_on="Item Code", rows=[{"brand": "Samsung"}])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_discount_above_hundred_is_rejected(self):
		doc = make_campaign(discount_percentage=150)
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestPricingRuleGeneration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_submit_generates_a_pricing_rule(self):
		doc = make_campaign()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertEqual(doc.status, ACTIVE)
		self.assertTrue(doc.generated_rules)

		rule = frappe.get_doc("Pricing Rule", doc.generated_rules[0].pricing_rule)
		self.assertEqual(rule.apply_on, "Brand")
		self.assertEqual(flt(rule.discount_percentage), 8.0)
		self.assertTrue(rule.selling)

	def test_branch_scope_produces_one_rule_per_branch_warehouse(self):
		doc = make_campaign(branches=["Kochi"])
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		warehouses = {
			frappe.db.get_value("Pricing Rule", row.pricing_rule, "warehouse")
			for row in doc.generated_rules
		}
		self.assertTrue(warehouses)
		for warehouse in warehouses:
			self.assertEqual(frappe.db.get_value("Warehouse", warehouse, "custom_branch"), "Kochi")

	def test_special_price_generates_a_rate_rule(self):
		doc = make_campaign(
			offer_type="Special Price",
			apply_on="Item Code",
			rate_or_discount="Rate",
			special_rate=64900,
			rows=[{"item_code": "MOB-APL-15-128-BLK", "special_rate": 64900}],
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		rule = frappe.get_doc("Pricing Rule", doc.generated_rules[0].pricing_rule)
		self.assertEqual(rule.rate_or_discount, "Rate")
		self.assertEqual(flt(rule.rate), 64900.0)

	def test_buy_x_get_y_generates_a_product_rule(self):
		doc = make_campaign(
			offer_type="Buy X Get Y",
			apply_on="Item Group",
			rows=[{"item_group": "Mobile Phones"}],
			free_item="ACC-TGL-A55",
			free_qty=1,
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		rule = frappe.get_doc("Pricing Rule", doc.generated_rules[0].pricing_rule)
		self.assertEqual(rule.price_or_product_discount, "Product")
		self.assertEqual(rule.free_item, "ACC-TGL-A55")

	def test_cancel_removes_the_pricing_rules(self):
		doc = make_campaign()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()
		rules = [row.pricing_rule for row in doc.generated_rules]
		self.assertTrue(rules)

		doc.cancel()
		for rule in rules:
			self.assertFalse(frappe.db.exists("Pricing Rule", rule), rule)

	def test_approval_required_holds_the_campaign(self):
		doc = make_campaign(requires_approval=1)
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()

		self.assertEqual(doc.status, PENDING)
		self.assertFalse(doc.generated_rules)

	def test_approve_activates_and_generates(self):
		from a3_retail.a3_retail_sales.doctype.seasonal_offer_campaign.seasonal_offer_campaign import approve

		doc = make_campaign(requires_approval=1)
		doc.insert(ignore_permissions=True)
		doc.submit()

		result = approve(doc.name)
		self.assertEqual(result["status"], ACTIVE)

		doc.reload()
		self.assertTrue(doc.generated_rules)
		self.assertEqual(doc.approved_by, "Administrator")


class TestBudgetAndScheduler(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_consumption_accumulates(self):
		doc = make_campaign(budget_cap=10000)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.consume(3000)
		doc.reload()
		self.assertEqual(flt(doc.consumed_amount), 3000.0)

	def test_campaign_pauses_when_the_budget_is_exhausted(self):
		doc = make_campaign(budget_cap=5000)
		doc.insert(ignore_permissions=True)
		doc.submit()

		doc.consume(5000)
		doc.reload()
		self.assertEqual(doc.status, PAUSED)

		for row in doc.generated_rules:
			self.assertTrue(frappe.db.get_value("Pricing Rule", row.pricing_rule, "disable"))

	def test_scheduler_activates_a_scheduled_campaign(self):
		doc = make_campaign(valid_from=add_days(nowdate(), 2), valid_upto=add_days(nowdate(), 10))
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()
		self.assertEqual(doc.status, SCHEDULED)

		frappe.db.set_value("Seasonal Offer Campaign", doc.name, "valid_from", nowdate())
		refresh_campaign_statuses()

		doc.reload()
		self.assertEqual(doc.status, ACTIVE)

	def test_scheduler_expires_a_finished_campaign(self):
		doc = make_campaign()
		doc.insert(ignore_permissions=True)
		doc.submit()

		frappe.db.set_value("Seasonal Offer Campaign", doc.name, "valid_upto", add_days(nowdate(), -1))
		refresh_campaign_statuses()

		doc.reload()
		self.assertEqual(doc.status, EXPIRED)

	def test_active_exchange_bonus_reads_live_campaigns(self):
		doc = make_campaign(
			offer_type="Exchange Bonus",
			apply_on="Item Group",
			rows=[{"item_group": "Mobile Phones"}],
			exchange_bonus=2000,
		)
		doc.insert(ignore_permissions=True)
		doc.submit()

		self.assertGreaterEqual(active_exchange_bonus(), 2000.0)


class TestDemoCampaigns(FrappeTestCase):
	def test_seven_campaigns_are_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Seasonal Offer Campaign", {"docstatus": 1}), 7)

	def test_onam_campaign_has_pricing_rules(self):
		name = frappe.db.get_value("Seasonal Offer Campaign", {"campaign_name": "Onam Dhamaka 2026"}, "name")
		if not name:
			self.skipTest("demo campaigns not seeded")

		rules = frappe.get_all(
			"Offer Item Rule",
			filters={"parent": name, "parentfield": "generated_rules"},
			pluck="pricing_rule",
		)
		self.assertTrue(rules)
		self.assertEqual(flt(frappe.db.get_value("Pricing Rule", rules[0], "discount_percentage")), 8.0)
