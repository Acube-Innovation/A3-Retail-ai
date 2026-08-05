"""Seed 23 — courier dispatches and delivery trips (scope 14.2)."""

import frappe
from frappe.utils import add_days, nowdate

# status, dispatch type, days ago
DISPATCHES = [
	("Delivered", "Sales Delivery", 8),
	("In Transit", "Service Device Return", 2),
	("In Transit", "Inter-branch Stock", 1),
	("Booked", "OEM Warranty Return", 0),
	("Delivered", "Sales Delivery", 12),
]


def run():
	_dispatches()
	_delivery_trips()


def _dispatches():
	if frappe.db.count("Courier Dispatch", {"docstatus": 1}) >= len(DISPATCHES):
		return

	partner = frappe.db.get_value("Courier Partner", {"is_active": 1}, "name") or \
		frappe.db.get_value("Courier Partner", {}, "name")
	if not partner:
		return

	service = frappe.db.get_value("Courier Service Type", {"parent": partner}, "service_type") \
		if frappe.db.exists("DocType", "Courier Service Type") else None

	jobs = frappe.get_all(
		"Service Job Card", filters={"docstatus": 1, "status": ["in", ["Delivered", "Ready for Delivery"]]},
		fields=["name", "branch", "customer", "customer_name", "customer_mobile"], limit=len(DISPATCHES),
	)

	for index, (status, dispatch_type, days_ago) in enumerate(DISPATCHES):
		job = jobs[index] if index < len(jobs) else None
		doc = frappe.new_doc("Courier Dispatch")
		doc.dispatch_type = dispatch_type
		doc.branch = job.branch if job else "Kochi"
		doc.courier_partner = partner
		if service:
			doc.service_type = service
		doc.awb_no = f"AWB{index + 1:09d}"
		doc.consignee_type = "Customer"
		if job:
			doc.reference_type = "Service Job Card"
			doc.reference_name = job.name
			doc.consignee = job.customer
			doc.consignee_name = job.customer_name
			doc.consignee_mobile = job.customer_mobile
		doc.consignee_address = "Kaloor, Kochi"
		doc.pincode = ["682017", "695001", "673001"][index % 3]
		doc.no_of_packages = 1
		doc.weight_kg = 0.5
		doc.declared_value = 15000
		doc.dispatch_date = add_days(nowdate(), -days_ago)
		doc.expected_delivery_date = add_days(nowdate(), -days_ago + 3)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: dispatch {index}")
			continue

		values = {"status": status}
		if status == "Delivered":
			values["actual_delivery_date"] = add_days(nowdate(), -days_ago + 2)
			values["received_by"] = doc.consignee_name or "Customer"
		frappe.db.set_value("Courier Dispatch", doc.name, values, update_modified=False)


def _vehicle(licence_plate: str, company: str) -> str | None:
	if frappe.db.exists("Vehicle", licence_plate):
		return licence_plate

	doc = frappe.new_doc("Vehicle")
	doc.license_plate = licence_plate
	doc.make = "TVS"
	doc.model = "Jupiter"
	doc.last_odometer = 12000
	doc.acquisition_date = frappe.utils.add_days(nowdate(), -400)
	doc.fuel_type = "Petrol"
	doc.uom = "Litre"
	doc.vehicle_value = 92000
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: vehicle {licence_plate}")
		return None
	return doc.name


def _delivery_trips():
	if not frappe.db.exists("DocType", "Delivery Trip"):
		return
	if frappe.db.count("Delivery Trip") >= 3:
		return

	driver = frappe.db.get_value("Employee", {"designation": "Delivery Executive"}, "name")
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	for index in range(3):
		doc = frappe.new_doc("Delivery Trip")
		doc.company = company
		doc.departure_time = f"{add_days(nowdate(), -index)} 10:00:00"
		doc.driver = driver
		vehicle = _vehicle(f"KL-07-AB-{4421 + index}", company)
		if not vehicle:
			continue
		doc.vehicle = vehicle
		if doc.meta.has_field("custom_branch"):
			doc.custom_branch = "Kochi"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: delivery trip {index}")
