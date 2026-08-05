"""Portal page: /stores (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	from a3_retail.api.portal import store_locator

	context.no_cache = 1
	context.stores = store_locator()
	return context
