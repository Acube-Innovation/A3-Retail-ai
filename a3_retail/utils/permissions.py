"""Branch-scoped permission query conditions.

Frappe calls `permission_query_conditions` hooks with `(user)` only, so we build
one closure per doctype from `BRANCH_SCOPED_DOCTYPES` and register them in
hooks.py. The list is data-driven — later steps only append to it.
"""

import frappe

# doctype -> fieldname holding the Branch link.
BRANCH_SCOPED_DOCTYPES = {
	"Branch Profile": "branch",
	"Service Job Card": "branch",
	"Service Estimate": "branch",
	"Technician Profile": "branch",
	"Stock Request": "requesting_branch",
	"Stock Damage Report": "branch",
	"Demurrage Charge": "branch",
	"Device Exchange": "branch",
	"EMI Application": "branch",
	"Warranty Registration": "branch",
	"OEM Warranty Return": "branch",
	"Branch Visit Log": "branch",
	"Customer Feedback": "branch",
	"Call Task": "branch",
	"Courier Dispatch": "branch",
	"Incentive Calculation Run": "branch",
	"WhatsApp Message Log": "branch",
}

# Roles that always see every branch.
UNRESTRICTED_ROLES = {
	"System Manager",
	"A3 Retail Admin",
	"Accounts Manager",
	"HR Manager",
	"Auditor",
}


def user_is_unrestricted(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def get_permitted_branches(user: str | None = None) -> list[str]:
	"""Branches visible to the user; empty list means 'all'."""
	from a3_retail.utils.branch import get_user_branches

	if user_is_unrestricted(user):
		return []
	return get_user_branches(user)


def build_branch_condition(doctype: str, branch_field: str, user: str | None = None) -> str:
	"""SQL condition restricting a list view to the user's branches."""
	branches = get_permitted_branches(user)
	if not branches:
		return ""

	table = f"`tab{doctype}`"
	values = ", ".join(frappe.db.escape(b) for b in branches)
	# Rows without a branch stay visible so drafts created before stamping are not lost.
	return f"({table}.`{branch_field}` in ({values}) or ifnull({table}.`{branch_field}`, '') = '')"


def get_permission_query_conditions_factory(doctype: str, branch_field: str):
	"""Return a `(user)` callable suitable for hooks.permission_query_conditions."""

	def _conditions(user: str | None = None) -> str:
		return build_branch_condition(doctype, branch_field, user)

	_conditions.__name__ = f"get_permission_query_conditions_{frappe.scrub(doctype)}"
	return _conditions


def has_branch_permission(doc, user: str | None = None, branch_field: str = "branch") -> bool:
	"""Document-level counterpart used by hooks.has_permission."""
	branches = get_permitted_branches(user)
	if not branches:
		return True
	value = doc.get(branch_field) if hasattr(doc, "get") else None
	return not value or value in branches


# Generated module-level callables, e.g. `service_job_card_query`, referenced from hooks.py.
def _register_conditions():
	module = globals()
	for doctype, field in BRANCH_SCOPED_DOCTYPES.items():
		key = f"{frappe.scrub(doctype)}_query"
		module[key] = get_permission_query_conditions_factory(doctype, field)


_register_conditions()
