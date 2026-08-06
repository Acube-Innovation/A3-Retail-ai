"""Seed 04 — Brands, Item Groups, Device Models, 19 Items, prices, reorder levels (scope 1.2)."""

import frappe

BRANDS = ["Samsung", "Apple", "Xiaomi", "Vivo", "Oppo", "Realme", "OnePlus", "Generic"]

# name, parent, is_group, default gst %, hsn
# The scope document quotes 4-digit chapter headings ("8517"); GST returns need
# the 6/8-digit tariff item, which india_compliance enforces, so these are the
# full codes for the same headings.
ITEM_GROUPS = [
	("Mobile Phones", "All Item Groups", 18, "85171300"),
	("Tablets", "All Item Groups", 18, "84713010"),
	("Smart Wearables", "All Item Groups", 18, "851762"),
	("Accessories", "All Item Groups", 18, "85177090"),
	("Spare Parts", "All Item Groups", 18, "85177010"),
	("Service Charges", "All Item Groups", 18, "998713"),
	("Extended Warranty Plans", "All Item Groups", 18, "997137"),
	("Used Devices", "All Item Groups", 18, "85171300"),
]

# item_code, item_name, group, is_stock, has_serial, is_device, brand, rate, warranty_months
ITEMS = [
	("MOB-SAM-A55-8-128-BLU", "Samsung Galaxy A55 5G 8/128 Blue", "Mobile Phones", 1, 1, 1, "Samsung", 39999, 12),
	("MOB-APL-15-128-BLK", "Apple iPhone 15 128GB Black", "Mobile Phones", 1, 1, 1, "Apple", 69900, 12),
	("MOB-XIA-N13-6-128", "Redmi Note 13 6/128", "Mobile Phones", 1, 1, 1, "Xiaomi", 16999, 12),
	("MOB-VIV-T3-8-128", "Vivo T3 5G 8/128", "Mobile Phones", 1, 1, 1, "Vivo", 21499, 12),
	("TAB-SAM-S9FE", "Samsung Tab S9 FE", "Tablets", 1, 1, 1, "Samsung", 34999, 12),
	("WEA-APL-SE2", "Apple Watch SE 2nd Gen", "Smart Wearables", 1, 1, 1, "Apple", 24900, 12),
	("ACC-CHG-25W-TC", "25W Type-C Charger", "Accessories", 1, 0, 0, "Samsung", 1499, 6),
	("ACC-TGL-A55", "Tempered Glass A55", "Accessories", 1, 0, 0, "Generic", 299, 0),
	("ACC-BUD-XIA", "Redmi Buds 5", "Accessories", 1, 0, 0, "Xiaomi", 2199, 6),
	("SPR-DSP-A55", "Display Assembly - Galaxy A55", "Spare Parts", 1, 1, 0, "Samsung", 8400, 3),
	("SPR-BAT-N13", "Battery - Redmi Note 13", "Spare Parts", 1, 0, 0, "Xiaomi", 1250, 3),
	("SPR-CHP-IC-PWR", "Power IC (Board Level)", "Spare Parts", 1, 0, 0, "Generic", 650, 0),
	("SPR-SPK-N13", "Speaker Module - Redmi Note 13", "Spare Parts", 1, 0, 0, "Xiaomi", 850, 3),
	("SRV-LAB-L1", "Service Labour - Level 1 (Software)", "Service Charges", 0, 0, 0, None, 300, 0),
	("SRV-LAB-L2", "Service Labour - Level 2 (Hardware)", "Service Charges", 0, 0, 0, None, 700, 0),
	("SRV-LAB-L3", "Service Labour - Level 3 (Board Level)", "Service Charges", 0, 0, 0, None, 1500, 0),
	("SRV-DIAG", "Diagnostic Charge", "Service Charges", 0, 0, 0, None, 200, 0),
	("EW-PLAN-12M", "Extended Warranty 12 Months", "Extended Warranty Plans", 0, 0, 0, None, 1999, 0),
	("EW-SCR-12M", "Screen Protection Plan 12 Months", "Extended Warranty Plans", 0, 0, 0, None, 2499, 0),
	("EW-COMBO-24M", "EW + Screen Combo 24 Months", "Extended Warranty Plans", 0, 0, 0, None, 4999, 0),
	("EW-ADP-12M", "Accidental Damage Plan 12 Months", "Extended Warranty Plans", 0, 0, 0, None, 3499, 0),
]

SERVICE_ITEM_MINUTES = {"SRV-LAB-L1": 30, "SRV-LAB-L2": 60, "SRV-LAB-L3": 120, "SRV-DIAG": 15}

EW_PLAN_SPECS = {
	"EW-PLAN-12M": (12, "Extended Warranty"),
	"EW-SCR-12M": (12, "Screen Protection"),
	"EW-COMBO-24M": (24, "Combo"),
	"EW-ADP-12M": (12, "Accidental & Liquid Damage"),
}

# Minimum selling price = list price less the maximum discount the shop allows.
MIN_PRICE_FACTOR = 0.92

DEVICE_MODELS = [
	("Galaxy A55", "Samsung", "Mobile", 2024, "SPR-DSP-A55", None),
	("iPhone 15", "Apple", "Mobile", 2023, None, None),
	("Redmi Note 13", "Xiaomi", "Mobile", 2024, None, "SPR-BAT-N13"),
	("Galaxy M14", "Samsung", "Mobile", 2023, None, None),
	("iPhone 12", "Apple", "Mobile", 2020, None, None),
	("Vivo T3", "Vivo", "Mobile", 2024, None, None),
	("Galaxy Tab S9 FE", "Samsung", "Tablet", 2023, None, None),
	("Watch SE 2nd Gen", "Apple", "Smartwatch", 2022, None, None),
]

# Which model each catalogue item actually is. The service counter needs this to
# open a job card, and the sales counter uses the model's launch year to decide
# what is new — an item with no model is a device nobody can service by name.
ITEM_DEVICE_MODEL = {
	"MOB-SAM-A55-8-128-BLU": "Samsung Galaxy A55",
	"MOB-APL-15-128-BLK": "Apple iPhone 15",
	"MOB-XIA-N13-6-128": "Xiaomi Redmi Note 13",
	"MOB-VIV-T3-8-128": "Vivo Vivo T3",
	"TAB-SAM-S9FE": "Samsung Galaxy Tab S9 FE",
	"WEA-APL-SE2": "Apple Watch SE 2nd Gen",
}

# item, warehouse suffix, reorder level, reorder qty
REORDER = [
	("MOB-SAM-A55-8-128-BLU", "Kochi Store", 5, 15),
	("MOB-XIA-N13-6-128", "Kochi Store", 8, 20),
	("ACC-TGL-A55", "Kochi Store", 25, 100),
	("SPR-BAT-N13", "Kochi Service Bay", 3, 10),
	("SPR-DSP-A55", "Kochi Service Bay", 2, 5),
]

PRICE_LIST = "Retail Kerala"


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	_brands()
	_item_groups()
	_price_list(company)
	_items(company)
	_device_models()
	_link_device_models()
	_reorder_levels(company)
	_artwork()


def _brands():
	for brand in BRANDS:
		if frappe.db.exists("Brand", brand):
			continue
		doc = frappe.new_doc("Brand")
		doc.brand = brand
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _item_groups():
	for name, parent, _gst, _hsn in ITEM_GROUPS:
		if frappe.db.exists("Item Group", name):
			continue
		doc = frappe.new_doc("Item Group")
		doc.item_group_name = name
		doc.parent_item_group = parent
		doc.is_group = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _price_list(company):
	if frappe.db.exists("Price List", PRICE_LIST):
		return
	doc = frappe.new_doc("Price List")
	doc.price_list_name = PRICE_LIST
	doc.selling = 1
	doc.currency = "INR"
	doc.enabled = 1
	doc.append("countries", {"country": "India"})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)


def _hsn_for(group):
	for name, _parent, _gst, hsn in ITEM_GROUPS:
		if name == group:
			return hsn
	return None


def _items(company):
	for code, name, group, is_stock, has_serial, is_device, brand, rate, warranty in ITEMS:
		if not frappe.db.exists("Item", code):
			doc = frappe.new_doc("Item")
			doc.item_code = code
			doc.item_name = name
			doc.item_group = group
			doc.stock_uom = "Nos"
			doc.is_stock_item = is_stock
			doc.has_serial_no = has_serial
			doc.include_item_in_manufacturing = 0
			doc.a3_is_device = is_device
			doc.a3_brand_warranty_months = warranty
			if brand:
				doc.brand = brand
			hsn = _hsn_for(group)
			if hsn and doc.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", hsn):
				doc.gst_hsn_code = hsn
			if code in SERVICE_ITEM_MINUTES:
				doc.a3_is_service_item = 1
				doc.a3_default_labour_minutes = SERVICE_ITEM_MINUTES[code]
			if code in EW_PLAN_SPECS:
				months, coverage = EW_PLAN_SPECS[code]
				doc.a3_is_ew_plan = 1
				doc.a3_ew_duration_months = months
				doc.a3_ew_coverage_type = coverage
				doc.a3_ew_claim_limit = 100
			if group == "Used Devices":
				doc.a3_is_margin_scheme = 1
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)

			# permlevel-1 fields cannot be set through the normal path.
			frappe.db.set_value(
				"Item", code, "a3_min_selling_price", round(rate * MIN_PRICE_FACTOR), update_modified=False
			)

		_item_price(code, rate)


def _item_price(item_code, rate):
	if frappe.db.exists("Item Price", {"item_code": item_code, "price_list": PRICE_LIST}):
		return
	doc = frappe.new_doc("Item Price")
	doc.item_code = item_code
	doc.price_list = PRICE_LIST
	doc.selling = 1
	doc.price_list_rate = rate
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)


def _device_models():
	for model, brand, device_type, year, display, battery in DEVICE_MODELS:
		name = f"{brand} {model}"
		if frappe.db.exists("Device Model", name):
			continue
		doc = frappe.new_doc("Device Model")
		doc.__newname = name
		doc.model_name = model
		doc.brand = brand
		doc.device_type = device_type
		doc.launch_year = year
		doc.standard_display_part = display
		doc.standard_battery_part = battery
		doc.avg_repair_tat_hours = 48
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _link_device_models():
	"""Point each handset at the model it is. Idempotent."""
	for item_code, model in ITEM_DEVICE_MODEL.items():
		if not frappe.db.exists("Item", item_code) or not frappe.db.exists("Device Model", model):
			continue
		if frappe.db.get_value("Item", item_code, "a3_device_model") == model:
			continue
		frappe.db.set_value("Item", item_code, "a3_device_model", model, update_modified=False)


def _reorder_levels(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	for item_code, warehouse_prefix, level, qty in REORDER:
		warehouse = f"{warehouse_prefix} - {abbr}"
		if not frappe.db.exists("Warehouse", warehouse):
			continue
		item = frappe.get_doc("Item", item_code)
		if any(r.warehouse == warehouse for r in item.get("reorder_levels", [])):
			continue
		item.append(
			"reorder_levels",
			{
				"warehouse": warehouse,
				"warehouse_reorder_level": level,
				"warehouse_reorder_qty": qty,
				"material_request_type": "Purchase",
			},
		)
		item.flags.ignore_permissions = True
		item.flags.ignore_mandatory = True
		item.save(ignore_permissions=True)


def _artwork():
	"""Hang the demo catalogue pictures once the items exist."""
	from a3_retail.demo import images

	images.run(verbose=False)

