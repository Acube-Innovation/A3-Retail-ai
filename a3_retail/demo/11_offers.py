"""Seed 11 — 7 seasonal offer campaigns and their pricing rules (scope 2.3)."""

import frappe
from frappe.utils import add_days, nowdate

# Dates are relative to today so the demo always has live campaigns.
# Priorities are distinct: ERPNext picks the highest-priority rule when several
# match the same item, and equal priorities raise MultiplePricingRuleConflict.
CAMPAIGNS = [
	{
		"campaign_name": "Onam Dhamaka 2026", "priority": 9, "offer_type": "Flat Percentage", "apply_on": "Brand",
		"rows": [{"brand": "Samsung", "discount_percentage": 8}],
		"discount_percentage": 8, "max_discount_amount": 4000, "budget_cap": 500000,
		"from_offset": -5, "to_offset": 25, "branches": [],
	},
	{
		"campaign_name": "Accessory Fest", "priority": 8, "offer_type": "Flat Percentage", "apply_on": "Item Group",
		"rows": [{"item_group": "Accessories", "discount_percentage": 15}],
		"discount_percentage": 15, "budget_cap": 75000,
		"from_offset": -10, "to_offset": 20, "branches": [],
	},
	{
		"campaign_name": "iPhone 15 Special Price", "priority": 7, "offer_type": "Special Price", "apply_on": "Item Code",
		"rows": [{"item_code": "MOB-APL-15-128-BLK", "special_rate": 64900}],
		"rate_or_discount": "Rate", "special_rate": 64900, "budget_cap": 200000,
		"from_offset": -2, "to_offset": 13, "branches": ["Kochi", "Thiruvananthapuram"],
	},
	{
		"campaign_name": "Buy Phone Get Tempered Glass", "priority": 6, "offer_type": "Buy X Get Y",
		"apply_on": "Item Group", "rows": [{"item_group": "Mobile Phones"}],
		"free_item": "ACC-TGL-A55", "free_qty": 1, "budget_cap": 50000,
		"from_offset": -10, "to_offset": 120, "branches": [],
	},
	{
		"campaign_name": "Diwali Exchange Bonus", "priority": 5, "offer_type": "Exchange Bonus",
		"apply_on": "Item Group", "rows": [{"item_group": "Mobile Phones"}],
		"exchange_bonus": 2000, "budget_cap": 300000,
		"from_offset": 60, "to_offset": 80, "branches": [],
	},
	{
		"campaign_name": "No Cost EMI - Redmi", "priority": 4, "offer_type": "No Cost EMI", "apply_on": "Brand",
		"rows": [{"brand": "Xiaomi"}], "subvention_percent": 6, "budget_cap": 150000,
		"from_offset": -8, "to_offset": 45, "branches": [],
	},
	{
		"campaign_name": "Weekend Combo Bundle", "priority": 3, "offer_type": "Bundle Price", "apply_on": "Item Code",
		"rows": [{"item_code": "MOB-SAM-A55-8-128-BLU", "special_rate": 41499}],
		"rate_or_discount": "Rate", "special_rate": 41499, "budget_cap": 40000,
		"from_offset": 3, "to_offset": 5, "branches": ["Kochi"],
	},
]


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	for spec in CAMPAIGNS:
		if frappe.db.exists("Seasonal Offer Campaign", {"campaign_name": spec["campaign_name"]}):
			continue

		doc = frappe.new_doc("Seasonal Offer Campaign")
		doc.campaign_name = spec["campaign_name"]
		doc.offer_type = spec["offer_type"]
		doc.company = company
		doc.apply_on = spec["apply_on"]
		doc.valid_from = add_days(nowdate(), spec["from_offset"])
		doc.valid_upto = add_days(nowdate(), spec["to_offset"])
		doc.rate_or_discount = spec.get("rate_or_discount", "Discount Percentage")
		doc.discount_percentage = spec.get("discount_percentage")
		doc.special_rate = spec.get("special_rate")
		doc.max_discount_amount = spec.get("max_discount_amount")
		doc.free_item = spec.get("free_item")
		doc.free_qty = spec.get("free_qty")
		doc.exchange_bonus = spec.get("exchange_bonus")
		doc.subvention_percent = spec.get("subvention_percent")
		doc.budget_cap = spec.get("budget_cap")
		doc.priority = spec["priority"]
		# Demo campaigns arrive pre-approved so the pricing rules exist.
		doc.requires_approval = 0

		for row in spec["rows"]:
			doc.append("items", row)
		for branch in spec.get("branches") or []:
			if frappe.db.exists("Branch", branch):
				doc.append("applicable_branches", {"branch": branch, "is_included": 1})

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
