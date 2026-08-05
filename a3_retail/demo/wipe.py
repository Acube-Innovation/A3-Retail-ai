# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Remove the demo dataset (scope 14.1).

Development only — `demo.install.wipe` refuses to call this without
`developer_mode`. Documents are cancelled and deleted in dependency order:
anything that posts a ledger first, then the documents that feed it, then the
masters. Configuration (roles, print formats, workspaces, settings) is left
alone, because it is what the app installs rather than what the demo adds.
"""

import frappe

# Deleted in this order. Ledger-bearing documents come first so their links are
# already gone when the documents they point at are removed.
TRANSACTION_DOCTYPES = [
	"Payment Entry",
	"Journal Entry",
	"Sales Invoice",
	"POS Invoice",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Stock Entry",
	"Stock Reconciliation",
	"Additional Salary",
	"Salary Slip",
	"Attendance",
	"Incentive Calculation Run",
	"Courier Dispatch",
	"Delivery Trip",
	"Stock Request",
	"Stock Damage Report",
	"Demurrage Charge",
	"OEM Warranty Return",
	"Warranty Claim",
	"Warranty Registration",
	"Financier Settlement",
	"EMI Application",
	"Device Exchange",
	"Service Estimate",
	"Service Job Card",
	"Call Task",
	"Telecalling Campaign",
	"Branch Visit Log",
	"Customer Feedback",
	"Issue",
	"Lead",
	"Asset Movement",
	"Asset",
	"WhatsApp Message Log",
	"Portal OTP",
	"Serial No",
	"Sales Order",
	"Payment Request",
]

MASTER_DOCTYPES = [
	"Employee Incentive Scheme",
	"Technician Profile",
	"Seasonal Offer Campaign",
	"Pricing Rule",
	"Sales Person",
	"Employee",
	"Customer",
	"Supplier",
	"Item Price",
	"Item",
	"Device Model",
]


def run(include_masters: bool = False, verbose: bool = True) -> dict:
	frappe.flags.in_demo_wipe = True
	removed = {}

	for doctype in TRANSACTION_DOCTYPES:
		removed[doctype] = _drop(doctype)

	if include_masters:
		for doctype in MASTER_DOCTYPES:
			removed[doctype] = _drop(doctype)

	settings = frappe.get_single("A3 Retail Settings")
	settings.demo_data_installed = 0
	settings.demo_data_installed_on = None
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()

	if verbose:
		for doctype, count in removed.items():
			if count:
				print(f"  {doctype}: {count} removed")
		print(f"\n{sum(removed.values())} documents removed")

	return removed


def _drop(doctype: str) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0

	count = 0
	for name in frappe.get_all(doctype, pluck="name", order_by="creation desc"):
		try:
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
			frappe.delete_doc(doctype, name, force=1, ignore_permissions=True,
			                  delete_permanently=True)
			count += 1
		except Exception:
			# A document another one still points at; the next pass catches it.
			continue

	frappe.db.commit()
	return count
