"""Portal page: /offers (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.api.portal import active_offers

	context.no_cache = 1
	context.branch = frappe.form_dict.get("branch")
	context.offers = active_offers(context.branch)
	context.branches = frappe.get_all(
		"Branch Profile", filters={"is_active": 1}, pluck="branch", order_by="branch"
	)
	return context
