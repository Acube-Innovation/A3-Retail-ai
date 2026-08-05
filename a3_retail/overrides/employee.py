# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Employee hooks — branch data isolation (scope 13.5).

When an Employee has both a `user_id` and a `branch`, that user gets User
Permission rows for Branch, the branch warehouses, the branch cost centers and
the branch POS Profile.

`apply_to_all_doctypes` is deliberately 0 with an explicit allowed-doctype list:
masters such as Item, Customer and Supplier are shared across branches, and a
blanket user permission would hide them.
"""

import frappe

# Which doctypes each user-permission value should restrict.
APPLICABLE_DOCTYPES = {
	"Branch": [
		"Branch Profile",
		"Service Job Card",
		"Service Estimate",
		"Stock Request",
		"Stock Damage Report",
		"Device Exchange",
		"EMI Application",
		"Warranty Registration",
		"Branch Visit Log",
		"Customer Feedback",
		"Courier Dispatch",
		"Call Task",
		"Technician Profile",
		"Demurrage Charge",
		"OEM Warranty Return",
		"Employee",
		"Sales Invoice",
		"POS Invoice",
		"Delivery Note",
		"Payment Entry",
		"Journal Entry",
		"Stock Entry",
	],
	"Warehouse": [
		"Stock Entry",
		"Stock Reconciliation",
		"Delivery Note",
		"Purchase Receipt",
		"Material Request",
		"Sales Invoice",
		"POS Invoice",
		"Stock Request",
		"Stock Damage Report",
	],
	"Cost Center": [
		"Sales Invoice",
		"POS Invoice",
		"Purchase Invoice",
		"Journal Entry",
		"Payment Entry",
		"Stock Entry",
		"Expense Claim",
	],
	"POS Profile": ["POS Invoice", "Sales Invoice"],
}

# Roles that must see every branch — no user permissions are written for them.
GLOBAL_ROLES = {"System Manager", "A3 Retail Admin", "Accounts Manager", "HR Manager", "Auditor"}


def on_update(doc, method=None):
	"""Refresh a user's branch permissions whenever their Employee record changes."""
	if not doc.get("user_id"):
		return

	if doc.status != "Active":
		clear_branch_permissions(doc.user_id)
		return

	if not doc.get("branch"):
		return

	sync_user_permissions(doc.user_id, doc.branch)


def on_trash(doc, method=None):
	if doc.get("user_id"):
		clear_branch_permissions(doc.user_id)


def sync_user_permissions(user: str, branch: str):
	"""Create/refresh the branch-scoped User Permission rows for `user`."""
	if not frappe.db.exists("User", user):
		return

	if GLOBAL_ROLES & set(frappe.get_roles(user)):
		# Head-office roles are branch-agnostic; leaving them unrestricted is the
		# whole point of the "consolidated view" requirement (scope 11.1).
		clear_branch_permissions(user)
		return

	profile_name = frappe.db.get_value("Branch Profile", {"branch": branch}, "name")
	targets: list[tuple[str, str]] = [("Branch", branch)]

	if profile_name:
		profile = frappe.get_cached_doc("Branch Profile", profile_name)
		for fieldname in (
			"default_warehouse",
			"service_warehouse",
			"damaged_warehouse",
			"used_device_warehouse",
			"transit_warehouse",
		):
			if profile.get(fieldname):
				targets.append(("Warehouse", profile.get(fieldname)))

		for fieldname in ("cost_center", "sales_cost_center", "service_cost_center"):
			if profile.get(fieldname):
				targets.append(("Cost Center", profile.get(fieldname)))

		if profile.pos_profile:
			targets.append(("POS Profile", profile.pos_profile))

	# `applicable_for` on User Permission is a single Link, so restricting N
	# doctypes means N rows per (allow, for_value) pair.
	wanted = {
		(allow, value, doctype)
		for allow, value in targets
		if value
		for doctype in APPLICABLE_DOCTYPES.get(allow, [])
		if frappe.db.exists("DocType", doctype)
	}
	_reconcile(user, wanted)


def _reconcile(user: str, wanted: set[tuple[str, str, str]]):
	"""Make the user's permissions for our managed doctypes match `wanted` exactly."""
	managed = list(APPLICABLE_DOCTYPES)
	existing = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": ["in", managed]},
		fields=["name", "allow", "for_value", "applicable_for"],
	)
	existing_map = {(row.allow, row.for_value, row.applicable_for): row.name for row in existing}

	for key, name in existing_map.items():
		if key not in wanted:
			frappe.delete_doc("User Permission", name, force=1, ignore_permissions=True)

	for allow, value, doctype in wanted:
		if (allow, value, doctype) in existing_map:
			continue
		perm = frappe.new_doc("User Permission")
		perm.user = user
		perm.allow = allow
		perm.for_value = value
		perm.apply_to_all_doctypes = 0
		perm.applicable_for = doctype
		perm.flags.ignore_permissions = True
		try:
			perm.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			pass


def clear_branch_permissions(user: str):
	for name in frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": ["in", list(APPLICABLE_DOCTYPES)]},
		pluck="name",
	):
		frappe.delete_doc("User Permission", name, force=1, ignore_permissions=True)


def resync_all(verbose: bool = True):
	"""Re-apply permissions for every active employee. Safe to re-run."""
	count = 0
	for employee in frappe.get_all(
		"Employee",
		filters={"status": "Active", "user_id": ["is", "set"], "branch": ["is", "set"]},
		fields=["name", "user_id", "branch"],
	):
		sync_user_permissions(employee.user_id, employee.branch)
		count += 1
	frappe.db.commit()
	if verbose:
		print(f"synced user permissions for {count} employees")
	return count
