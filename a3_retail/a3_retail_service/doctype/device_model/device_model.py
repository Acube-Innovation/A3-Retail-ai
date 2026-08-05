# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Device Model — the catalogue the reception desk uses for devices we did not sell."""

import frappe
from frappe import _
from frappe.model.document import Document


class DeviceModel(Document):
	def autoname(self):
		self.name = f"{self.brand} {self.model_name}".strip()

	def validate(self):
		self.model_name = (self.model_name or "").strip()
		if not self.model_name:
			frappe.throw(_("Model Name is required."))

		duplicate = frappe.db.exists(
			"Device Model",
			{"model_name": self.model_name, "brand": self.brand, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("Device Model {0} already exists for brand {1}.").format(self.model_name, self.brand))


@frappe.whitelist()
def search_models(brand: str | None = None, txt: str = "", limit: int = 20) -> list[dict]:
	"""Autocomplete source for the Reception Desk model picker."""
	from a3_retail.api import require_permission

	require_permission("Device Model", "read")

	filters = {"is_active": 1}
	if brand:
		filters["brand"] = brand
	return frappe.get_all(
		"Device Model",
		filters=filters,
		or_filters=[["model_name", "like", f"%{txt}%"], ["name", "like", f"%{txt}%"]] if txt else None,
		fields=["name", "model_name", "brand", "device_type", "avg_repair_tat_hours"],
		limit_page_length=int(limit),
		order_by="modified desc",
	)
