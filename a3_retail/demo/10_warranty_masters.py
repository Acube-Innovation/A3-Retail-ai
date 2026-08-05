"""Seed 10 — 4 Extended Warranty Plans (scope 5.2)."""

import frappe

# name, item, coverage, months, starts from, price, max claims, cap %, deductible, window
PLANS = [
	("EW 12 Months Standard", "EW-PLAN-12M", "Extended Warranty", 12,
	 "After Brand Warranty Expiry", 1999, 2, 80, 0, 15),
	("Screen Protect 12M", "EW-SCR-12M", "Screen Protection", 12,
	 "Date of Purchase", 2499, 1, 100, 500, 7),
	("EW + Screen Combo 24M", "EW-COMBO-24M", "Combo (EW + Screen)", 24,
	 "Date of Purchase", 4999, 3, 100, 500, 15),
	("Accidental Damage 12M", "EW-ADP-12M", "Accidental & Liquid Damage", 12,
	 "Date of Purchase", 3499, 1, 80, 1000, 7),
]

COVERED = {
	"Extended Warranty": ["Display", "Battery", "Motherboard", "Camera", "Charging Port", "Speaker"],
	"Screen Protection": ["Display"],
	"Combo (EW + Screen)": ["Display", "Battery", "Motherboard", "Camera", "Charging Port",
	                        "Speaker", "Accidental Damage"],
	"Accidental & Liquid Damage": ["Display", "Body", "Water Damage", "Accidental Damage"],
}


def run():
	for (name, item, coverage, months, starts, price, claims, cap, deductible, window) in PLANS:
		if frappe.db.exists("Extended Warranty Plan", name) or not frappe.db.exists("Item", item):
			continue

		doc = frappe.new_doc("Extended Warranty Plan")
		doc.plan_name = name
		doc.plan_item = item
		doc.coverage_type = coverage
		doc.duration_months = months
		doc.starts_from = starts
		doc.plan_price = price
		doc.max_claims = claims
		doc.claim_value_cap_percent = cap
		doc.deductible_amount = deductible
		doc.sale_window_days = window
		doc.waiting_period_days = 15 if coverage == "Screen Protection" else 0
		doc.is_active = 1

		for component in COVERED.get(coverage, []):
			doc.append("coverage_items", {"component": component, "is_covered": 1,
			                              "coverage_percent": 100})

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
