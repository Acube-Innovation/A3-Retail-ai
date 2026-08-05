"""Portal page: /support (scope 13.1)."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.branches = frappe.get_all(
		"Branch Profile", filters={"is_active": 1}, pluck="branch", order_by="branch"
	)
	context.categories = [
		"Service Delay", "Repair Quality", "Product Defect", "Billing / Invoice", "Refund",
		"EMI / Finance", "Delivery Delay", "Staff Behaviour", "Warranty Denial", "Other",
	]
	return context
