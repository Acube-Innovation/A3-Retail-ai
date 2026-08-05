"""Naming helpers.

Series such as `JC-{branch_code}-.YY.-.#####` need `branch_code` populated on the
document before `autoname` runs, so `set_branch_code` is wired into
`before_naming` for every doctype that uses a branch series.
"""

import frappe
from frappe import _
from frappe.model.naming import make_autoname

from a3_retail.utils.branch import get_branch_code, get_user_branch


def set_branch_code(doc, method=None):
	"""Populate `branch_code` from the document's Branch before naming."""
	if not doc.meta.has_field("branch_code"):
		return

	if doc.get("branch_code"):
		return

	branch = doc.get("branch") or get_user_branch()
	if not branch:
		return

	if doc.meta.has_field("branch") and not doc.get("branch"):
		doc.branch = branch

	doc.branch_code = get_branch_code(branch) or "HO"


def branch_autoname(doc, prefix: str, digits: int = 5) -> str:
	"""Build `<PREFIX>-<BRANCH>-<YY>-<serial>` respecting the branch code.

	Used by controllers whose naming rule cannot be expressed as a plain series
	(for example when the prefix is configurable through A3 Retail Settings).
	"""
	set_branch_code(doc)
	code = doc.get("branch_code") or "HO"
	return make_autoname(f"{prefix}-{code}-.YY.-.{'#' * digits}", doc=doc)


def get_series_prefix(setting_field: str, fallback: str) -> str:
	"""Read a configurable prefix from A3 Retail Settings with a safe fallback."""
	if not frappe.db.exists("DocType", "A3 Retail Settings"):
		return fallback
	return frappe.db.get_single_value("A3 Retail Settings", setting_field) or fallback


def validate_unique(doctype: str, filters: dict, exclude: str | None = None, label: str | None = None):
	"""Throw when another document already matches `filters`."""
	existing = frappe.db.get_value(doctype, filters, "name")
	if existing and existing != exclude:
		frappe.throw(
			_("{0} {1} already exists for this combination.").format(label or doctype, existing),
			frappe.DuplicateEntryError,
		)
