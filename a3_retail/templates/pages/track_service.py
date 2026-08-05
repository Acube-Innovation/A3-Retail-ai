"""Portal page: /track-service (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.title = _("Track your repair")
	context.reference = frappe.form_dict.get("ref") or ""
	return context
