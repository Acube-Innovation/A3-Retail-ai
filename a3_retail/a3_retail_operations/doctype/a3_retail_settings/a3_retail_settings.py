# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class A3RetailSettings(Document):
	def validate(self):
		if self.min_photos and self.min_photos > 4:
			frappe.throw(_("A job card captures at most 4 device photos."))
		if self.max_discount_percent_branch_user and self.max_discount_percent_branch_user > 100:
			frappe.throw(_("Maximum discount cannot exceed 100%."))
		if self.otp_validity_minutes and self.otp_validity_minutes < 1:
			frappe.throw(_("OTP validity must be at least one minute."))

	def on_update(self):
		frappe.clear_cache(doctype="A3 Retail Settings")


def get_settings():
	"""Cached accessor used across the app."""
	return frappe.get_cached_doc("A3 Retail Settings")


def get_value(fieldname, default=None):
	value = frappe.db.get_single_value("A3 Retail Settings", fieldname)
	return default if value in (None, "") else value
