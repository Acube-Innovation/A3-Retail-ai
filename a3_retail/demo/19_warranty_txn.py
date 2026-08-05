"""Seed 19 — warranty registrations, one claim and OEM returns (scope 14.2)."""

import frappe
from frappe.utils import add_days, nowdate


def run():
	_registrations()
	_oem_returns()


def _registrations():
	"""Registrations follow device sales, so back-fill any invoice that has none."""
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "is_return": 0, "remarks": ["like", "A3 demo %"]},
		pluck="name", limit=12,
	)
	from a3_retail.a3_retail_warranty.doctype.warranty_registration.warranty_registration import (
		register_from_invoice,
	)

	for name in invoices:
		invoice = frappe.get_doc("Sales Invoice", name)
		try:
			register_from_invoice(invoice)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: warranty for {name}")


def _oem_returns():
	if frappe.db.count("OEM Warranty Return", {"docstatus": 1}) >= 3:
		return

	supplier = frappe.db.get_value("Supplier", {"a3_supplier_category": "Device Distributor"},
	                               "name") or frappe.db.get_value("Supplier", {}, "name")
	if not supplier:
		return

	for index, branch in enumerate(("Kochi", "Thiruvananthapuram", "Kochi")):
		doc = frappe.new_doc("OEM Warranty Return")
		doc.supplier = supplier
		doc.branch = branch
		doc.return_type = "Defective Part Return"
		doc.dispatch_date = add_days(nowdate(), -(10 + index * 5))
		doc.docket_no = f"OEM-DEMO-{index + 1:03d}"
		doc.expected_credit_date = add_days(nowdate(), 15 - index * 5)
		part = frappe.db.get_value("Item", {"item_group": "Spare Parts"}, "name")
		if part:
			doc.append("items", {"item_code": part, "qty": 1 + index,
			                     "claim_value": 1200 * (index + 1)})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: OEM return {index}")
