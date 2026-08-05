"""Seed 14 — Six employee incentive schemes (scope 10.2).

Targets sit on the scheme where every employee shares one, and on the employee
row where they differ (Vipin's ₹6,00,000 against Rafeeq's ₹4,00,000 in the July
demo run).
"""

import frappe

from a3_retail.setup.hr import ensure_salary_components

SALES_SLABS = [
	(0, 79.99, "% of Metric Value", 0),
	(80, 99.99, "% of Metric Value", 0.30),
	(100, 119.99, "% of Metric Value", 0.60),
	(120, 149.99, "% of Metric Value", 0.90),
	(150, 9999, "% of Metric Value", 1.25),
]

TECHNICIAN_SLABS = [
	(0, 39, "Per Unit", 0),
	(40, 59, "Per Unit", 60),
	(60, 79, "Per Unit", 90),
	(80, 9999, "Per Unit", 120),
]

SALES_SPIFFS = [
	{"brand": "Apple", "spiff_per_unit": 300, "remarks": "Apple devices"},
	{"brand": "Samsung", "min_value": 40000, "spiff_per_unit": 250, "remarks": "Samsung flagship"},
	{"item_group": "Extended Warranty Plans", "spiff_per_unit": 150, "remarks": "EW plan"},
]

# scheme_name, applicable_to, metric, target_type, target, slab_basis, slabs, spiffs, extras
SCHEMES = [
	{
		"scheme_name": "Sales Executive Monthly",
		"applicable_to": "Sales Executive",
		"designations": ["Sales Executive", "Senior Sales Executive"],
		"metric": "Net Sales Value",
		"target_type": "Absolute Target",
		"monthly_target": 600000,
		"slab_basis": "Achievement %",
		"minimum_qualification_percent": 80,
		"slabs": SALES_SLABS,
		"product_spiffs": SALES_SPIFFS,
		"attendance_gate_percent": 90,
		"csat_gate": 1,
		"min_csat": 4.0,
		"return_clawback": 1,
		"cap_amount": 25000,
		"payout_component": "Sales Incentive",
		"employee_targets": {"Vipin S": 600000, "Rafeeq M": 400000},
	},
	{
		"scheme_name": "Technician Monthly",
		"applicable_to": "Technician",
		"designations": ["Technician L1", "Technician L2", "Technician L3"],
		"metric": "Jobs Completed",
		"target_type": "Absolute Target",
		"monthly_target": 60,
		"slab_basis": "Metric Value",
		"minimum_qualification_percent": 0,
		"slabs": TECHNICIAN_SLABS,
		"product_spiffs": [],
		"attendance_gate_percent": 90,
		"quality_gate": 1,
		"max_qc_fail_percent": 5,
		"csat_gate": 1,
		"min_csat": 4.0,
		"cap_amount": 15000,
		"payout_component": "Technician Incentive",
	},
	{
		"scheme_name": "EW Attach Bonus",
		"applicable_to": "Custom (Employee List)",
		"employees": ["Vipin S", "Rafeeq M", "Reshma K", "Divya P", "Manoj Kumar"],
		"metric": "EW Plans Sold",
		"target_type": "No Target (Slab from Zero)",
		"slab_basis": "Metric Value",
		"slabs": [(0, 9999, "Per Unit", 150)],
		"product_spiffs": [],
		"bonus_rule": "Branch EW Attach Rate",
		"bonus_value": 2000,
		"bonus_threshold_percent": 25,
		"attendance_gate_percent": 85,
		"cap_amount": 10000,
		"payout_component": "Sales Incentive",
	},
	{
		"scheme_name": "EMI Conversion",
		"applicable_to": "Custom (Employee List)",
		"employees": ["Manoj Kumar", "Vipin S", "Rafeeq M"],
		"metric": "EMI Applications Disbursed",
		"target_type": "No Target (Slab from Zero)",
		"slab_basis": "Metric Value",
		"slabs": [(0, 9999, "Per Unit", 100)],
		"product_spiffs": [],
		"bonus_rule": "EMI Approved Within 24 Hours",
		"bonus_value": 150,
		"attendance_gate_percent": 90,
		"cap_amount": 12000,
		"payout_component": "Sales Incentive",
	},
	{
		"scheme_name": "Telecaller Monthly",
		"applicable_to": "Telecaller",
		"designations": ["Telecaller"],
		"metric": "Telecalling Conversions",
		"target_type": "Absolute Target",
		"monthly_target": 30,
		"slab_basis": "Metric Value",
		"slabs": [(0, 9999, "Per Unit", 40)],
		"product_spiffs": [],
		"attendance_gate_percent": 90,
		"cap_amount": 8000,
		"payout_component": "Sales Incentive",
	},
	{
		"scheme_name": "Branch Manager Quarterly",
		"applicable_to": "Branch Manager",
		"designations": ["Branch Manager"],
		"metric": "Net Sales Value",
		"target_type": "% of Branch Target",
		"monthly_target": 100,
		"frequency": "Quarterly",
		"slab_basis": "Achievement %",
		"minimum_qualification_percent": 100,
		"slabs": [
			(100, 119.99, "% of Metric Value", 0.15),
			(120, 9999, "% of Metric Value", 0.25),
		],
		"product_spiffs": [],
		"attendance_gate_percent": 90,
		"csat_gate": 1,
		"min_csat": 4.0,
		"cap_amount": 60000,
		"payout_component": "Sales Incentive",
	},
]


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	ensure_salary_components(company)

	for spec in SCHEMES:
		_ensure_scheme(spec)


def _employee(name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": name}, "name")


def _ensure_scheme(spec: dict):
	name = spec["scheme_name"]
	if frappe.db.exists("Employee Incentive Scheme", name):
		return name

	doc = frappe.new_doc("Employee Incentive Scheme")
	doc.scheme_name = name
	doc.applicable_to = spec["applicable_to"]
	doc.frequency = spec.get("frequency", "Monthly")
	doc.is_active = 1
	doc.metric = spec["metric"]
	doc.target_type = spec["target_type"]
	doc.monthly_target = spec.get("monthly_target", 0)
	doc.slab_basis = spec.get("slab_basis", "Achievement %")
	doc.minimum_qualification_percent = spec.get("minimum_qualification_percent", 0)
	doc.attendance_gate_percent = spec.get("attendance_gate_percent", 0)
	doc.quality_gate = spec.get("quality_gate", 0)
	doc.max_qc_fail_percent = spec.get("max_qc_fail_percent", 0)
	doc.csat_gate = spec.get("csat_gate", 0)
	doc.min_csat = spec.get("min_csat", 0)
	doc.return_clawback = spec.get("return_clawback", 0)
	doc.bonus_rule = spec.get("bonus_rule")
	doc.bonus_value = spec.get("bonus_value", 0)
	doc.bonus_threshold_percent = spec.get("bonus_threshold_percent", 0)
	doc.cap_amount = spec.get("cap_amount", 0)

	component = spec.get("payout_component")
	if component and frappe.db.exists("Salary Component", component):
		doc.payout_component = component

	for designation in spec.get("designations", []):
		if frappe.db.exists("Designation", designation):
			doc.append("designations", {"designation": designation})

	targets = spec.get("employee_targets", {})
	for employee_name in spec.get("employees", []) or list(targets):
		employee = _employee(employee_name)
		if employee:
			doc.append("employees", {"employee": employee,
			                         "monthly_target": targets.get(employee_name, 0)})

	for from_percent, to_percent, kind, value in spec["slabs"]:
		doc.append("slabs", {"from_percent": from_percent, "to_percent": to_percent,
		                     "incentive_type": kind, "value": value})

	for spiff in spec.get("product_spiffs", []):
		row = dict(spiff)
		if row.get("brand") and not frappe.db.exists("Brand", row["brand"]):
			row.pop("brand")
		if row.get("item_group") and not frappe.db.exists("Item Group", row["item_group"]):
			row.pop("item_group")
		if row.get("brand") or row.get("item_group") or row.get("item_code"):
			doc.append("product_spiffs", row)

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name
