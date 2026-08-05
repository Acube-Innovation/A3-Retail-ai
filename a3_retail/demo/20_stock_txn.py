"""Seed 20 — stock requests, damage reports and demurrage (scope 14.2)."""

import frappe
from frappe.utils import add_days, nowdate

REQUESTS = [
	("Thiruvananthapuram", "Kochi", "SPR-DSP-A55", 2, "Received", "Service Job Card"),
	("Kozhikode", "Kochi", "SPR-BAT-N13", 3, "In Transit", "Service Job Card"),
	("Kochi", "Thiruvananthapuram", "ACC-TGL-A55", 10, "Approved", "Stock Balancing"),
	("Kozhikode", "Kochi", "MOB-XIA-N13-6-128", 1, "Pending Approval", "Customer Sale"),
]

DAMAGES = [
	("Kochi", "Handling Damage", "ACC-TGL-A55", 4, "Employee"),
	("Kochi", "Transit Damage", "ACC-CHG-25W-TC", 2, "Courier / Transporter"),
	("Thiruvananthapuram", "Display/Demo Wear", "ACC-BUD-XIA", 1, "Company (No Recovery)"),
	("Kochi", "Natural Calamity", "ACC-TGL-A55", 6, "Insurance"),
	("Kozhikode", "Handling Damage", "ACC-CHG-25W-TC", 1, "Employee"),
]


def run():
	_stock_requests()
	_damage_reports()
	_demurrage()


def _stock_requests():
	if frappe.db.count("Stock Request", {"docstatus": 1}) >= len(REQUESTS):
		return

	for index, (requesting, source, item_code, qty, target_status, purpose) in enumerate(REQUESTS):
		if not frappe.db.exists("Item", item_code):
			continue

		doc = frappe.new_doc("Stock Request")
		doc.request_date = add_days(nowdate(), -(index + 2))
		doc.requesting_branch = requesting
		doc.source_branch = source
		doc.purpose = purpose
		doc.priority = "Normal"
		doc.required_by = add_days(nowdate(), 2)
		doc.append("items", {"item_code": item_code, "qty": qty})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: stock request {index}")
			continue

		_advance(doc, target_status)


def _advance(doc, target_status: str):
	"""Walk the request to the status the demo wants it in."""
	sequence = ["Pending Approval", "Approved", "In Transit", "Received"]
	if target_status not in sequence:
		return

	for status in sequence[: sequence.index(target_status) + 1]:
		if status == "Pending Approval":
			continue
		try:
			if status == "Approved":
				doc.reload()
				if doc.status != "Pending Approval":
					# Small requests approve themselves under the auto-approve limit.
					continue
				doc.approve()
			elif status == "In Transit":
				doc.reload()
				doc.dispatch()
			elif status == "Received":
				doc.reload()
				doc.receive()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: stock request {doc.name} -> {status}")
			return


def _damage_reports():
	if frappe.db.count("Stock Damage Report", {"docstatus": 1}) >= len(DAMAGES):
		return

	for index, (branch, damage_type, item_code, qty, responsibility) in enumerate(DAMAGES):
		if not frappe.db.exists("Item", item_code):
			continue

		warehouse = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
		doc = frappe.new_doc("Stock Damage Report")
		doc.report_date = add_days(nowdate(), -(index + 1))
		doc.branch = branch
		doc.damage_type = damage_type
		doc.discovered_during = "Stock Count"
		doc.source_warehouse = warehouse
		doc.responsibility = responsibility
		doc.reported_by = frappe.db.get_value("Employee", {"branch": branch, "status": "Active"},
		                                      "name")
		rate = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
		                           "valuation_rate") or 100
		doc.append("items", {"item_code": item_code, "warehouse": warehouse, "qty": qty,
		                     "valuation_rate": rate, "amount": rate * qty,
		                     "damage_description": f"{damage_type} damage found during count"})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: damage report {index}")


def _demurrage():
	if frappe.db.count("Demurrage Charge") >= 3:
		return

	jobs = frappe.get_all(
		"Service Job Card",
		filters={"docstatus": 1, "status": "Ready for Delivery"},
		fields=["name", "branch", "customer", "ready_on"], limit=3,
	)
	for index, job in enumerate(jobs):
		doc = frappe.new_doc("Demurrage Charge")
		doc.charge_type = "Customer Device Storage"
		doc.branch = job.branch
		doc.party_type = "Customer"
		doc.party = job.customer
		doc.reference_type = "Service Job Card"
		doc.reference_name = job.name
		doc.arrival_date = add_days(nowdate(), -(20 + index * 5))
		doc.free_days = 15
		doc.rate_per_day = 20
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: demurrage {index}")
