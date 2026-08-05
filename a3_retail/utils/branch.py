"""Branch resolution and default stamping.

Branch isolation (ADR-01) is a single Company with a Cost Center, a warehouse
group and an Accounting Dimension per branch. Every branch-scoped document is
stamped here so the rest of the app never has to resolve the branch itself.
"""

import frappe
from frappe import _

# Fields a branch-scoped doctype may declare; only the ones that exist are set.
BRANCH_DEFAULT_MAP = {
	"branch": "branch",
	"branch_code": "branch_code",
	"company": "company",
	"cost_center": "cost_center",
}


def get_user_branch(user: str | None = None) -> str | None:
	"""Resolve the Branch for a user via their Employee record.

	Falls back to the user's Branch User Permission, then to the only active
	Branch Profile when a single-branch tenant is in play.
	"""
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return _single_branch()

	branch = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "branch")
	if branch:
		return branch

	permitted = frappe.db.get_value("User Permission", {"user": user, "allow": "Branch"}, "for_value")
	if permitted:
		return permitted

	return _single_branch()


def _single_branch() -> str | None:
	branches = frappe.get_all("Branch Profile", filters={"is_active": 1}, pluck="branch", limit=2)
	return branches[0] if len(branches) == 1 else None


def get_user_branches(user: str | None = None) -> list[str]:
	"""Every Branch the user may see. Empty list means unrestricted."""
	user = user or frappe.session.user
	if user == "Administrator":
		return []

	unrestricted = {"System Manager", "A3 Retail Admin", "Accounts Manager", "HR Manager", "Auditor"}
	if unrestricted & set(frappe.get_roles(user)):
		return []

	branches = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Branch"},
		pluck="for_value",
	)
	if branches:
		return branches

	branch = get_user_branch(user)
	return [branch] if branch else []


def get_branch_profile(branch: str | None):
	"""Return the Branch Profile document for a Branch, or None."""
	if not branch:
		return None
	name = frappe.db.get_value("Branch Profile", {"branch": branch}, "name")
	if not name:
		return None
	return frappe.get_cached_doc("Branch Profile", name)


def get_branch_profile_value(branch: str | None, fieldname: str):
	"""Single-field read from a Branch Profile without loading the whole doc."""
	if not branch:
		return None
	return frappe.db.get_value("Branch Profile", {"branch": branch}, fieldname)


def get_branch_code(branch: str | None) -> str | None:
	return get_branch_profile_value(branch, "branch_code")


def set_branch_defaults(doc, throw_if_missing: bool = False):
	"""Stamp branch, branch_code, company and cost center on a document.

	Called from `before_validate` of every branch-scoped doctype (directly or
	through A3BranchMixin). Existing values are never overwritten.
	"""
	meta = doc.meta

	if meta.has_field("branch") and not doc.get("branch"):
		doc.branch = get_user_branch()

	branch = doc.get("branch")
	if not branch:
		if throw_if_missing:
			frappe.throw(
				_("Branch could not be determined for {0}. Link your user to an Employee with a Branch.").format(
					frappe.session.user
				)
			)
		return doc

	profile = get_branch_profile(branch)
	if not profile:
		if throw_if_missing:
			frappe.throw(_("No Branch Profile exists for Branch {0}").format(branch))
		return doc

	if meta.has_field("branch_code") and not doc.get("branch_code"):
		doc.branch_code = profile.branch_code

	if meta.has_field("company") and not doc.get("company"):
		doc.company = profile.company

	if meta.has_field("cost_center") and not doc.get("cost_center"):
		doc.cost_center = profile.cost_center

	return doc


class A3BranchMixin:
	"""Mixin for branch-scoped controllers.

	Controllers that subclass it get branch stamping for free; those that define
	their own `before_validate` should call `self.set_branch_defaults()`.
	"""

	def before_validate(self):
		self.set_branch_defaults()

	def set_branch_defaults(self):
		set_branch_defaults(self)

	@property
	def branch_profile(self):
		return get_branch_profile(self.get("branch"))
