# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Serial No hooks — the IMEI register (ADR-02, scope 1.2).

Naming a device's Serial No as its IMEI gives free global uniqueness and makes
`frappe.db.exists("Serial No", imei)` the fastest possible lookup at the counter.
"""

import frappe
from frappe import _
from frappe.utils import add_months, getdate, nowdate

from a3_retail.utils import commit_if_not_testing

from a3_retail.utils.imei import enforce_imei, normalize_imei

WARRANTY_STATES = ("Not Sold", "In Warranty", "In Extended Warranty", "Out of Warranty", "Void")


def is_device(item_code: str | None) -> bool:
	if not item_code:
		return False
	return bool(frappe.get_cached_value("Item", item_code, "a3_is_device"))


def before_insert(doc, method=None):
	"""Name a device serial after its IMEI and validate the check digit."""
	doc.a3_imei_1 = normalize_imei(doc.get("a3_imei_1"))
	doc.a3_imei_2 = normalize_imei(doc.get("a3_imei_2"))

	if not is_device(doc.item_code):
		return

	# The scan may arrive in either field depending on where it came from.
	if not doc.a3_imei_1 and doc.serial_no:
		doc.a3_imei_1 = normalize_imei(doc.serial_no)

	if not doc.a3_imei_1:
		frappe.throw(_("IMEI 1 is required for device {0}.").format(doc.item_code))

	override = bool(doc.get("a3_imei_override"))
	doc.a3_imei_1 = enforce_imei(doc.a3_imei_1, "IMEI 1", override=override)
	if doc.a3_imei_2:
		doc.a3_imei_2 = enforce_imei(doc.a3_imei_2, "IMEI 2", override=override)

	# Serial No is named by its `serial_no` field; setting it names the record.
	doc.serial_no = doc.a3_imei_1
	doc.name = doc.a3_imei_1

	if not doc.a3_warranty_state:
		doc.a3_warranty_state = "Not Sold"


def validate(doc, method=None):
	doc.a3_imei_1 = normalize_imei(doc.get("a3_imei_1"))
	doc.a3_imei_2 = normalize_imei(doc.get("a3_imei_2"))

	if doc.a3_imei_1 and doc.a3_imei_2 and doc.a3_imei_1 == doc.a3_imei_2:
		frappe.throw(_("IMEI 1 and IMEI 2 cannot be the same."))

	_validate_imei_uniqueness(doc)
	compute_warranty_dates(doc)


def _validate_imei_uniqueness(doc):
	"""IMEI 1 must be globally unique — it is how a device is identified."""
	if not doc.a3_imei_1:
		return
	clash = frappe.db.get_value(
		"Serial No", {"a3_imei_1": doc.a3_imei_1, "name": ["!=", doc.name]}, "name"
	)
	if clash:
		frappe.throw(_("IMEI {0} is already registered on Serial No {1}.").format(doc.a3_imei_1, clash))


def compute_warranty_dates(doc):
	"""Brand warranty expiry = activation date + the item's warranty months."""
	if not doc.a3_activation_date:
		return

	months = frappe.get_cached_value("Item", doc.item_code, "a3_brand_warranty_months") or 0
	if months and not doc.a3_brand_warranty_expiry:
		doc.a3_brand_warranty_expiry = add_months(getdate(doc.a3_activation_date), int(months))


def resolve_warranty_state(serial: dict | None) -> str:
	"""Pure function so it can be unit-tested without touching the database."""
	if not serial:
		return "Not Sold"
	if serial.get("a3_warranty_state") == "Void":
		return "Void"
	if not serial.get("a3_activation_date"):
		return "Not Sold"

	today = getdate(nowdate())
	ew_expiry = serial.get("a3_ew_expiry")
	brand_expiry = serial.get("a3_brand_warranty_expiry")

	if brand_expiry and getdate(brand_expiry) >= today:
		return "In Warranty"
	if ew_expiry and getdate(ew_expiry) >= today:
		return "In Extended Warranty"
	return "Out of Warranty"


def recompute_warranty_state():
	"""Daily scheduler — refresh `a3_warranty_state` on every sold serial (scope 1.2)."""
	serials = frappe.get_all(
		"Serial No",
		filters={"a3_activation_date": ["is", "set"], "a3_warranty_state": ["!=", "Void"]},
		fields=[
			"name",
			"a3_warranty_state",
			"a3_activation_date",
			"a3_brand_warranty_expiry",
			"a3_ew_expiry",
		],
	)

	updated = 0
	for serial in serials:
		state = resolve_warranty_state(serial)
		if state != serial.a3_warranty_state:
			frappe.db.set_value("Serial No", serial.name, "a3_warranty_state", state, update_modified=False)
			updated += 1

	commit_if_not_testing()
	return updated


@frappe.whitelist()
def lookup_imei(imei: str) -> dict:
	"""Counter lookup: everything known about a device, by IMEI."""
	from a3_retail.api import require_permission

	require_permission("Serial No", "read")

	imei = normalize_imei(imei)
	if not imei:
		return {"found": False}

	name = frappe.db.get_value("Serial No", {"a3_imei_1": imei}, "name") or (
		imei if frappe.db.exists("Serial No", imei) else None
	)
	if not name:
		return {"found": False, "imei": imei}

	serial = frappe.get_doc("Serial No", name)
	item = frappe.get_cached_doc("Item", serial.item_code)

	return {
		"found": True,
		"imei": serial.a3_imei_1 or serial.name,
		"serial_no": serial.name,
		"item_code": serial.item_code,
		"item_name": item.item_name,
		"brand": item.brand,
		"device_model": item.a3_device_model,
		"warehouse": serial.warehouse,
		"status": serial.status,
		"customer": serial.customer,
		"sold_by_us": bool(serial.a3_sales_invoice),
		"purchase_date": serial.a3_activation_date,
		"sales_invoice": serial.a3_sales_invoice,
		"brand_warranty_expiry": serial.a3_brand_warranty_expiry,
		"ew_expiry": serial.a3_ew_expiry,
		"warranty_state": serial.a3_warranty_state,
		"service_count": serial.a3_service_count,
		"last_service_date": serial.a3_last_service_date,
	}
