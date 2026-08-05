# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service TAT Policy — how long a repair category is allowed to take (scope 3.7)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceTATPolicy(Document):
	def validate(self):
		if self.tat_hours is not None and self.tat_hours <= 0:
			frappe.throw(_("TAT Hours must be greater than zero."))

		if self.escalate_after_hours and self.escalate_after_hours < self.tat_hours:
			frappe.throw(_("Escalation must happen after the TAT, not before it."))

		if self.warn_at_percent and not (0 < self.warn_at_percent <= 100):
			frappe.throw(_("Warn At % must be between 1 and 100."))
