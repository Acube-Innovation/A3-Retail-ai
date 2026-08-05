"""Seed 08 — 12 issue types, 6 TAT policies, 4 technician profiles (scope 3.6 – 3.8)."""

import frappe

# name, category, default labour item, standard tat, voids warranty
ISSUE_TYPES = [
	("Display Broken", "Display", "SRV-LAB-L2", 24, 0),
	("Touch Not Working", "Display", "SRV-LAB-L2", 24, 0),
	("Battery Draining Fast", "Battery", "SRV-LAB-L2", 12, 0),
	("Not Charging", "Charging", "SRV-LAB-L2", 24, 0),
	("Speaker Not Working", "Audio", "SRV-LAB-L2", 24, 0),
	("Camera Blur", "Camera", "SRV-LAB-L2", 24, 0),
	("No Network", "Board Level", "SRV-LAB-L3", 72, 0),
	("Water Damage", "Liquid Damage", "SRV-LAB-L3", 72, 1),
	("Phone Hanging", "Software", "SRV-LAB-L1", 4, 0),
	("Dead - No Power", "Board Level", "SRV-LAB-L3", 72, 0),
	("Software Update", "Software", "SRV-LAB-L1", 2, 0),
	("Face ID Not Working", "Board Level", "SRV-LAB-L3", 48, 0),
]

# name, repair category, priority, tat hours, escalate after, escalate role
TAT_POLICIES = [
	("Software - Normal", "Software", "Normal", 8, 12, "Service Manager"),
	("Hardware Component - Normal", "Hardware - Component", "Normal", 48, 60, "Service Manager"),
	("Board Level - Normal", "Hardware - Board Level", "Normal", 96, 120, "Branch Manager"),
	("Display Replacement - High", "Display", "High", 24, 30, "Service Manager"),
	("Same Day Urgent", "Software", "Urgent (Same Day)", 4, 5, "Branch Manager"),
	("Liquid Damage", "Liquid Damage", "Normal", 120, 144, "Branch Manager"),
]

# employee name, level, max jobs, skills [(brand, category, proficiency)]
TECHNICIANS = [
	("Vishnu P", "L3 - Board Level", 5, [
		("Samsung", "Hardware - Board Level", "Expert"),
		("Apple", "Hardware - Board Level", "Expert"),
	]),
	("Sajeer K", "L2 - Hardware", 8, [
		("Samsung", "Hardware - Component", "Expert"),
		("Xiaomi", "Display", "Expert"),
	]),
	("Anoop R", "L1 - Software", 12, [
		("Samsung", "Software", "Intermediate"),
		("Xiaomi", "Software", "Intermediate"),
	]),
	("Rijo Thomas", "L2 - Hardware", 8, [
		("Xiaomi", "Hardware - Component", "Expert"),
		("Vivo", "Display", "Expert"),
	]),
]


def run():
	_issue_types()
	_tat_policies()
	_technicians()


def _issue_types():
	for name, category, labour_item, tat, voids in ISSUE_TYPES:
		if frappe.db.exists("Service Issue Type", name):
			continue
		doc = frappe.new_doc("Service Issue Type")
		doc.issue_name = name
		doc.category = category
		doc.standard_tat_hours = tat
		doc.is_warranty_void_trigger = voids
		doc.requires_data_backup = 1 if category in ("Software", "Display", "Board Level") else 0
		if frappe.db.exists("Item", labour_item):
			doc.default_labour_item = labour_item
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _tat_policies():
	for name, category, priority, tat, escalate_after, role in TAT_POLICIES:
		if frappe.db.exists("Service TAT Policy", name):
			continue
		doc = frappe.new_doc("Service TAT Policy")
		doc.policy_name = name
		doc.repair_category = category
		doc.priority = priority
		doc.tat_hours = tat
		doc.escalate_after_hours = escalate_after
		doc.escalate_to_role = role if frappe.db.exists("Role", role) else None
		doc.exclude_non_working_hours = 1
		doc.warn_at_percent = 80
		doc.notify_customer_on_delay = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _technicians():
	for employee_name, level, max_jobs, skills in TECHNICIANS:
		employee = frappe.db.get_value("Employee", {"employee_name": employee_name}, "name")
		if not employee or frappe.db.exists("Technician Profile", {"employee": employee}):
			continue

		doc = frappe.new_doc("Technician Profile")
		doc.__newname = employee_name
		doc.employee = employee
		doc.technician_level = level
		doc.max_concurrent_jobs = max_jobs
		doc.is_active = 1
		for brand, category, proficiency in skills:
			if frappe.db.exists("Brand", brand):
				doc.append("skills", {"brand": brand, "repair_category": category, "proficiency": proficiency})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
