# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Idempotent post-install / post-migrate defaults.

Everything here is safe to re-run: each block guards with `frappe.db.exists`.
Later steps append their own `_setup_*` function and call it from `run()`.
"""

import frappe

# Transaction doctypes that must carry the Branch dimension (scope 1.1).
# ERPNext's Accounting Dimension Detail is keyed by *company*, not by doctype, so
# per-doctype enforcement is done by our own branch-stamping hooks; this list is
# what those hooks iterate over.
BRANCH_DIMENSION_DOCTYPES = [
	"Sales Invoice",
	"Purchase Invoice",
	"Journal Entry",
	"Payment Entry",
	"Stock Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Sales Order",
	"Purchase Order",
	"Expense Claim",
	"Material Request",
	"POS Invoice",
	"Stock Reconciliation",
]


def run():
	"""Entry point called from after_install and after_migrate."""
	_setup_settings_defaults()
	_setup_system_settings()
	_setup_accounting_dimension()
	frappe.db.commit()


def _setup_settings_defaults():
	"""Seed A3 Retail Settings the first time it is materialised."""
	settings = frappe.get_single("A3 Retail Settings")

	if not settings.default_company:
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		if company:
			settings.default_company = company

	if not settings.get("ew_reminder_days"):
		for days, description in ((30, "First renewal nudge"), (15, "Second nudge"), (7, "Last chance"), (-7, "Win-back after expiry")):
			settings.append("ew_reminder_days", {"days_before": days, "description": description})

	if not settings.get("allow_imei_override_roles"):
		settings.append("allow_imei_override_roles", {"role": "A3 Retail Admin"})

	if not settings.get("allow_discount_roles"):
		settings.append("allow_discount_roles", {"role": "Branch Manager"})

	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)


def _setup_system_settings():
	"""Branch isolation relies on strict user permissions (scope 13.5)."""
	if not frappe.db.get_single_value("System Settings", "apply_strict_user_permissions"):
		frappe.db.set_single_value("System Settings", "apply_strict_user_permissions", 1)


def _setup_accounting_dimension():
	"""Create the Branch accounting dimension used for branch-wise P&L (ADR-01)."""
	if not frappe.db.exists("DocType", "Accounting Dimension"):
		return
	if not frappe.db.exists("DocType", "Branch"):
		return

	if frappe.db.exists("Accounting Dimension", {"document_type": "Branch"}):
		_refresh_dimension_details()
		return

	dimension = frappe.new_doc("Accounting Dimension")
	dimension.document_type = "Branch"
	dimension.label = "Branch"
	dimension.flags.ignore_permissions = True
	try:
		dimension.insert(ignore_permissions=True)
	except frappe.exceptions.DuplicateEntryError:
		pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: could not create Branch dimension")
		return

	_refresh_dimension_details()


def _refresh_dimension_details():
	"""Give every Company a Branch dimension default row.

	`Accounting Dimension Detail` holds at most one row per company — ERPNext
	throws "Company added more than once" otherwise — so the row carries the
	company-wide default and the mandatory flags. Per-doctype coverage of the
	list in scope 1.1 is enforced by our branch-stamping hooks instead.
	"""
	name = frappe.db.get_value("Accounting Dimension", {"document_type": "Branch"}, "name")
	if not name:
		return

	dimension = frappe.get_doc("Accounting Dimension", name)
	existing = {row.company for row in dimension.get("dimension_defaults", [])}

	changed = False
	for company in frappe.get_all("Company", pluck="name"):
		if company in existing:
			continue
		dimension.append(
			"dimension_defaults",
			{
				"company": company,
				"reference_document": "Branch",
				"mandatory_for_bs": 0,
				# Turned on by setup.accounts once branch stamping is live (step 5),
				# so postings made before any Branch exists are not blocked.
				"mandatory_for_pl": 0,
			},
		)
		changed = True

	if changed:
		dimension.flags.ignore_permissions = True
		dimension.save(ignore_permissions=True)
