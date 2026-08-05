"""Seed 07 — opening stock with serial numbers across branches (scope 14.2)."""

import frappe
from frappe.utils import add_days, flt, nowdate

from a3_retail.utils.imei import luhn_check_digit

# item, branch, qty, rate. Serialised items get generated Luhn-valid IMEIs.
OPENING = [
	("MOB-SAM-A55-8-128-BLU", "Kochi", 8, 33000),
	("MOB-SAM-A55-8-128-BLU", "Thiruvananthapuram", 4, 33000),
	("MOB-APL-15-128-BLK", "Kochi", 5, 61000),
	("MOB-XIA-N13-6-128", "Kochi", 10, 14000),
	("MOB-XIA-N13-6-128", "Kozhikode", 6, 14000),
	("MOB-VIV-T3-8-128", "Kochi", 6, 18000),
	("TAB-SAM-S9FE", "Kochi", 3, 29000),
	("WEA-APL-SE2", "Kochi", 4, 21000),
	("ACC-CHG-25W-TC", "Kochi", 40, 900),
	("ACC-TGL-A55", "Kochi", 120, 120),
	("ACC-TGL-A55", "Thiruvananthapuram", 60, 120),
	("ACC-BUD-XIA", "Kochi", 25, 1500),
	("SPR-BAT-N13", "Kochi", 12, 800),
	("SPR-BAT-N13", "Thiruvananthapuram", 8, 800),
	("SPR-CHP-IC-PWR", "Kochi", 20, 400),
	("SPR-SPK-N13", "Kochi", 10, 550),
	("SPR-DSP-A55", "Kochi", 6, 6800),
	("SPR-DSP-A55", "Thiruvananthapuram", 4, 6800),
]

# Spare parts go to the Service Bay, everything else to the store.
SERVICE_ITEMS = {"SPR-BAT-N13", "SPR-DSP-A55", "SPR-CHP-IC-PWR", "SPR-SPK-N13"}

IMEI_PREFIX = "3591230"
_sequence = {"next": 100000}


def _next_imei() -> str:
	"""Deterministic, Luhn-valid IMEIs so re-seeding is stable."""
	while True:
		body = f"{IMEI_PREFIX}{_sequence['next']:07d}"[:14]
		_sequence["next"] += 1
		imei = body + str(luhn_check_digit(body))
		if not frappe.db.exists("Serial No", imei):
			return imei


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if frappe.db.exists("Stock Entry", {"remarks": "A3 Retail opening stock", "docstatus": 1}):
		return

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.company = company
	entry.posting_date = add_days(nowdate(), -30)
	entry.set_posting_time = 1
	entry.remarks = "A3 Retail opening stock"

	added = 0
	for item_code, branch, qty, rate in OPENING:
		warehouse = _warehouse_for(branch, item_code)
		if not warehouse or not frappe.db.exists("Item", item_code):
			continue

		row = {
			"item_code": item_code,
			"qty": flt(qty),
			"t_warehouse": warehouse,
			"basic_rate": flt(rate),
			"allow_zero_valuation_rate": 0,
		}

		if frappe.get_cached_value("Item", item_code, "has_serial_no"):
			row["serial_no"] = "\n".join(_next_imei() for _ in range(int(qty)))

		entry.append("items", row)
		added += 1

	if not added:
		return

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()


def _warehouse_for(branch: str, item_code: str) -> str | None:
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": branch},
		["default_warehouse", "service_warehouse"], as_dict=True,
	)
	if not profile:
		return None
	if item_code in SERVICE_ITEMS and profile.service_warehouse:
		return profile.service_warehouse
	return profile.default_warehouse
