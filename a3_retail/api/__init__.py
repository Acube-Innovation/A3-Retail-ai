"""Whitelisted API surface for A3 Retail.

Every endpoint in this package must perform an explicit permission check —
`frappe.whitelist()` alone only proves the caller is logged in. Use the
`require_permission` / `require_role` helpers below rather than hand-rolling
checks so the security audit in step 26 has one place to look.
"""

import frappe
from frappe import _


def require_permission(doctype: str, ptype: str = "read", doc=None):
	"""Throw PermissionError unless the session user has `ptype` on `doctype`."""
	if not frappe.has_permission(doctype, ptype=ptype, doc=doc):
		frappe.throw(
			_("Not permitted to {0} {1}").format(ptype, _(doctype)),
			frappe.PermissionError,
		)


def require_role(*roles: str):
	"""Throw PermissionError unless the user holds at least one of `roles`."""
	allowed = set(roles) | {"System Manager", "A3 Retail Admin"}
	if not (allowed & set(frappe.get_roles())):
		frappe.throw(
			_("This action requires one of these roles: {0}").format(", ".join(roles)),
			frappe.PermissionError,
		)


def require_branch_access(branch: str | None):
	"""Throw unless the user is allowed to act on `branch`."""
	from a3_retail.utils.permissions import get_permitted_branches

	if not branch:
		return
	permitted = get_permitted_branches()
	if permitted and branch not in permitted:
		frappe.throw(_("You do not have access to branch {0}").format(branch), frappe.PermissionError)


def parse_payload(payload) -> dict:
	"""Accept a dict or a JSON string from the client and return a dict."""
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid payload"))
	return payload


def stamp_cost_center(doc, cost_center: str | None):
	"""Put the branch's cost center on every cost-center field of a document.

	Two reasons, and they point the same way. A branch's postings belong to that
	branch's cost center, not to whatever default ERPNext reaches for while it is
	pricing the document. And `apply_strict_user_permissions` treats a *blank*
	link, or one outside the user's allowed set, as a violation — so an invoice
	that keeps "Main" on its tax rows becomes unreadable to the very counter that
	raised it, which breaks reading it back, allocating an advance against it and
	printing it.

	Every Cost Center link on the parent and on every child row, overwritten.
	"""
	if not cost_center:
		return

	def stamp(row):
		for field in row.meta.get_link_fields():
			if field.options == "Cost Center":
				row.set(field.fieldname, cost_center)

	stamp(doc)
	for table in doc.meta.get_table_fields():
		for row in doc.get(table.fieldname) or []:
			stamp(row)

