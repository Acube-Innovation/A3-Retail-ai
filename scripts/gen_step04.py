import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SVC = "A3 Retail Service"

DEVICE_TYPES = "Mobile\nTablet\nSmartwatch\nEarbuds\nLaptop\nOther"

device_model_fields = [
    f("model_name", "Data", "Model Name", reqd=1, in_list_view=1),
    f("brand", "Link", "Brand", "Brand", reqd=1, in_list_view=1, in_standard_filter=1),
    f("device_type", "Select", "Device Type", DEVICE_TYPES, default="Mobile", in_list_view=1),
    f("launch_year", "Int", "Launch Year"),
    cb(),
    f("is_active", "Check", "Active", default="1"),
    f("avg_repair_tat_hours", "Int", "Avg TAT (hrs)", default="48"),
    f("common_issues", "Table MultiSelect", "Common Issues", "Device Model Issue"),

    sb("parts_section", "Standard Parts"),
    f("standard_display_part", "Link", "Standard Display Part", "Item"),
    f("standard_battery_part", "Link", "Standard Battery Part", "Item"),
    cb(),
    f("standard_display_rate", "Currency", "Typical Display Cost"),
    f("standard_battery_rate", "Currency", "Typical Battery Cost"),
]

DEVICE_MODEL_CONTROLLER = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
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
'''

print("Step 4 — masters")

DT(
    "Device Model Issue",
    SVC,
    [f("issue_type", "Link", "Issue Type", "Service Issue Type", reqd=1, in_list_view=1)],
    istable=1,
).write()

DT(
    "Device Model",
    SVC,
    device_model_fields,
    autoname="prompt",
    title_field="model_name",
    search_fields="brand,device_type",
    track_changes=1,
    perms_spec=[
        ("System Manager", "CRUD"),
        ("A3 Retail Admin", "CRUD"),
        ("Service Manager", "CRUD"),
        ("Reception Executive", "CRU"),
        ("Branch Manager", "R"),
        ("Sales Executive", "R"),
        ("Technician", "R"),
    ],
).write(controller=DEVICE_MODEL_CONTROLLER)
