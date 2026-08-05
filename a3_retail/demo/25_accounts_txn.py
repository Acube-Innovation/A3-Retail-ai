"""Seed 25 — purchase invoices, RCM, office expenses and payments (scope 14.2)."""

import frappe
from frappe.utils import add_days, nowdate

# description, amount, is_rcm — the last three are the reverse-charge cases
EXPENSES = [
	("Branch rent — Kochi", 65000, True),
	("Branch rent — Trivandrum", 48000, True),
	("Legal fees (unregistered advocate)", 15000, True),
	("Electricity — Kochi", 18500, False),
	("Internet and telephone", 6400, False),
	("Housekeeping", 9000, False),
]

MARKER = "A3 demo accounts"


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	_purchase_invoices(company)
	_payments(company)


def _purchase_invoices(company: str):
	if frappe.db.count("Purchase Invoice", {"remarks": MARKER, "docstatus": 1}) >= len(EXPENSES):
		return

	supplier = _expense_supplier(company)
	expense_account = _expense_account(company)
	if not supplier or not expense_account:
		return

	for index, (description, amount, is_rcm) in enumerate(EXPENSES):
		doc = frappe.new_doc("Purchase Invoice")
		doc.supplier = supplier
		doc.company = company
		doc.posting_date = add_days(nowdate(), -(index * 5 + 3))
		doc.set_posting_time = 1
		doc.due_date = add_days(nowdate(), 7)
		doc.branch = "Kochi"
		doc.remarks = MARKER
		if doc.meta.has_field("is_reverse_charge"):
			doc.is_reverse_charge = 1 if is_rcm else 0
		doc.append("items", {
			"item_name": description,
			"description": description,
			"qty": 1,
			"rate": amount,
			"expense_account": expense_account,
			"uom": "Nos",
		})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: purchase invoice {index}")


def _expense_supplier(company: str) -> str | None:
	name = "Local Services (Unregistered)"
	if frappe.db.exists("Supplier", name):
		return name

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = name
	doc.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	doc.country = "India"
	if doc.meta.has_field("gst_category"):
		doc.gst_category = "Unregistered"
	if doc.meta.has_field("a3_supplier_category"):
		doc.a3_supplier_category = "Utilities & Office"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 demo: expense supplier")
		return None
	return doc.name


def _expense_account(company: str) -> str | None:
	"""The numbered chart prefixes account names, so match on the label."""
	for label in ("Administrative Expenses", "Office Maintenance Expenses", "Miscellaneous Expenses"):
		name = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 0, "account_name": label},
			"name",
		)
		if name:
			return name
	return frappe.db.get_value(
		"Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
	)


def _payments(company: str):
	"""Collect a few outstanding sales invoices so receivables look worked."""
	if frappe.db.count("Payment Entry", {"remarks": ["like", f"%{MARKER}%"], "docstatus": 1}) >= 5:
		return

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "outstanding_amount": [">", 0], "is_return": 0,
		         "remarks": ["like", "A3 demo %"]},
		pluck="name", limit=8,
	)
	for name in invoices:
		try:
			entry = get_payment_entry("Sales Invoice", name)
			entry.mode_of_payment = "Cash"
			entry.reference_no = f"DEMO-{name}"
			entry.reference_date = nowdate()
			entry.remarks = MARKER
			entry.flags.ignore_permissions = True
			entry.insert(ignore_permissions=True)
			entry.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: payment for {name}")
