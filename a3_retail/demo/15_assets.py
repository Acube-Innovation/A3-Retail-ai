"""Seed 15 — Twelve fixed assets with custody and calibration (scope 10.3).

Each asset is created, submitted and then issued to its custodian through an
Asset Movement, because the movement — not a field edit — is what the app treats
as the custody record.
"""

import frappe
from frappe.utils import add_days, getdate

from a3_retail.setup.hr import ensure_asset_categories

# asset_name, category, branch, custodian, purchase_date, amount, condition,
# next_calibration, asset_class, serial
ASSETS = [
	("Hot Air Rework Station - Quick 861DW", "Service Tools & Equipment", "Kochi", "Vishnu P",
	 "2023-05-10", 18500, "Good", "2026-11-10", "Service Tool", None),
	("Digital Microscope 7050", "Test & Measuring Instruments", "Kochi", "Vishnu P",
	 "2024-01-20", 12000, "Good", "2026-09-20", "Test Instrument", None),
	("DC Power Supply 30V/5A", "Test & Measuring Instruments", "Kochi", "Sajeer K",
	 "2023-08-01", 6500, "Good", "2026-10-01", "Test Instrument", None),
	("Ultrasonic Cleaner", "Service Tools & Equipment", "Kochi", "Sajeer K",
	 "2024-03-11", 9800, "Fair", None, "Service Tool", None),
	("POS Terminal - Kochi Counter 1", "Computers & POS Hardware", "Kochi", "Reshma K",
	 "2025-02-15", 42000, "Good", None, "IT Equipment", "POS-KCH-0001"),
	("Thermal Printer TVS RP3200", "Computers & POS Hardware", "Kochi", "Reshma K",
	 "2025-02-15", 8900, "Good", None, "IT Equipment", None),
	("Barcode Scanner Honeywell 1450g", "Computers & POS Hardware", "Kochi", "Vipin S",
	 "2025-02-15", 5400, "Good", None, "IT Equipment", None),
	("Delivery Scooter KL-07-AB-4421", "Vehicles (Delivery)", "Kochi", "Jithin Raj",
	 "2024-07-01", 92000, "Good", None, "Vehicle", "KL-07-AB-4421"),
	("Staff Phone - Redmi 12", "Mobile Phones (Staff Issue)", "Kochi", "Manoj Kumar",
	 "2025-06-01", 11999, "Good", None, "IT Equipment", "356938035643809"),
	("Display Counter Unit A", "Furniture & Display Fixtures", "Thiruvananthapuram", "Nikhil Das",
	 "2022-04-10", 65000, "Good", None, "Display Fixture", None),
	("Rework Station - TVM", "Service Tools & Equipment", "Thiruvananthapuram", "Rijo Thomas",
	 "2023-09-05", 17800, "Needs Repair", "2026-09-05", "Service Tool", None),
	("POS Terminal - Calicut", "Computers & POS Hardware", "Kozhikode", "Rafeeq M",
	 "2024-11-01", 39500, "Good", None, "IT Equipment", "POS-CLT-0001"),
]


DEFAULT_HSN = "84713010"
CATEGORY_HSN = {
	"Service Tools & Equipment": "82055990",
	"Test & Measuring Instruments": "90304000",
	"Computers & POS Hardware": "84713010",
	"Furniture & Display Fixtures": "94036000",
	"Vehicles (Delivery)": "87112019",
	"Mobile Phones (Staff Issue)": "85171300",
	"Air Conditioners & Electricals": "84151090",
	"Software Licences": "85234910",
}


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	ensure_asset_categories(company)

	for spec in ASSETS:
		name = _ensure_asset(spec, company)
		if name:
			_issue(name, spec[3], spec[4])


def _employee(name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": name}, "name")


def _location(branch: str, company: str) -> str | None:
	"""Assets need a Location when they are not assigned to an employee."""
	name = f"{branch} Premises"
	if frappe.db.exists("Location", name):
		return name
	doc = frappe.new_doc("Location")
	doc.location_name = name
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		return None
	return doc.name


def _ensure_asset(spec, company):
	(asset_name, category, branch, custodian, purchase_date, amount, condition,
	 next_calibration, asset_class, serial) = spec

	existing = frappe.db.get_value("Asset", {"asset_name": asset_name}, "name")
	if existing:
		return existing
	if not frappe.db.exists("Asset Category", category):
		return None

	item_code = _ensure_asset_item(asset_name, category, company)
	if not item_code:
		return None

	doc = frappe.new_doc("Asset")
	doc.asset_name = asset_name
	doc.item_code = item_code
	doc.asset_category = category
	doc.company = company
	doc.location = _location(branch, company)
	doc.purchase_date = purchase_date
	doc.available_for_use_date = purchase_date
	doc.gross_purchase_amount = amount
	doc.asset_quantity = 1
	doc.is_existing_asset = 1
	doc.calculate_depreciation = 0
	doc.a3_branch = branch
	doc.a3_asset_class = asset_class
	doc.a3_asset_condition = condition
	doc.a3_serial_or_imei = serial
	if next_calibration:
		doc.a3_is_calibration_required = 1
		doc.a3_next_calibration_date = next_calibration
		doc.a3_last_calibration_date = add_days(getdate(next_calibration), -365)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: asset {asset_name}")
		return None
	return doc.name


def _ensure_asset_item(asset_name: str, category: str, company: str) -> str | None:
	"""One non-stock fixed-asset Item per asset keeps ERPNext's Asset happy."""
	code = f"FA-{frappe.scrub(asset_name).upper().replace('_', '-')[:120]}"
	if frappe.db.exists("Item", code):
		return code

	doc = frappe.new_doc("Item")
	doc.item_code = code
	doc.item_name = asset_name[:140]
	doc.item_group = "All Item Groups"
	doc.is_fixed_asset = 1
	doc.is_stock_item = 0
	doc.asset_category = category
	# india_compliance makes the HSN mandatory on every Item, assets included.
	doc.gst_hsn_code = CATEGORY_HSN.get(category, DEFAULT_HSN)
	doc.include_item_in_manufacturing = 0
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: asset item {code}")
		return None
	return doc.name


def _issue(asset: str, custodian_name: str, transaction_date: str):
	"""Issue the asset to its custodian through an Asset Movement."""
	employee = _employee(custodian_name)
	if not employee:
		return
	if frappe.db.get_value("Asset", asset, "a3_assigned_employee") == employee:
		return

	company = frappe.db.get_value("Asset", asset, "company")
	doc = frappe.new_doc("Asset Movement")
	doc.company = company
	doc.purpose = "Issue"
	doc.transaction_date = f"{transaction_date} 10:00:00"
	doc.reference_doctype = None
	doc.a3_branch = frappe.db.get_value("Asset", asset, "a3_branch")
	doc.a3_acknowledged = 1
	doc.append("assets", {"asset": asset, "to_employee": employee})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: asset movement {asset}")
