"""Seed 24 — July 2026 HR history and the four incentive runs (scope 10.1, 10.2).

Everything here exists to make the July incentive table in scope 10.2 reproduce
from live data rather than from hand-typed figures: the sales that earn Vipin's
0.90% slab, the 189 repairs behind the technician run, Manoj's EMI conversions,
Sneha's telecalling conversions, and the attendance that fails Sajeer's gate.

Back-dated documents are inserted in the state they ended in — `a3_import_history`
tells the job-card state machine this is history, not a shop-floor edit — because
walking 189 cards through eight hops each would make the seed unusable.
"""

import frappe
from frappe.utils import add_to_date, flt, get_last_day, getdate

from a3_retail.setup.hr import assign_salary_structure
from a3_retail.utils.imei import luhn_check_digit

PERIOD_START = "2026-07-01"
PERIOD_END = "2026-07-31"

# Twenty-five attendance rows per employee — July 2026 has 27 non-Sunday days and
# every branch closes for Onam stock-taking. present / half-day / absent.
ATTENDANCE = {
	"Vipin S": (24, 0, 1),        # 96%
	"Rafeeq M": (23, 0, 2),       # 92%
	"Manoj Kumar": (24, 1, 0),    # 98%
	"Vishnu P": (23, 1, 1),       # 94%
	"Sajeer K": (22, 0, 3),       # 88% — fails the 90% gate
	"Rijo Thomas": (24, 0, 1),    # 96%
	"Sneha M": (24, 0, 1),        # 96%
	"Anoop R": (23, 0, 2),        # 92%
	"Arjun V": (24, 0, 1),        # 96%
	"Reshma K": (24, 0, 1),
	"Arun Menon": (25, 0, 0),
}

WORKING_DAYS = [
	"2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-06",
	"2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11",
	"2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17",
	"2026-07-18", "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
	"2026-07-24", "2026-07-25", "2026-07-27", "2026-07-28", "2026-07-29",
]

# Jobs each technician delivered in July, and how many failed QC on the way.
TECHNICIAN_JOBS = {
	"Vishnu P": (71, 2, "Kochi"),
	"Sajeer K": (55, 1, "Kochi"),
	"Rijo Thomas": (63, 1, "Thiruvananthapuram"),
}

# Vipin's July sales. The mix is what earns the scope table's ₹1,650 spiff:
# two Apple units at ₹300 and seven extended-warranty plans at ₹150. The Galaxy
# A55 at ₹39,999 sits just under the ₹40,000 Samsung-flagship threshold, so it
# earns nothing extra — exactly as the scheme intends.
VIPIN_INVOICES = [
	("2026-07-08", [("MOB-APL-15-128-BLK", 2, 69900), ("EW-PLAN-12M", 2, 1999)]),
	("2026-07-14", [("MOB-SAM-A55-8-128-BLU", 6, 39999), ("EW-PLAN-12M", 2, 1999),
	                ("ACC-CHG-25W-TC", 20, 1499)]),
	("2026-07-21", [("MOB-XIA-N13-6-128", 4, 16999), ("EW-PLAN-12M", 2, 1999),
	                ("ACC-BUD-XIA", 4, 2199), ("MOB-VIV-T3-8-128", 6, 21499)]),
	("2026-07-27", [("TAB-SAM-S9FE", 3, 34999), ("EW-PLAN-12M", 1, 1999),
	                ("ACC-TGL-A55", 30, 299)]),
]
VIPIN_NET_TARGET = 742000
VIPIN_RETURN_VALUE = 24000  # clawed back at the top slab: 24,000 × 1.25% = 300

RAFEEQ_INVOICES = [
	("2026-07-09", [("MOB-XIA-N13-6-128", 6, 16999), ("EW-PLAN-12M", 3, 1999)]),
	("2026-07-18", [("MOB-SAM-A55-8-128-BLU", 5, 39999)]),
]
RAFEEQ_NET_TARGET = 305000

EMI_APPLICATIONS = 18
EMI_FAST_APPROVALS = 4  # approved inside 24 hours — ₹150 bonus each
TELECALL_CONVERSIONS = 41

RUNS = [
	("Sales Executive Monthly", None),
	("Technician Monthly", None),
	("EMI Conversion", None),
	("Telecaller Monthly", None),
]

_imei_sequence = {"next": 4000000}


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	_assign_salary_structures(company)
	_seed_attendance(company)
	_seed_sales_persons()
	_seed_sales(company)
	_seed_job_cards()
	_seed_emi_applications()
	_seed_telecalling()
	_seed_feedback()
	_seed_incentive_runs(company)


# ---------------------------------------------------------------- payroll setup
def _assign_salary_structures(company):
	from a3_retail.demo import __name__ as _pkg  # noqa: F401  (keeps the package importable)

	for employee in frappe.get_all(
		"Employee", filters={"status": "Active"}, fields=["name", "grade", "date_of_joining"]
	):
		base = flt(frappe.db.get_value("Employee Grade", employee.grade, "default_base_pay"))
		if not base:
			continue
		from_date = max(getdate(employee.date_of_joining), getdate("2026-04-01"))
		try:
			assign_salary_structure(employee.name, base, str(from_date))
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: salary structure {employee.name}")


# ------------------------------------------------------------------ attendance
def _seed_attendance(company):
	for employee_name, (present, half, absent) in ATTENDANCE.items():
		employee = _employee(employee_name)
		if not employee:
			continue
		if frappe.db.exists(
			"Attendance",
			{"employee": employee, "attendance_date": ["between", [PERIOD_START, PERIOD_END]],
			 "docstatus": 1},
		):
			continue

		statuses = ["Present"] * present + ["Half Day"] * half + ["Absent"] * absent
		branch = frappe.db.get_value("Employee", employee, "branch")

		for date, status in zip(WORKING_DAYS, statuses):
			doc = frappe.new_doc("Attendance")
			doc.employee = employee
			doc.attendance_date = date
			doc.status = status
			doc.company = company
			doc.a3_branch = branch
			doc.flags.ignore_permissions = True
			doc.flags.ignore_validate = True
			try:
				doc.insert(ignore_permissions=True)
				doc.submit()
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"A3 demo: attendance {employee} {date}")


# ----------------------------------------------------------------- sales people
def _seed_sales_persons():
	"""Incentives are attributed through Sales Team, so every seller needs one."""
	parent = _sales_person_root()
	for employee_name in ("Vipin S", "Rafeeq M", "Manoj Kumar", "Arun Menon", "Fahad Rahman",
	                      "Nikhil Das"):
		employee = _employee(employee_name)
		if not employee or frappe.db.exists("Sales Person", {"employee": employee}):
			continue
		doc = frappe.new_doc("Sales Person")
		doc.sales_person_name = employee_name
		doc.employee = employee
		doc.parent_sales_person = parent
		doc.is_group = 0
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: sales person {employee_name}")


def _sales_person_root() -> str | None:
	# `["in", ["", None]]` never matches a SQL NULL — the tree root has one.
	root = frappe.db.get_value(
		"Sales Person", {"is_group": 1, "parent_sales_person": ["is", "not set"]}, "name"
	)
	if root:
		return root
	doc = frappe.new_doc("Sales Person")
	doc.sales_person_name = "All Sales Persons"
	doc.is_group = 1
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


# ----------------------------------------------------------------------- sales
def _seed_sales(company):
	_sell("Vipin S", "Kochi", VIPIN_INVOICES, VIPIN_NET_TARGET, company,
	      return_value=VIPIN_RETURN_VALUE)
	_sell("Rafeeq M", "Kozhikode", RAFEEQ_INVOICES, RAFEEQ_NET_TARGET, company)


def _sell(employee_name, branch, invoices, net_target, company, return_value=0):
	person = frappe.db.get_value("Sales Person", {"employee": _employee(employee_name)}, "name")
	if not person:
		return
	if frappe.db.exists("Sales Invoice", {"remarks": f"A3 demo July incentive - {employee_name}",
	                                      "docstatus": 1}):
		return

	warehouse = _warehouse(branch)
	customer = _customer()
	created = []

	# Everything sells at list price; the shortfall to the scope figure is booked
	# as a negotiated discount on the last invoice of the month.
	subtotal = sum(qty * rate for _date, lines in invoices for _code, qty, rate in lines)
	discount = max(subtotal - net_target, 0)

	for index, (posting_date, lines) in enumerate(invoices):
		doc = frappe.new_doc("Sales Invoice")
		doc.customer = customer
		doc.company = company
		doc.posting_date = posting_date
		doc.set_posting_time = 1
		doc.due_date = posting_date
		doc.branch = branch
		doc.update_stock = 1
		doc.set_warehouse = warehouse
		doc.remarks = f"A3 demo July incentive - {employee_name}"
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})

		for item_code, qty, rate in lines:
			row = doc.append("items", {
				"item_code": item_code,
				"qty": qty,
				"rate": rate,
				"warehouse": warehouse if frappe.get_cached_value("Item", item_code, "is_stock_item") else None,
			})
			if frappe.get_cached_value("Item", item_code, "has_serial_no"):
				row.use_serial_batch_fields = 1
				row.serial_no = "\n".join(_serials(item_code, warehouse, qty))

		if index == len(invoices) - 1 and discount:
			doc.apply_discount_on = "Net Total"
			doc.discount_amount = discount

		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_permissions=True)
			doc.submit()
			created.append(doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: invoice for {employee_name}")

	if return_value and created:
		_credit_note(created[0], return_value, company)


def _credit_note(invoice_name, net_value, company):
	"""A returned handset — the clawback the July table charges Vipin."""
	source = frappe.get_doc("Sales Invoice", invoice_name)
	row = next((r for r in source.items if flt(r.rate) >= net_value), source.items[0])

	doc = frappe.new_doc("Sales Invoice")
	doc.customer = source.customer
	doc.company = company
	doc.posting_date = "2026-07-30"
	doc.set_posting_time = 1
	doc.due_date = "2026-07-30"
	doc.branch = source.get("branch")
	doc.is_return = 1
	doc.return_against = source.name
	doc.update_stock = 0
	doc.remarks = "A3 demo July incentive - return"
	for member in source.get("sales_team") or []:
		doc.append("sales_team", {"sales_person": member.sales_person,
		                          "allocated_percentage": member.allocated_percentage})
	doc.append("items", {
		"item_code": row.item_code,
		"qty": -1,
		"rate": net_value,
		"warehouse": row.warehouse,
	})
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 demo: July credit note")


def _serials(item_code, warehouse, qty) -> list[str]:
	"""Serials on hand, topped up with a back-dated receipt when stock runs out."""
	available = frappe.get_all(
		"Serial No",
		filters={"item_code": item_code, "warehouse": warehouse, "status": "Active"},
		pluck="name",
		limit=qty,
	)
	if len(available) >= qty:
		return available

	receipt = _receive_stock(item_code, warehouse, qty - len(available))
	return available + receipt


def _receive_stock(item_code, warehouse, qty) -> list[str]:
	serials = [_next_imei() for _ in range(qty)]
	company = frappe.db.get_value("Warehouse", warehouse, "company")

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.company = company
	entry.posting_date = "2026-07-01"
	entry.set_posting_time = 1
	entry.remarks = "A3 demo July replenishment"
	row = entry.append("items", {
		"item_code": item_code,
		"qty": qty,
		"t_warehouse": warehouse,
		"basic_rate": flt(frappe.db.get_value("Item Price", {"item_code": item_code,
		                                                    "price_list": "Standard Buying"}, "price_list_rate"))
		or flt(frappe.get_cached_value("Item", item_code, "valuation_rate")) or 1000,
	})
	if frappe.get_cached_value("Item", item_code, "has_serial_no"):
		row.use_serial_batch_fields = 1
		row.serial_no = "\n".join(serials)

	entry.flags.ignore_permissions = True
	try:
		entry.insert(ignore_permissions=True)
		entry.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: replenish {item_code}")
		return []
	return serials


def _next_imei() -> str:
	while True:
		body = f"3591250{_imei_sequence['next']:07d}"[:14]
		_imei_sequence["next"] += 1
		imei = body + str(luhn_check_digit(body))
		if not frappe.db.exists("Serial No", imei):
			return imei


# ------------------------------------------------------------------ job cards
def _seed_job_cards():
	"""189 repairs delivered in July, imported in their final state."""
	customer = _customer()
	frappe.flags.a3_import_history = True
	try:
		for technician_name, (count, qc_failures, branch) in TECHNICIAN_JOBS.items():
			technician = _employee(technician_name)
			if not technician:
				continue

			existing = frappe.db.count(
				"Service Job Card",
				{"assigned_technician": technician, "docstatus": 1,
				 "delivered_on": ["between", [PERIOD_START, f"{PERIOD_END} 23:59:59"]]},
			)
			for index in range(existing, count):
				_job_card(customer, technician, branch, index, qc_failed=index < qc_failures)
	finally:
		frappe.flags.a3_import_history = False


def _job_card(customer, technician, branch, index, qc_failed=False):
	day = WORKING_DAYS[index % len(WORKING_DAYS)]
	doc = frappe.new_doc("Service Job Card")
	doc.branch = branch
	doc.customer = customer
	doc.device_type = "Mobile"
	doc.brand = "Samsung"
	doc.device_model = "Samsung Galaxy A55"
	doc.imei_1 = _next_imei()
	doc.complaint_description = "Display flickering after a drop"
	doc.repair_category = "Display"
	doc.received_on = f"{day} 10:00:00"
	doc.assigned_technician = technician
	doc.data_loss_consent = 1
	doc.customer_signature = "data:image/png;base64,iVBORw0KGgo="
	doc.device_photo_1 = "/files/demo-device.jpg"
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
		doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 demo: July job card")
		return

	if qc_failed:
		_status_log(doc, "In Progress", "QC Failed")

	doc.reload()
	doc.status = "Delivered"
	doc.delivered_on = add_to_date(getdate(day), days=2)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)


def _status_log(doc, from_status, to_status):
	log = frappe.new_doc("Job Card Status Log")
	log.parent = doc.name
	log.parenttype = doc.doctype
	log.parentfield = "status_log"
	log.from_status = from_status
	log.to_status = to_status
	log.changed_by = frappe.session.user
	log.changed_on = doc.received_on
	log.flags.ignore_permissions = True
	log.db_insert()


# ------------------------------------------------------------------------ EMI
def _seed_emi_applications():
	coordinator = _employee("Manoj Kumar")
	if not coordinator:
		return

	existing = frappe.db.count(
		"EMI Application",
		{"coordinator": coordinator, "docstatus": 1,
		 "application_date": ["between", [PERIOD_START, PERIOD_END]]},
	)

	scheme = frappe.db.get_value("EMI Scheme", {"is_active": 1}, ["name", "finance_partner"],
	                             as_dict=True) or frappe.db.get_value(
		"EMI Scheme", {}, ["name", "finance_partner"], as_dict=True)
	if not scheme:
		return

	customer = _customer()
	for index in range(existing, EMI_APPLICATIONS):
		day = WORKING_DAYS[index % len(WORKING_DAYS)]
		doc = frappe.new_doc("EMI Application")
		doc.customer = customer
		doc.branch = "Kochi"
		doc.coordinator = coordinator
		doc.application_date = day
		doc.employment_type = "Salaried"
		doc.pan_number = "ABCPK1234F"
		doc.aadhaar_last4 = "4321"
		doc.finance_partner = scheme.finance_partner
		doc.emi_scheme = scheme.name
		doc.invoice_total = 25000
		doc.down_payment = 5000
		doc.tenure_months = 9
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			for row in doc.get("documents") or []:
				row.is_received = 1
				row.attachment = "/files/demo-emi-document.pdf"
			doc.save(ignore_permissions=True)
			doc.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 demo: EMI application")
			continue

		# The first four came back approved the same day — the 24-hour bonus.
		approval_date = getdate(day) if index < EMI_FAST_APPROVALS else add_to_date(getdate(day), days=3)
		frappe.db.set_value(
			"EMI Application", doc.name,
			{
				"status": "Disbursed",
				"submitted_on": f"{day} 11:00:00",
				"partner_application_no": f"DEMO-{index + 1:04d}",
				"approved_loan_amount": 20000,
				"loan_account_number": f"LN{index + 1:08d}",
				"approval_date": approval_date,
				"disbursement_date": add_to_date(approval_date, days=1),
			},
			update_modified=False,
		)


# ---------------------------------------------------------------- telecalling
def _seed_telecalling():
	telecaller = _employee("Sneha M")
	if not telecaller or not frappe.db.exists("DocType", "Call Task"):
		return

	existing = frappe.db.count(
		"Call Task",
		{"assigned_to": telecaller, "outcome": "Converted",
		 "call_datetime": ["between", [PERIOD_START, f"{PERIOD_END} 23:59:59"]]},
	)
	for index in range(existing, TELECALL_CONVERSIONS):
		day = WORKING_DAYS[index % len(WORKING_DAYS)]
		doc = frappe.new_doc("Call Task")
		doc.contact_name = f"July Prospect {index + 1}"
		doc.mobile_no = f"98460{70000 + index:05d}"
		doc.branch = "Kochi"
		doc.assigned_to = telecaller
		doc.scheduled_date = day
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 demo: July call task")
			continue

		frappe.db.set_value(
			"Call Task", doc.name,
			{"call_status": "Connected", "outcome": "Converted",
			 "call_datetime": f"{day} 11:30:00", "attempt_no": 1, "duration_seconds": 180},
			update_modified=False,
		)


# ------------------------------------------------------------------- feedback
def _seed_feedback():
	"""Five-star feedback so the CSAT gate has data to pass on."""
	customer = _customer()
	for employee_name, branch in (("Vipin S", "Kochi"), ("Rafeeq M", "Kozhikode"),
	                              ("Vishnu P", "Kochi"), ("Sajeer K", "Kochi"),
	                              ("Rijo Thomas", "Thiruvananthapuram")):
		employee = _employee(employee_name)
		if not employee:
			continue
		if frappe.db.exists("Customer Feedback", {"attended_employee": employee,
		                                          "feedback_date": ["between", [PERIOD_START, PERIOD_END]]}):
			continue

		for day, rating in (("2026-07-11", 1.0), ("2026-07-22", 0.9)):
			doc = frappe.new_doc("Customer Feedback")
			doc.feedback_date = day
			doc.customer = customer
			doc.branch = branch
			doc.channel = "WhatsApp"
			doc.attended_employee = employee
			doc.overall_rating = rating
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			try:
				doc.insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"A3 demo: feedback {employee_name}")


# -------------------------------------------------------------- incentive runs
def _seed_incentive_runs(company):
	for scheme, branch in RUNS:
		if not frappe.db.exists("Employee Incentive Scheme", scheme):
			continue
		if frappe.db.exists("Incentive Calculation Run",
		                    {"scheme": scheme, "from_date": PERIOD_START, "docstatus": ["<", 2]}):
			continue

		doc = frappe.new_doc("Incentive Calculation Run")
		doc.scheme = scheme
		doc.from_date = PERIOD_START
		doc.to_date = PERIOD_END
		doc.branch = branch
		doc.company = company
		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_permissions=True)
			doc.calculate()
			doc.reload()
			doc.submit()
			doc.reload()
			doc.post_to_payroll()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: incentive run {scheme}")


# ------------------------------------------------------------------- helpers
def _employee(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "name")


def _customer() -> str:
	return (
		frappe.db.get_value("Customer", {"a3_mobile_no": ["is", "set"]}, "name")
		or frappe.db.get_value("Customer", {}, "name")
	)


def _warehouse(branch: str) -> str | None:
	profile = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
	return profile or frappe.db.get_value("Warehouse", {"branch": branch, "is_group": 0}, "name")
