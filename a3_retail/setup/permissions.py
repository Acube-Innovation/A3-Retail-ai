# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Role permission matrix (scope 13.2) applied as Custom DocPerm.

Data-driven on purpose: later build steps only append rows to `PERMISSION_MATRIX`
and re-run `run()`. `frappe.permissions.add_permission` copies the standard
DocPerms into Custom DocPerm the first time it touches a doctype, so adding a
role to a core doctype never silently drops ERPNext's own permissions.

Legend: C=create R=read U=write D=delete S=submit/cancel/amend
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

PTYPE_MAP = {
	"C": ("create",),
	"R": ("read",),
	"U": ("write",),
	"D": ("delete",),
	"S": ("submit", "cancel", "amend"),
	# "L" is select-only: the role may reference the record from a link field but
	# cannot open or list it. ERPNext checks for exactly this on Account.
	"L": ("select",),
}

# doctype -> {role: flags}
PERMISSION_MATRIX: dict[str, dict[str, str]] = {
	# ---------------------------------------------------------------- service
	"Service Job Card": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "CRUDS",
		"Sales Executive": "R",
		"Reception Executive": "CRUS",
		"Technician": "RU",
		"Store Keeper": "R",
		"Accounts Manager": "R",
		"Telecaller": "R",
	},
	"Service Estimate": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "CRUDS",
		"Sales Executive": "R",
		"Reception Executive": "R",
		"Technician": "CRU",
		"Accounts Manager": "R",
	},
	"Service Issue Type": {
		"A3 Retail Admin": "CRUD",
		"Service Manager": "CRUD",
		"Branch Manager": "R",
		"Technician": "R",
		"Reception Executive": "R",
	},
	"Service TAT Policy": {
		"A3 Retail Admin": "CRUD",
		"Service Manager": "CRUD",
		"Branch Manager": "R",
		"Technician": "R",
	},
	"Technician Profile": {
		"A3 Retail Admin": "CRUD",
		"Service Manager": "CRUD",
		"Branch Manager": "R",
		"Technician": "R",
	},
	"Device Model": {
		"A3 Retail Admin": "CRUD",
		"Service Manager": "CRUD",
		"Reception Executive": "CRU",
		"Sales Executive": "R",
		"Technician": "R",
		"Branch Manager": "R",
	},
	# ------------------------------------------------------------------ sales
	"Sales Invoice": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "R",
		"Sales Executive": "CRUS",
		"Reception Executive": "CRUS",
		"Accounts Manager": "CRUDS",
		"Accounts Executive": "CRU",
		"Auditor": "R",
	},
	"POS Invoice": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Sales Executive": "CRUS",
		"Reception Executive": "CRUS",
		"Accounts Manager": "CRUDS",
	},
	"Customer": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRUD",
		"Service Manager": "R",
		"Sales Executive": "CRU",
		"Reception Executive": "CRU",
		"Technician": "R",
		"Accounts Manager": "R",
		"Telecaller": "RU",
		"Helpdesk Agent": "RU",
	},
	"Item": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "R",
		"Service Manager": "R",
		"Sales Executive": "R",
		"Reception Executive": "R",
		"Technician": "R",
		"Store Keeper": "RU",
		"Accounts Manager": "R",
	},
	# Scope 11.1 keeps the chart of accounts away from the shop floor — but
	# pricing an invoice makes ERPNext resolve the customer's receivable account,
	# and it checks `select` when that is all the role holds. Select-only lets the
	# sale go through without opening a single account to a branch user.
	"Account": {
		"Branch Manager": "L",
		"Service Manager": "L",
		"Sales Executive": "L",
		"Reception Executive": "L",
		"Store Keeper": "L",
	},
	# The counter captures the delivery address with the customer (scope 2.1).
	"Address": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRU",
		"Service Manager": "CRU",
		"Sales Executive": "CRU",
		"Reception Executive": "CRU",
		"Accounts Manager": "CRUD",
		"Telecaller": "R",
	},
	"Contact": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRU",
		"Sales Executive": "CRU",
		"Reception Executive": "CRU",
		"Telecaller": "R",
	},
	# Submitting an invoice for a serialised phone makes ERPNext create the
	# bundle that records which handset left the shop.
	"Serial and Batch Bundle": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "CRUDS",
		"Sales Executive": "CRUS",
		"Reception Executive": "CRUS",
		"Store Keeper": "CRUDS",
		"Accounts Manager": "R",
	},
	# A counter cannot bill a phone without reading its IMEI, and cannot take one
	# in for repair without finding it (scope 2.2, step 12 P1).
	"Serial No": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRU",
		"Service Manager": "CRU",
		"Sales Executive": "RU",
		"Reception Executive": "RU",
		"Technician": "R",
		"Store Keeper": "CRUD",
		"Accounts Manager": "R",
		"Auditor": "R",
	},
	"Seasonal Offer Campaign": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CR",
		"Sales Executive": "R",
		"Reception Executive": "R",
		"Accounts Manager": "R",
		"Telecaller": "R",
	},
	"Device Exchange": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Sales Executive": "CRU",
		"Reception Executive": "CRU",
		"Accounts Manager": "R",
	},
	# -------------------------------------------------------------- inventory
	"Stock Entry": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "R",
		"Reception Executive": "R",
		"Technician": "CRUDS",
		# Scope 13.2 shows "–" for Store Keeper here, which contradicts the
		# Stock Request row and the role description ("stock entries, transfers,
		# receipts"). Granted deliberately — a store keeper who cannot post a
		# transfer cannot do the job.
		"Store Keeper": "CRUDS",
		"Accounts Manager": "R",
	},
	"Stock Request": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "CRU",
		"Sales Executive": "CRU",
		"Reception Executive": "CRU",
		"Technician": "CRU",
		"Store Keeper": "CRUDS",
	},
	"Stock Damage Report": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUS",
		"Service Manager": "R",
		"Technician": "CR",
		"Store Keeper": "CRU",
		"Accounts Manager": "R",
	},
	"Demurrage Charge": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRU",
		"Accounts Manager": "CRUDS",
		"Store Keeper": "R",
	},
	# ---------------------------------------------------------------- finance
	"EMI Application": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Sales Executive": "CRU",
		"EMI Coordinator": "CRUDS",
		"Reception Executive": "R",
		"Accounts Manager": "R",
	},
	"Finance Partner": {
		"A3 Retail Admin": "CRUD",
		"EMI Coordinator": "R",
		"Accounts Manager": "CRUD",
		"Sales Executive": "R",
	},
	"EMI Scheme": {
		"A3 Retail Admin": "CRUD",
		"EMI Coordinator": "CRU",
		"Sales Executive": "R",
		"Branch Manager": "R",
	},
	"Financier Settlement": {
		"A3 Retail Admin": "CRUDS",
		"Accounts Manager": "CRUDS",
		"EMI Coordinator": "R",
	},
	# --------------------------------------------------------------- warranty
	"Warranty Registration": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "R",
		"Service Manager": "RU",
		"Sales Executive": "R",
		"Reception Executive": "R",
		"Technician": "R",
		"Accounts Manager": "R",
		"Telecaller": "R",
	},
	"Extended Warranty Plan": {
		"A3 Retail Admin": "CRUD",
		"Service Manager": "R",
		"Sales Executive": "R",
		"Branch Manager": "R",
		"Reception Executive": "R",
	},
	"OEM Warranty Return": {
		"A3 Retail Admin": "CRUDS",
		"Service Manager": "CRUDS",
		"Store Keeper": "CRU",
		"Accounts Manager": "R",
	},
	# -------------------------------------------------------------------- crm
	"Branch Visit Log": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRUD",
		"Service Manager": "R",
		"Sales Executive": "CRUD",
		"Reception Executive": "CRUD",
		"Telecaller": "R",
	},
	"Customer Feedback": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRU",
		"Service Manager": "R",
		"Helpdesk Agent": "CRUD",
		"Telecaller": "CRU",
		"Reception Executive": "CRU",
	},
	"Issue": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "CRUD",
		"Service Manager": "CRUD",
		"Sales Executive": "R",
		"Reception Executive": "CRU",
		"Technician": "R",
		"Helpdesk Agent": "CRU",
	},
	"Call Task": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "R",
		"Telecaller": "CRU",
		"Helpdesk Agent": "R",
	},
	"Telecalling Campaign": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "R",
		"Telecaller": "R",
	},
	# --------------------------------------------------------------- logistics
	"Courier Dispatch": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "CRUDS",
		"Service Manager": "CRU",
		"Store Keeper": "CRUS",
		"Reception Executive": "CRU",
		"Accounts Manager": "R",
	},
	# --------------------------------------------------------------- accounts
	"Journal Entry": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "R",
		"Accounts Manager": "CRUDS",
		"Accounts Executive": "CRU",
		"Auditor": "R",
	},
	"Payment Entry": {
		"A3 Retail Admin": "CRUDS",
		# A manager who is standing at the counter takes the advance the counter
		# takes. Keeping this at read meant a one-desk branch could not book a
		# repair in at all — the ledger itself stays closed to them (11.1).
		"Branch Manager": "CRUS",
		"Reception Executive": "CRUS",
		"Accounts Manager": "CRUDS",
		"Accounts Executive": "CRU",
		"Auditor": "R",
	},
	# --------------------------------------------------------------------- hr
	"Incentive Calculation Run": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "R",
		"Accounts Manager": "R",
		"HR Manager": "CRUDS",
	},
	"Employee Incentive Scheme": {
		"A3 Retail Admin": "CRUD",
		"HR Manager": "CRUD",
		"Branch Manager": "R",
		"Accounts Manager": "R",
	},
	"Asset": {
		"A3 Retail Admin": "CRUDS",
		"Branch Manager": "R",
		"Service Manager": "R",
		"Technician": "R",
		"Store Keeper": "R",
		"Accounts Manager": "R",
		"HR Manager": "CRUDS",
	},
	# ------------------------------------------------------------ operations
	"Branch Profile": {
		"A3 Retail Admin": "CRUD",
		"Branch Manager": "R",
		"Service Manager": "R",
		"Sales Executive": "R",
		"Reception Executive": "R",
		"Store Keeper": "R",
		"Accounts Manager": "R",
		"HR Manager": "R",
		"Technician": "R",
	},
}

# Roles that get level-1 read on cost/margin fields (scope 13.5 field masking).
PERMLEVEL_1_READERS = ("A3 Retail Admin", "Branch Manager", "Accounts Manager")

# Doctypes carrying permlevel-1 fields.
PERMLEVEL_1_DOCTYPES = (
	"Service Job Card",
	"Job Card Labour",
	"Job Card Part",
	"EMI Application",
	"Stock Damage Report",
	"Stock Damage Item",
	"Stock Request Item",
	"Item",
	"Extended Warranty Plan",
)


def run(verbose: bool = False):
	"""Apply the whole matrix. Doctypes that do not exist yet are skipped."""
	applied = 0
	for doctype, roles in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role, flags in roles.items():
			if not frappe.db.exists("Role", role):
				continue
			_apply(doctype, role, flags)
			applied += 1

	_apply_permlevel_one()
	frappe.clear_cache()
	if verbose:
		print(f"applied {applied} role permissions")
	return applied


def _apply(doctype: str, role: str, flags: str, permlevel: int = 0):
	"""Grant exactly `flags` to `role` on `doctype` (never revokes other roles)."""
	if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": permlevel}):
		add_permission(doctype, role, permlevel)

	wanted = set()
	for flag in flags.upper():
		wanted.update(PTYPE_MAP.get(flag, ()))

	# Read is implied by every other permission — but not by select, which exists
	# precisely to let a role reference a record it may not open.
	if wanted - {"select"}:
		wanted.add("read")

	for ptype in ("read", "write", "create", "delete", "submit", "cancel", "amend", "select"):
		value = 1 if ptype in wanted else 0
		update_permission_property(doctype, role, permlevel, ptype, value, validate=False)

	desk = 1 if wanted - {"select"} else 0
	for ptype in ("report", "export", "print", "email", "share"):
		update_permission_property(doctype, role, permlevel, ptype, desk, validate=False)


def _apply_permlevel_one():
	"""Only managers read cost fields; everyone else sees them blank (scope 13.5)."""
	for doctype in PERMLEVEL_1_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for role in PERMLEVEL_1_READERS:
			if not frappe.db.exists("Role", role):
				continue
			_apply(doctype, role, "RU", permlevel=1)
