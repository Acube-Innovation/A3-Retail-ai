"""Seed 17 — 60 service job cards spread across every status (scope 14.2, 14.3).

The status mix is the one the scope asks for: 18 delivered or closed, 12 in
progress, 7 awaiting parts, 6 ready, 5 at estimate stage, 6 delayed and the rest
still open. Recent cards walk the state machine so their status log is real;
older ones are imported in the state they ended in, the same treatment seed 24
gives July's history.
"""

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.utils.imei import luhn_check_digit

# status, count, age in days
MIX = [
	("Delivered", 12, 20),
	("Closed", 6, 30),
	("In Progress", 12, 3),
	("Awaiting Parts", 7, 6),
	("Ready for Delivery", 6, 2),
	("Estimate Sent", 5, 2),
	("Under Diagnosis", 6, 1),
	("Open", 12, 0),
]

BRANCHES = ["Kochi", "Kochi", "Thiruvananthapuram"]
COMPLAINTS = [
	("Display flickering after a drop", "Display"),
	("Battery drains within 3 hours", "Battery"),
	("Charging port loose", "Hardware - Component"),
	("No network after software update", "Software"),
	("Speaker distorted on calls", "Hardware - Component"),
	("Water damage — phone dead", "Liquid Damage"),
	("Camera app crashes", "Hardware - Board Level"),
	("Touch not responding in the corner", "Display"),
]
# Device Model names carry the brand prefix (seed 04).
MODELS = [("Samsung", "Samsung Galaxy A55"), ("Xiaomi", "Xiaomi Redmi Note 13"),
          ("Vivo", "Vivo Vivo T3"), ("Apple", "Apple iPhone 15")]

IMEI_PREFIX = "3591270"
_imei_sequence = {"next": 7000000}


def run():
	# The IMEI prefix is this seed's fingerprint — other seeds use their own.
	if frappe.db.count("Service Job Card", {"imei_1": ["like", f"{IMEI_PREFIX}%"]}) >= 60:
		return

	customers = frappe.get_all("Customer", filters={"a3_mobile_no": ["is", "set"]}, pluck="name")
	if not customers:
		return

	index = 0
	for status, count, age in MIX:
		for _ in range(count):
			_job_card(index, status, age, customers)
			index += 1


def _job_card(index: int, target_status: str, age_days: int, customers: list[str]):
	branch = BRANCHES[index % len(BRANCHES)]
	complaint, category = COMPLAINTS[index % len(COMPLAINTS)]
	brand, model = MODELS[index % len(MODELS)]
	received = add_to_date(getdate(nowdate()), days=-age_days)

	doc = frappe.new_doc("Service Job Card")
	doc.branch = branch
	doc.customer = customers[index % len(customers)]
	doc.device_type = "Mobile"
	doc.brand = brand
	doc.device_model = model
	doc.imei_1 = _next_imei()
	doc.complaint_description = complaint
	doc.repair_category = category
	doc.received_on = f"{received} {10 + index % 8}:00:00"
	doc.priority = "High" if index % 7 == 0 else "Normal"
	doc.assigned_technician = _technician(branch, index)
	doc.data_loss_consent = 1
	doc.customer_signature = "data:image/png;base64,iVBORw0KGgo="
	doc.device_photo_1 = "/files/demo-device.jpg"
	doc.flags.ignore_permissions = True

	try:
		doc.insert(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: job card {index}")
		return

	if target_status == "Open":
		return

	if age_days <= 3:
		_walk(doc, target_status)
	else:
		_import_state(doc, target_status, received)


def _walk(doc, target_status: str):
	"""Recent cards walk the state machine, so the status log is genuine."""
	for hop in st.path_to(doc.status, target_status) or []:
		doc.status = hop
		doc.flags.ignore_permissions = True
		try:
			doc.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: job card hop {doc.name} -> {hop}")
			return


def _import_state(doc, target_status: str, received):
	frappe.flags.a3_import_history = True
	try:
		doc.reload()
		doc.status = target_status
		if target_status in ("Delivered", "Closed"):
			doc.delivered_on = add_to_date(received, days=2)
			doc.receiver_name = doc.customer_name
		doc.flags.ignore_permissions = True
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: job card import {doc.name}")
	finally:
		frappe.flags.a3_import_history = False


def _technician(branch: str, index: int) -> str | None:
	technicians = frappe.get_all(
		"Employee",
		filters={"branch": branch, "status": "Active", "designation": ["like", "Technician%"]},
		pluck="name",
	)
	return technicians[index % len(technicians)] if technicians else None


def _next_imei() -> str:
	while True:
		body = f"{IMEI_PREFIX}{_imei_sequence['next']:07d}"[:14]
		_imei_sequence["next"] += 1
		imei = body + str(luhn_check_digit(body))
		if not frappe.db.exists("Serial No", imei):
			return imei
