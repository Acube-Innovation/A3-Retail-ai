# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Selling guards and post-sale stamping (scope 2.1, 2.5, 12).

Three rules the counter must not be able to bypass:

1. A device line has to carry a serial number — the IMEI *is* the traceability.
2. A rate below the item's minimum selling price needs a Branch Manager.
3. Every invoice carries a sales person, otherwise incentives cannot be computed.

On submit the sold serial is stamped with the customer, invoice, branch and the
warranty dates that the whole warranty module then reads from.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate

from a3_retail.utils import setting
from a3_retail.utils.branch import get_user_branch

OVERRIDE_ROLES = {"Branch Manager", "A3 Retail Admin", "System Manager", "Accounts Manager"}


def _may_override(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(OVERRIDE_ROLES & set(frappe.get_roles(user)))


def validate(doc, method=None):
	"""Runs for both Sales Invoice and POS Invoice."""
	validate_device_serials(doc)
	validate_minimum_price(doc)
	ensure_sales_person(doc)
	flag_extended_warranty(doc)


def validate_device_serials(doc):
	"""A phone cannot leave the shop without its IMEI on the invoice."""
	if not setting("require_serial_on_device_sale", 1):
		return
	if doc.get("is_return"):
		return

	for row in doc.get("items") or []:
		if not frappe.get_cached_value("Item", row.item_code, "a3_is_device"):
			continue

		serials = _row_serials(row)
		if not serials:
			frappe.throw(
				_("Row {0}: {1} is a device — scan or enter its IMEI before saving.").format(
					row.idx, row.item_code
				),
				title=_("IMEI Required"),
			)

		if len(serials) != cint(abs(flt(row.qty))):
			frappe.throw(
				_("Row {0}: {1} IMEI(s) entered for a quantity of {2}.").format(
					row.idx, len(serials), cint(abs(flt(row.qty)))
				)
			)


def _row_serials(row) -> list[str]:
	"""Serial numbers on a row, whether typed or held in a serial/batch bundle."""
	raw = (row.get("serial_no") or "").replace(",", "\n")
	serials = [s.strip() for s in raw.split("\n") if s.strip()]
	if serials:
		return serials

	bundle = row.get("serial_and_batch_bundle")
	if bundle:
		return frappe.get_all(
			"Serial and Batch Entry", filters={"parent": bundle}, pluck="serial_no"
		)
	return []


def validate_minimum_price(doc):
	"""Selling below the floor price needs a manager (scope 2.2, P7)."""
	if not setting("enforce_min_selling_price", 1):
		return
	if doc.get("is_return") or _may_override():
		return

	for row in doc.get("items") or []:
		minimum = flt(frappe.get_cached_value("Item", row.item_code, "a3_min_selling_price"))
		if minimum and flt(row.rate) < minimum:
			frappe.throw(
				_("Row {0}: {1} cannot be sold below {2}. A Branch Manager must approve.").format(
					row.idx, row.item_code, frappe.format_value(minimum, {"fieldtype": "Currency"})
				),
				title=_("Below Minimum Price"),
			)


def ensure_sales_person(doc):
	"""Default the sales team from the POS user, then insist on one (scope 2.5)."""
	if not setting("require_sales_person", 1) or doc.get("is_return"):
		return
	if doc.get("sales_team"):
		return

	sales_person = _sales_person_for_user()
	if sales_person:
		doc.append("sales_team", {"sales_person": sales_person, "allocated_percentage": 100})
		return

	if doc.get("is_pos") or doc.doctype == "POS Invoice":
		frappe.throw(
			_("No Sales Person is linked to {0}. Incentives cannot be attributed.").format(
				frappe.session.user
			),
			title=_("Sales Person Required"),
		)


def _sales_person_for_user() -> str | None:
	employee = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
	)
	if not employee:
		return None
	return frappe.db.get_value("Sales Person", {"employee": employee, "enabled": 1}, "name")


def flag_extended_warranty(doc):
	"""Mark invoices that carry an EW plan — feeds the attach-rate incentive."""
	if not doc.meta.has_field("a3_ew_attached"):
		return

	doc.a3_ew_attached = 1 if any(
		frappe.get_cached_value("Item", row.item_code, "a3_is_ew_plan")
		for row in doc.get("items") or []
	) else 0


# ---------------------------------------------------------------------------
# On submit
# ---------------------------------------------------------------------------
def on_submit(doc, method=None):
	stamp_sold_serials(doc)
	refresh_customer_stats(doc)


def stamp_sold_serials(doc):
	"""Write the sale onto every device serial (scope 1.2)."""
	if doc.get("is_return"):
		return

	posting_date = getdate(doc.posting_date)

	for row in doc.get("items") or []:
		if not frappe.get_cached_value("Item", row.item_code, "a3_is_device"):
			continue

		months = cint(frappe.get_cached_value("Item", row.item_code, "a3_brand_warranty_months"))
		expiry = add_months(posting_date, months) if months else None

		for serial in _row_serials(row):
			if not frappe.db.exists("Serial No", serial):
				continue
			frappe.db.set_value(
				"Serial No",
				serial,
				{
					"a3_activation_date": posting_date,
					"a3_sales_invoice": doc.name,
					"a3_branch": doc.get("branch"),
					"a3_brand_warranty_expiry": expiry,
					"a3_warranty_state": "In Warranty" if expiry else "Out of Warranty",
					"customer": doc.customer,
				},
				update_modified=False,
			)


def refresh_customer_stats(doc):
	from a3_retail.api.customer import refresh_customer_stats as refresh

	if doc.customer:
		refresh(doc.customer)


def on_cancel(doc, method=None):
	"""Un-stamp the serials so a cancelled sale does not leave a device 'sold'."""
	for row in doc.get("items") or []:
		if not frappe.get_cached_value("Item", row.item_code, "a3_is_device"):
			continue
		for serial in _row_serials(row):
			if frappe.db.get_value("Serial No", serial, "a3_sales_invoice") != doc.name:
				continue
			frappe.db.set_value(
				"Serial No",
				serial,
				{
					"a3_activation_date": None,
					"a3_sales_invoice": None,
					"a3_brand_warranty_expiry": None,
					"a3_warranty_state": "Not Sold",
				},
				update_modified=False,
			)


# ---------------------------------------------------------------------------
# POS helpers (called from pos_extension.js)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def validate_pos_serial(item_code: str, serial_no: str, warehouse: str) -> dict:
	"""P1: the scanned IMEI must exist, be Active and sit in the POS warehouse."""
	from a3_retail.api import require_permission
	from a3_retail.utils.imei import normalize_imei

	require_permission("Serial No", "read")

	serial_no = normalize_imei(serial_no) or serial_no
	serial = frappe.db.get_value(
		"Serial No", serial_no, ["name", "item_code", "warehouse", "status"], as_dict=True
	)

	if not serial:
		return {"valid": False, "reason": _("IMEI {0} is not in stock.").format(serial_no)}
	if serial.item_code != item_code:
		return {"valid": False, "reason": _("IMEI {0} belongs to {1}.").format(serial_no, serial.item_code)}
	if serial.warehouse != warehouse:
		return {
			"valid": False,
			"reason": _("IMEI {0} is at {1}, not {2}.").format(serial_no, serial.warehouse, warehouse),
		}
	if serial.status != "Active":
		return {"valid": False, "reason": _("IMEI {0} is {1}.").format(serial_no, serial.status)}

	return {"valid": True, "serial_no": serial.name}


@frappe.whitelist()
def suggest_ew_plans(item_code: str) -> list[dict]:
	"""P4: extended-warranty plans that fit the device just added to the cart."""
	from a3_retail.api import require_permission

	require_permission("Item", "read")

	if not frappe.get_cached_value("Item", item_code, "a3_is_device"):
		return []

	if frappe.db.exists("DocType", "Extended Warranty Plan"):
		plans = frappe.get_all(
			"Extended Warranty Plan",
			filters={"is_active": 1},
			fields=["name", "plan_name", "plan_item", "plan_price", "coverage_type", "duration_months"],
		)
		if plans:
			return plans

	return frappe.get_all(
		"Item",
		filters={"a3_is_ew_plan": 1, "disabled": 0},
		fields=[
			"name as plan_item",
			"item_name as plan_name",
			"a3_ew_coverage_type as coverage_type",
			"a3_ew_duration_months as duration_months",
			"standard_rate as plan_price",
		],
	)


@frappe.whitelist()
def cross_branch_availability(item_code: str) -> list[dict]:
	"""P8: where else is this model in stock right now?"""
	from a3_retail.api.stock import availability_matrix

	return availability_matrix(item_code)
