"""Shared helpers for the A3 Retail app."""

import frappe
from frappe.utils import flt


def get_settings():
	"""Cached A3 Retail Settings singleton."""
	return frappe.get_cached_doc("A3 Retail Settings")


def setting(fieldname, default=None):
	"""Read one field off A3 Retail Settings without loading the doc."""
	value = frappe.db.get_single_value("A3 Retail Settings", fieldname)
	return default if value in (None, "") else value


def money(value) -> float:
	"""Currency rounding used across the app (precision 2, scope golden rule 6)."""
	return flt(value, 2)


def publish_dashboard_update(branch_code: str | None = None, payload: dict | None = None):
	"""Nudge the Control Tower to re-fetch (scope 12.1)."""
	if not setting("enable_realtime_dashboard", 1):
		return
	frappe.publish_realtime(
		"a3_retail_dashboard_update",
		payload or {"branch": branch_code},
		room=f"branch:{branch_code}" if branch_code else None,
		after_commit=True,
	)
