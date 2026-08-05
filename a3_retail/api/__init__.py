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
