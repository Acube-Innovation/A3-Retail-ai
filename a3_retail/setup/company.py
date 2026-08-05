# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Tenant bootstrap: Company, Fiscal Year and the ERPNext setup wizard.

Scope 0.9 defines the demo tenant. This module is idempotent — running it on a
site that is already set up is a no-op, so it is safe from patches and demo
seeding alike.
"""

import frappe
from frappe.utils import getdate

COMPANY_NAME = "Mobile World Retail Pvt Ltd"
COMPANY_ABBR = "MWR"
COUNTRY = "India"
CURRENCY = "INR"
TIMEZONE = "Asia/Kolkata"
FY_START = "2026-04-01"
FY_END = "2027-03-31"
GSTIN_HQ = "32AABCM1234K1Z5"


def is_setup_complete() -> bool:
	return bool(frappe.db.get_single_value("System Settings", "setup_complete")) and bool(
		frappe.db.exists("Company", COMPANY_NAME)
	)


def run(company_name: str = COMPANY_NAME, abbr: str = COMPANY_ABBR):
	"""Complete the ERPNext setup wizard for the A3 Retail tenant."""
	if is_setup_complete():
		_ensure_defaults(company_name)
		return company_name

	if frappe.db.exists("Company", company_name):
		_mark_setup_complete()
		_ensure_defaults(company_name)
		return company_name

	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	args = {
		"language": "English (United States)",
		"country": COUNTRY,
		"timezone": TIMEZONE,
		"currency": CURRENCY,
		"full_name": "Administrator",
		"email": frappe.session.user if "@" in frappe.session.user else "admin@example.com",
		"password": frappe.generate_hash(length=12),
		"company_name": company_name,
		"company_abbr": abbr,
		"company_tagline": "Mobile Retail & Service",
		"chart_of_accounts": "Standard with Numbers",
		"fy_start_date": FY_START,
		"fy_end_date": FY_END,
		"bank_account": "HDFC Current 4421",
		"domains": ["Retail"],
		"setup_demo": 0,
	}

	frappe.flags.in_setup_wizard = True
	try:
		setup_complete(args)
	finally:
		frappe.flags.in_setup_wizard = False

	_ensure_defaults(company_name)
	frappe.db.commit()
	return company_name


def _mark_setup_complete():
	frappe.db.set_single_value("System Settings", "setup_complete", 1)


def _ensure_defaults(company_name: str):
	"""Fill in the pieces the wizard leaves blank for our tenant."""
	_ensure_fiscal_year()
	_ensure_warehouse_types()

	if not frappe.db.get_single_value("Global Defaults", "default_company"):
		frappe.db.set_single_value("Global Defaults", "default_company", company_name)

	if not frappe.db.get_single_value("System Settings", "country"):
		frappe.db.set_single_value("System Settings", "country", COUNTRY)

	company = frappe.get_doc("Company", company_name)
	changed = False
	if not company.country:
		company.country = COUNTRY
		changed = True
	if not company.default_currency:
		company.default_currency = CURRENCY
		changed = True
	# Branch-wise advance liability needs advances booked to a separate account (scope 3.5).
	if company.meta.has_field("book_advance_payments_in_separate_party_account") and not company.get(
		"book_advance_payments_in_separate_party_account"
	):
		company.book_advance_payments_in_separate_party_account = 1
		changed = True
	if changed:
		company.flags.ignore_permissions = True
		company.save(ignore_permissions=True)

	settings = frappe.get_single("A3 Retail Settings")
	if not settings.default_company:
		settings.default_company = company_name
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)


def _ensure_fiscal_year():
	if frappe.db.exists("Fiscal Year", {"year_start_date": FY_START}):
		return
	fy = frappe.new_doc("Fiscal Year")
	fy.year = "2026-2027"
	fy.year_start_date = getdate(FY_START)
	fy.year_end_date = getdate(FY_END)
	fy.flags.ignore_permissions = True
	try:
		fy.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass


def _ensure_warehouse_types():
	"""ERPNext expects a `Transit` Warehouse Type for in-transit transfers (scope 6.2)."""
	for wtype in ("Transit", "Stores", "Work In Progress", "Finished Goods"):
		if not frappe.db.exists("Warehouse Type", wtype):
			doc = frappe.new_doc("Warehouse Type")
			doc.name = wtype
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
