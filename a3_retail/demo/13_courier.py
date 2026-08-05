"""Seed 13 — 5 courier partners with rate cards (scope 7.3)."""

import frappe

# name, supplier, tat, services, tracking pattern, rates [(zone, service, to_kg, base, extra, tat)]
PARTNERS = [
	("Blue Dart Express", "Blue Dart Express Ltd", 2, ["Air", "Express"],
	 "https://www.bluedart.com/tracking?awb={awb}",
	 [("Within State", "Air", 0.5, 80, 40, 2), ("Metro", "Air", 0.5, 120, 55, 2)]),
	("DTDC", None, 3, ["Surface"], "https://www.dtdc.in/tracking?awb={awb}",
	 [("Within State", "Surface", 0.5, 55, 30, 3), ("Rest of India", "Surface", 0.5, 95, 45, 5)]),
	("Delhivery", None, 3, ["Surface", "Express"], "https://www.delhivery.com/track/?awb={awb}",
	 [("Within State", "Surface", 0.5, 60, 32, 3)]),
	("Professional Couriers", None, 4, ["Surface"], "https://www.tpcindia.com/track?awb={awb}",
	 [("Within State", "Surface", 0.5, 45, 25, 4), ("Metro", "Surface", 0.5, 90, 40, 5)]),
	("Own Rider", None, 1, ["Same Day"], None,
	 [("Within City", "Same Day", 5, 0, 0, 1)]),
]


def run():
	for name, supplier, tat, services, pattern, rates in PARTNERS:
		if frappe.db.exists("Courier Partner", name):
			continue

		doc = frappe.new_doc("Courier Partner")
		doc.partner_name = name
		doc.standard_tat_days = tat
		doc.tracking_url_pattern = pattern
		doc.free_days_before_demurrage = 1
		doc.is_active = 1
		if supplier and frappe.db.exists("Supplier", supplier):
			doc.supplier = supplier

		for service in services:
			doc.append("service_types", {"service_type": service})

		for zone, service, to_kg, base, extra, rate_tat in rates:
			doc.append(
				"rate_card",
				{
					"zone": zone,
					"service_type": service,
					"weight_slab_from": 0,
					"weight_slab_to": to_kg,
					"base_rate": base,
					"per_additional_500g": extra,
					"fuel_surcharge_percent": 10 if base else 0,
					"tat_days": rate_tat,
				},
			)

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
