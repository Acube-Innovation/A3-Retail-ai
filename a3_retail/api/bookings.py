# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Bookings — the repairs the counter booked in (`/retail/bookings`).

Reads the Service Job Cards the Mobile Service POS writes. It owns no lifecycle
of its own: the job card decides status, warranty, TAT, parts and money, the
service module raises the advance and the invoice, and the acknowledgement comes
off the same print format the counter hands the customer at intake — so a
booking reads the same wherever it is opened.

What this module adds is the view the counter did not have: every booking in one
list, searchable, and one page per booking showing the device, the work, the
money and everything that has happened to it.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import require_permission
from a3_retail.api.staff import _me

PAGE_SIZES = (20, 50, 100)

# The states a counter thinks in, over the eighteen the job card knows.
GROUPS = {
	"in_shop": list(st.OPEN_STATUSES),
	"waiting": [st.AWAITING_PARTS, st.ON_HOLD, st.ESTIMATE_SENT, st.ESTIMATE_PENDING],
	"ready": [st.READY_FOR_DELIVERY],
	"delivered": [st.DELIVERED, st.CLOSED],
	"closed": [st.DELIVERED, st.CLOSED, st.CANCELLED, st.ESTIMATE_REJECTED],
}

# Pill tone per status, from the colour the desk list view already uses.
TONES = {
	"grey": "pill-sky", "blue": "pill-sky", "orange": "pill-warn", "yellow": "pill-warn",
	"red": "pill-bad", "green": "pill-good", "purple": "pill-purple",
}


def _branch() -> str:
	return _me().branch


def tone_of(status: str) -> str:
	return TONES.get(st.STATUS_COLOURS.get(status, "grey"), "pill-sky")


def _filters(data: dict) -> tuple[str, dict]:
	"""The filter bar as one where-clause the whole page shares."""
	employee = _me()
	conditions = ["jc.docstatus < 2"]
	values = {"branch": employee.branch}

	if (data.get("branch") or "current") != "all":
		conditions.append("jc.branch = %(branch)s")

	if data.get("query"):
		conditions.append(
			"(jc.name like %(like)s or jc.customer_name like %(like)s "
			"or jc.customer_mobile like %(like)s or jc.imei_1 like %(like)s "
			"or jc.serial_no like %(like)s or jc.device_model like %(like)s "
			"or jc.complaint_description like %(like)s)"
		)
		values["like"] = f"%{data['query']}%"

	if data.get("from_date"):
		conditions.append("jc.received_on >= %(from_date)s")
		values["from_date"] = f"{getdate(data['from_date'])} 00:00:00"
	if data.get("to_date"):
		conditions.append("jc.received_on <= %(to_date)s")
		values["to_date"] = f"{getdate(data['to_date'])} 23:59:59"

	status = data.get("status") or "all"
	if status in GROUPS:
		values["statuses"] = GROUPS[status]
		conditions.append("jc.status in %(statuses)s")
	elif status != "all":
		conditions.append("jc.status = %(status)s")
		values["status"] = status

	payment = data.get("payment") or "all"
	if payment == "unpaid":
		conditions.append("jc.outstanding_amount > 0.005")
	elif payment == "paid":
		conditions.append("jc.outstanding_amount <= 0.005 and jc.customer_payable > 0")
	elif payment == "warranty":
		conditions.append("jc.warranty_borne_amount > 0")

	if data.get("technician"):
		conditions.append("jc.assigned_technician = %(technician)s")
		values["technician"] = data["technician"]

	if data.get("priority") and data["priority"] != "all":
		conditions.append("jc.priority = %(priority)s")
		values["priority"] = data["priority"]

	if data.get("delay") == "delayed":
		conditions.append("jc.is_delayed = 1")
	elif data.get("delay") == "ontime":
		conditions.append("ifnull(jc.is_delayed, 0) = 0")

	return " and ".join(conditions), values


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the filter bar needs before anybody types anything."""
	employee = _me()
	require_permission("Service Job Card", "read")

	technicians = frappe.get_all(
		"Technician Profile",
		filters={"branch": employee.branch, "is_active": 1},
		fields=["employee", "employee_name"],
		order_by="employee_name",
	)
	return {
		"branch": employee.branch,
		"statuses": list(st.STATUSES),
		"technicians": [{"name": row.employee, "label": row.employee_name} for row in technicians],
		"can_write": bool(frappe.has_permission("Service Job Card", "write")),
		"can_invoice": bool(frappe.has_permission("Sales Invoice", "create")),
		"can_take_money": bool(frappe.has_permission("Payment Entry", "create")),
	}


@frappe.whitelist()
def summary(filters=None) -> dict:
	"""The cards over the list — same filters as the table, so they agree."""
	_me()
	require_permission("Service Job Card", "read")
	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _filters(data)

	rows = frappe.db.sql(
		f"""
		select jc.status, jc.is_delayed, jc.grand_total, jc.customer_payable,
		       jc.advance_amount, jc.outstanding_amount, jc.warranty_borne_amount,
		       jc.received_on, jc.delivered_on
		from `tabService Job Card` jc where {where}
		""",
		values,
		as_dict=True,
	)

	today = getdate(nowdate())

	def money(subset, field="grand_total") -> float:
		return sum(flt(row.get(field)) for row in subset)

	def group(key) -> list:
		return [row for row in rows if row.status in GROUPS[key]]

	delivered_today = [
		row for row in rows
		if row.delivered_on and getdate(row.delivered_on) == today
	]

	return {
		"total": {"count": len(rows), "amount": money(rows)},
		"in_shop": {"count": len(group("in_shop")), "amount": money(group("in_shop"))},
		"waiting": {"count": len(group("waiting")), "amount": money(group("waiting"))},
		"ready": {"count": len(group("ready")), "amount": money(group("ready"))},
		"delivered": {"count": len(delivered_today), "amount": money(delivered_today)},
		"delayed": {"count": len([row for row in rows if cint(row.is_delayed)]),
		            "amount": money([row for row in rows if cint(row.is_delayed)])},
		"outstanding": {"count": len([row for row in rows if flt(row.outstanding_amount) > 0.005]),
		                "amount": money(rows, "outstanding_amount")},
		"advance": {"count": len([row for row in rows if flt(row.advance_amount) > 0]),
		            "amount": money(rows, "advance_amount")},
	}


@frappe.whitelist()
def list_bookings(filters=None, page: int = 1, page_size: int = 20) -> dict:
	"""The table: one row per booking, with every column the page shows."""
	_me()
	require_permission("Service Job Card", "read")

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _filters(data)

	page = max(cint(page), 1)
	size = cint(page_size) if cint(page_size) in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	total = frappe.db.sql(
		f"select count(*) from `tabService Job Card` jc where {where}", values)[0][0]

	rows = frappe.db.sql(
		f"""
		select jc.name, jc.status, jc.docstatus, jc.branch, jc.priority,
		       jc.customer, jc.customer_name, jc.customer_mobile,
		       jc.device_type, jc.brand, jc.device_model, jc.imei_1, jc.serial_no,
		       jc.complaint_description, jc.repair_category, jc.warranty_type,
		       jc.received_on, jc.estimated_delivery_date, jc.delivered_on,
		       jc.is_delayed, jc.delay_hours, jc.assigned_technician,
		       jc.grand_total, jc.customer_payable, jc.advance_amount,
		       jc.outstanding_amount, jc.warranty_borne_amount, jc.payment_status,
		       jc.sales_invoice,
		       (select count(*) from `tabJob Card Part` p where p.parent = jc.name) as part_count,
		       (select count(*) from `tabJob Card Labour` l where l.parent = jc.name) as labour_count
		from `tabService Job Card` jc
		where {where}
		order by jc.received_on desc, jc.creation desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	models = {row.device_model for row in rows if row.device_model}
	names = dict(frappe.get_all(
		"Device Model", filters={"name": ["in", list(models)]} if models else {"name": ""},
		fields=["name", "model_name"], as_list=True,
	)) if models else {}

	technicians = {row.assigned_technician for row in rows if row.assigned_technician}
	staff = dict(frappe.get_all(
		"Employee", filters={"name": ["in", list(technicians)]} if technicians else {"name": ""},
		fields=["name", "employee_name"], as_list=True,
	)) if technicians else {}

	for row in rows:
		row["device"] = names.get(row.device_model) or row.device_model or row.device_type
		row["technician_name"] = staff.get(row.assigned_technician)
		row["tone"] = tone_of(row.status)
		row["balance"] = flt(row.outstanding_amount)
		row["is_open"] = row.status in st.OPEN_STATUSES
		row["editable"] = cint(row.docstatus) == 0
		row["overdue"] = bool(cint(row.is_delayed))

	return {
		"rows": rows,
		"total": total,
		"page": page,
		"page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


# ---------------------------------------------------------------------------
# One booking
# ---------------------------------------------------------------------------
@frappe.whitelist()
def booking(name: str) -> dict:
	"""Everything the booking page shows, read from the job card itself."""
	doc = _open_booking(name)

	return {
		"name": doc.name,
		"status": doc.status,
		"tone": tone_of(doc.status),
		"docstatus": cint(doc.docstatus),
		"branch": doc.branch,
		"company": doc.company,
		"priority": doc.priority,
		"lead_source": doc.lead_source,
		"received_on": str(doc.received_on or ""),
		"received_by": _employee_name(doc.received_by),
		"promised": str(doc.estimated_delivery_date or ""),
		"delivered_on": str(doc.delivered_on or ""),
		"is_delayed": bool(cint(doc.is_delayed)),
		"delay_hours": flt(doc.delay_hours),
		"sla_due_on": str(doc.sla_due_on or ""),
		"technician": doc.assigned_technician,
		"technician_name": _employee_name(doc.assigned_technician),
		"customer": {
			"name": doc.customer,
			"customer_name": doc.customer_name,
			"mobile_no": doc.customer_mobile,
			"alternate_mobile": doc.alternate_mobile,
			"email": doc.customer_email,
			"is_repeat": bool(cint(doc.is_repeat_customer)),
		},
		"device": {
			"device_type": doc.device_type,
			"brand": doc.brand,
			"model": frappe.db.get_value("Device Model", doc.device_model, "model_name")
			or doc.device_model,
			"model_code": doc.device_model,
			"imei_1": doc.imei_1,
			"imei_2": doc.imei_2,
			"serial_no": doc.serial_no,
			"sold_by_us": bool(cint(doc.sold_by_us)),
			"purchase_date": str(doc.device_purchase_date or ""),
			"condition": doc.physical_condition,
			"photos": [doc.get(f"device_photo_{index}") for index in range(1, 5)
			           if doc.get(f"device_photo_{index}")],
		},
		"warranty": {
			"type": doc.warranty_type,
			"expiry": str(doc.warranty_expiry_date or ""),
			"registration": doc.warranty_registration,
			"chargeable": bool(cint(doc.is_chargeable)),
			"borne": flt(doc.warranty_borne_amount),
		},
		"complaint": doc.complaint_description,
		"issues": [row.issue_type for row in doc.get("reported_issues") or []],
		"repair_category": doc.repair_category,
		"diagnosis": doc.diagnosis_notes,
		"root_cause": doc.root_cause,
		"accessories": [
			{"accessory": row.accessory, "received": bool(cint(row.received)),
			 "condition": row.condition, "returned": bool(cint(row.returned))}
			for row in doc.get("device_condition_checklist") or []
		],
		"parts": [
			{"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty),
			 "rate": flt(row.rate), "amount": flt(row.amount), "status": row.part_status,
			 "warranty": bool(cint(row.is_warranty_covered)),
			 "customer_provided": bool(cint(row.is_customer_provided)),
			 "serial_no": row.serial_no}
			for row in doc.get("parts") or []
		],
		"labour": [
			{"item_code": row.service_item, "description": row.description,
			 "technician": _employee_name(row.technician), "qty": flt(row.qty),
			 "rate": flt(row.rate), "amount": flt(row.amount),
			 "warranty": bool(cint(row.is_warranty_covered))}
			for row in doc.get("labour") or []
		],
		"totals": {
			"parts": flt(doc.parts_total),
			"labour": flt(doc.labour_total),
			"before_discount": flt(doc.total_before_discount),
			"discount": flt(doc.discount_amount),
			"discount_reason": doc.discount_reason,
			"taxable": flt(doc.net_total),
			"tax": flt(doc.tax_amount),
			"grand_total": flt(doc.grand_total),
			"warranty_borne": flt(doc.warranty_borne_amount),
			"payable": flt(doc.customer_payable),
			"advance": flt(doc.advance_amount),
			"balance": flt(doc.outstanding_amount),
			"payment_status": doc.payment_status,
		},
		"payments": _payments(doc),
		"delivery": {
			"mode": doc.delivery_mode,
			"ready_on": str(doc.ready_on or ""),
			"otp_verified": bool(cint(doc.otp_verified)),
			"otp_pending": doc.status == st.READY_FOR_DELIVERY and not cint(doc.otp_verified),
			"receiver": doc.receiver_name,
			"delivered_by": _employee_name(doc.delivered_by),
			"accessories_returned": bool(cint(doc.accessories_returned)),
		},
		"feedback": {"rating": flt(doc.feedback_rating), "comments": doc.feedback_comments}
		if doc.feedback_rating or doc.feedback_comments else None,
		"sales_invoice": doc.sales_invoice,
		"activity": activity(doc.name),
		"can": _can(doc),
		"print_url": print_url(doc.name),
		"invoice_url": _invoice_url(doc.sales_invoice) if doc.sales_invoice else None,
		"counter_url": f"/retail/service?booking={frappe.utils.quoted(doc.name)}",
	}


def _open_booking(name: str):
	"""The job card, once this branch is allowed to see it."""
	employee = _me()
	require_permission("Service Job Card", "read")

	if not frappe.db.exists("Service Job Card", name):
		frappe.throw(_("There is no booking numbered {0}.").format(name),
		             title=_("Booking not found"))

	doc = frappe.get_doc("Service Job Card", name)
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That booking belongs to another branch."), title=_("Not this branch"))
	return doc


def _employee_name(employee: str | None) -> str | None:
	return frappe.db.get_value("Employee", employee, "employee_name") if employee else None


def _can(doc) -> dict:
	"""What this person may do to this booking, asked of ERPNext each time."""
	live = cint(doc.docstatus) == 1 and doc.status not in st.TERMINAL_STATUSES
	return {
		"write": bool(frappe.has_permission("Service Job Card", "write", doc)),
		"take_money": bool(frappe.has_permission("Payment Entry", "create")) and live,
		"invoice": bool(frappe.has_permission("Sales Invoice", "create"))
		and not doc.sales_invoice and cint(doc.docstatus) == 1,
		"deliver": doc.status == st.READY_FOR_DELIVERY,
		"note": bool(frappe.has_permission("Service Job Card", "write", doc)),
	}


def _payments(doc) -> list[dict]:
	"""What the customer has actually handed over against this repair."""
	out = []
	for row in frappe.db.sql(
		"""
		select pe.name, pe.posting_date, pe.creation, pe.payment_type, pe.mode_of_payment,
		       pe.paid_amount, pe.reference_no, pe.remarks
		from `tabPayment Entry` pe
		where pe.docstatus = 1 and pe.reference_no = %(card)s
		order by pe.posting_date, pe.creation
		""",
		{"card": doc.name},
		as_dict=True,
	):
		out.append({
			"name": row.name,
			"date": str(row.posting_date),
			# The timeline is a sequence, and a posting date alone would put the
			# money before the device it was taken for.
			"at": str(row.creation),
			"mode": row.mode_of_payment,
			"amount": flt(row.paid_amount),
			"kind": _("Refund") if row.payment_type == "Pay" else _("Advance"),
			"reference": row.reference_no or "",
		})

	if doc.sales_invoice:
		for row in frappe.db.sql(
			"""
			select pe.name, pe.posting_date, pe.creation, pe.mode_of_payment,
			       per.allocated_amount
			from `tabPayment Entry Reference` per
			join `tabPayment Entry` pe on pe.name = per.parent
			where per.reference_doctype = 'Sales Invoice' and per.reference_name = %(invoice)s
			  and pe.docstatus = 1
			order by pe.posting_date
			""",
			{"invoice": doc.sales_invoice},
			as_dict=True,
		):
			if any(paid["name"] == row.name for paid in out):
				continue
			out.append({
				"name": row.name, "date": str(row.posting_date), "at": str(row.creation),
				"mode": row.mode_of_payment, "amount": flt(row.allocated_amount),
				"kind": _("Against the invoice"), "reference": doc.sales_invoice,
			})
	return out


@frappe.whitelist()
def activity(name: str) -> list[dict]:
	"""Everything that has happened to this booking, oldest first.

	Four sources, one list: the job card's own status log, the money, the
	messages the customer was sent, and whatever staff typed as a note.
	"""
	doc = _open_booking(name)
	events = [{
		"kind": "intake",
		"label": _("Booked in"),
		"at": str(doc.received_on or doc.creation),
		"by": _employee_name(doc.received_by) or doc.owner,
		"note": doc.complaint_description,
	}]

	for row in doc.get("status_log") or []:
		events.append({
			"kind": "status",
			"label": _("{0} → {1}").format(_(row.from_status or st.DRAFT), _(row.to_status)),
			"at": str(row.changed_on),
			"by": frappe.db.get_value("User", row.changed_by, "full_name") or row.changed_by,
			"note": row.remarks,
			"tone": tone_of(row.to_status),
		})

	for payment in _payments(doc):
		events.append({
			"kind": "money",
			"label": _("{0} — {1}").format(
				payment["kind"], frappe.utils.fmt_money(payment["amount"], currency="INR")),
			"at": payment.get("at") or payment["date"],
			"by": payment["mode"] or "",
			"note": payment["name"],
		})

	if doc.sales_invoice:
		events.append({
			"kind": "invoice",
			"label": _("Invoiced"),
			"at": str(frappe.db.get_value("Sales Invoice", doc.sales_invoice, "posting_date") or ""),
			"by": "",
			"note": doc.sales_invoice,
		})

	if frappe.db.exists("DocType", "WhatsApp Message Log"):
		for row in frappe.get_all(
			"WhatsApp Message Log",
			filters={"reference_doctype": "Service Job Card", "reference_name": doc.name},
			fields=["template", "status", "to_number", "sent_on", "creation", "error_message"],
			order_by="creation",
		):
			events.append({
				"kind": "message",
				"label": _("Message: {0}").format(row.template or _("update")),
				"at": str(row.sent_on or row.creation),
				"by": row.to_number or "",
				"note": row.error_message or row.status,
			})

	for row in frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Service Job Card", "reference_name": doc.name,
		         "comment_type": "Comment"},
		fields=["content", "comment_email", "comment_by", "creation"],
		order_by="creation",
	):
		events.append({
			"kind": "note",
			"label": _("Note"),
			"at": str(row.creation),
			"by": row.comment_by or row.comment_email,
			"note": frappe.utils.strip_html(row.content or "").strip(),
		})

	if doc.delivered_on:
		events.append({
			"kind": "delivery",
			"label": _("Handed over"),
			"at": str(doc.delivered_on),
			"by": _employee_name(doc.delivered_by) or "",
			"note": doc.receiver_name,
		})

	events.sort(key=lambda event: str(event["at"] or ""))
	return events


# ---------------------------------------------------------------------------
# What the page may do to a booking
# ---------------------------------------------------------------------------
@frappe.whitelist()
def print_url(name: str) -> str:
	"""The acknowledgement the customer walks out with — the counter's own."""
	from a3_retail.api.service_pos import estimate_url

	_open_booking(name)
	return estimate_url(name)


def _invoice_url(invoice: str) -> str:
	from a3_retail.api.pos import print_url as invoice_print_url

	return invoice_print_url(invoice)


# ---------------------------------------------------------------------------
# Working the repair
# ---------------------------------------------------------------------------
#: What each step means to the person pressing it. The state machine decides
#: which are offered; this only decides how they read on a button.
STEP_WORDS = {
	st.UNDER_DIAGNOSIS: ("Start diagnosis", "Look at the device and find the fault"),
	st.ESTIMATE_PENDING: ("Needs an estimate", "The repair has to be quoted first"),
	st.ESTIMATE_SENT: ("Estimate sent", "The customer has been given the figure"),
	st.ESTIMATE_APPROVED: ("Customer approved", "Go ahead with the repair"),
	st.ESTIMATE_REJECTED: ("Customer refused", "Hand the device back unrepaired"),
	st.AWAITING_PARTS: ("Waiting for parts", "The part is not on the shelf"),
	st.IN_PROGRESS: ("Start the repair", "Work is under way"),
	st.ON_HOLD: ("Put on hold", "Stopped for now — say why"),
	st.REPAIR_COMPLETED: ("Repair done", "Ready to be checked"),
	st.QC_PASSED: ("Checked and passed", "The repair holds up"),
	st.QC_FAILED: ("Failed the check", "Back to the bench"),
	st.NOT_REPAIRABLE: ("Cannot be repaired", "Hand it back unrepaired"),
	st.READY_FOR_DELIVERY: ("Ready for the customer", "Sends the collection code"),
	st.DELIVERED: ("Handed over", "Use the Hand over button — it needs the code"),
	st.CLOSED: ("Close the job", "Nothing further to do"),
	st.CANCELLED: ("Cancel the job", "Say why"),
}

#: Steps that must say why. A card that stalls with no reason is the one nobody
#: can answer the customer about.
NEEDS_REASON = (st.ON_HOLD, st.CANCELLED, st.NOT_REPAIRABLE, st.QC_FAILED)

#: Delivery is its own action — it needs the customer's code, the accessories
#: back and the balance settled, so it is never just a status button.
NOT_A_BUTTON = (st.DELIVERED,)


@frappe.whitelist()
def steps(name: str) -> dict:
	"""Where this job card is, and the steps it may take from here."""
	doc = _open_booking(name)
	may_write = bool(frappe.has_permission("Service Job Card", "write", doc))

	# Some steps are somebody else's to take — a technician does not pass QC on
	# their own repair. The state machine refuses those anyway; offering a
	# button that is going to be refused is the thing worth avoiding.
	mine = set(frappe.get_roles())
	offered = []
	for status in st.next_statuses(doc.status):
		if status in NOT_A_BUTTON:
			continue
		needed = st.TRANSITION_ROLES.get(status)
		if needed and frappe.session.user != "Administrator" \
				and not (set(needed) | {"System Manager"}) & mine:
			continue
		label, hint = STEP_WORDS.get(status, (status, ""))
		offered.append({
			"status": status,
			"label": label,
			"hint": hint,
			"needs_reason": status in NEEDS_REASON,
			"tone": tone_of(status),
		})

	# When every way forward belongs to someone else, say whose — otherwise the
	# bench sees an empty panel and no reason for it.
	waiting_on = ""
	if may_write and not offered:
		others = []
		for status in st.next_statuses(doc.status):
			for role in st.TRANSITION_ROLES.get(status, ()):
				if role not in others:
					others.append(role)
		if others:
			waiting_on = _("The next step on this repair is for {0}.").format(
				" or ".join(others[:3]))

	return {
		"status": doc.status,
		"tone": tone_of(doc.status),
		"can_work": may_write,
		"steps": offered if may_write else [],
		"waiting_on": waiting_on,
		"technician": doc.assigned_technician,
		"technician_name": _employee_name(doc.assigned_technician),
		"diagnosis": doc.diagnosis_notes or "",
		"root_cause": doc.root_cause or "",
		# A Select on the doctype, not free text — the screen has to offer the
		# same list the document will accept, or every save is refused.
		"root_causes": [choice for choice in (
			frappe.get_meta("Service Job Card").get_field("root_cause").options or ""
		).split("\n")],
		"require_otp": bool(frappe.db.get_single_value(
			"A3 Retail Settings", "require_delivery_otp")),
		"accessories_out": [
			row.accessory for row in doc.get("device_condition_checklist") or []
			if cint(row.received) and not cint(row.returned)
		],
	}


@frappe.whitelist()
def advance(name: str, status: str, remarks: str | None = None) -> dict:
	"""Move the job card one step, through the same rules the desk obeys.

	The branch app is where the work actually happens, so the whole repair has
	to be drivable from it. What it must not do is invent its own path through
	the states — `set_status` on the doctype owns that, and this only decides
	whether the person is allowed to ask.
	"""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)

	status = (status or "").strip()
	if status in NOT_A_BUTTON:
		frappe.throw(_("Use Hand over to deliver — it needs the customer's code."),
		             title=_("Not this way"))
	if status not in st.next_statuses(doc.status):
		frappe.throw(
			_("A job card at {0} cannot go straight to {1}.").format(doc.status, status),
			title=_("Not the next step"),
		)
	reason = (remarks or "").strip()
	if status in NEEDS_REASON and not reason:
		frappe.throw(_("Say why, so whoever picks this up next knows."),
		             title=_("A reason is needed"))

	from a3_retail.a3_retail_service.doctype.service_job_card.service_job_card import set_status

	moved = set_status(name, status, reason or None)
	if reason:
		doc.reload()
		doc.add_comment("Comment", text=f"{status}: {reason}")
	return moved


@frappe.whitelist()
def assign(name: str, technician: str) -> dict:
	"""Put the card on a technician's bench."""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)

	if not frappe.db.exists("Employee", {"name": technician, "branch": doc.branch,
	                                     "status": "Active"}):
		frappe.throw(_("That technician does not work at {0}.").format(doc.branch),
		             title=_("Not this branch"))

	from a3_retail.a3_retail_service.doctype.service_job_card.service_job_card import assign_technician

	return assign_technician(name, technician)


@frappe.whitelist()
def diagnose(name: str, diagnosis: str | None = None, root_cause: str | None = None) -> dict:
	"""What was found when the device was opened.

	Kept apart from the status buttons because it is written while the card sits
	at Under Diagnosis, often over a couple of visits to the bench.
	"""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)

	cause = (root_cause or "").strip()
	allowed = (frappe.get_meta("Service Job Card").get_field("root_cause").options
	           or "").split("\n")
	if cause and cause not in allowed:
		frappe.throw(_("{0} is not one of the causes this form offers.").format(cause),
		             title=_("Pick a cause"))

	doc.diagnosis_notes = (diagnosis or "").strip()[:2000] or None
	doc.root_cause = cause or None
	doc.save()
	return {"job_card": doc.name, "diagnosis": doc.diagnosis_notes or "",
	        "root_cause": doc.root_cause or ""}


@frappe.whitelist()
def return_accessories(name: str) -> dict:
	"""Everything that came in with the device, handed back.

	Delivery refuses while anything is outstanding, so this is the step that
	unblocks it — and it is a real check, not a formality: the charger left in
	the drawer is the commonest complaint after a repair.
	"""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)

	handed = 0
	for row in doc.get("device_condition_checklist") or []:
		if cint(row.received) and not cint(row.returned):
			row.returned = 1
			handed += 1
	doc.accessories_returned = 1
	doc.save()
	return {"job_card": doc.name, "returned": handed}


@frappe.whitelist()
def hand_over(name: str, otp: str, receiver: str | None = None) -> dict:
	"""Give the device back, against the customer's code."""
	_open_booking(name)   # branch guard

	from a3_retail.api.service import deliver_job_card

	return deliver_job_card(name, otp=otp, receiver=receiver)


@frappe.whitelist()
def lines(name: str) -> dict:
	"""What is on the repair, and whether it can still be changed."""
	doc = _open_booking(name)
	rows = []
	for row in doc.get("parts") or []:
		rows.append({
			"row": row.name, "kind": "Part", "item_code": row.item_code,
			"item_name": row.item_name or row.item_code, "qty": flt(row.qty),
			"rate": flt(row.rate), "amount": flt(row.amount),
			"status": row.part_status or "",
			"warranty": bool(cint(row.is_warranty_covered)),
		})
	for row in doc.get("labour") or []:
		rows.append({
			"row": row.name, "kind": "Service", "item_code": row.service_item,
			"item_name": row.description or row.service_item, "qty": flt(row.qty),
			"rate": flt(row.rate), "amount": flt(row.amount),
			"status": "", "warranty": bool(cint(row.is_warranty_covered)),
		})

	# Once the bill is raised the lines are what the customer was charged, so
	# they stop being editable here — a change then belongs on a credit note.
	return {
		"rows": rows,
		"can_edit": bool(frappe.has_permission("Service Job Card", "write", doc))
		and not doc.sales_invoice and doc.status not in st.TERMINAL_STATUSES,
		"invoiced": bool(doc.sales_invoice),
		"totals": {"parts": flt(doc.parts_total), "labour": flt(doc.labour_total),
		           "grand_total": flt(doc.grand_total)},
	}


@frappe.whitelist()
def add_line(name: str, item_code: str, kind: str = "Part", qty: float = 1,
             rate: float | None = None) -> dict:
	"""Put a part or a charge on a repair that is already open.

	What a device needs is not known when it is booked in — the fault is found
	at the bench, and the part is chosen after that. Making the counter guess at
	intake is how a repair gets billed for the wrong thing.
	"""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)
	_editable(doc)

	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("{0} is not an item we carry.").format(item_code))

	item = frappe.db.get_value("Item", item_code, ["item_name", "is_stock_item"],
	                           as_dict=True)
	if rate is None:
		from a3_retail.api.service_pos import _selling_rate

		rate = _selling_rate(item_code)

	if (kind or "Part").strip().title() == "Service":
		doc.append("labour", {
			"service_item": item_code, "description": item.item_name,
			"technician": doc.assigned_technician,
			"qty": flt(qty) or 1, "rate": flt(rate)})
	else:
		doc.append("parts", {
			"item_code": item_code, "item_name": item.item_name,
			"qty": flt(qty) or 1, "rate": flt(rate)})
	doc.save()
	return lines(name)


@frappe.whitelist()
def update_line(name: str, row: str, qty: float | None = None,
                rate: float | None = None) -> dict:
	"""Change how many, or what it costs."""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)
	_editable(doc)

	line = _find_line(doc, row)
	if qty is not None:
		if flt(qty) <= 0:
			frappe.throw(_("A line needs a quantity. Remove it instead."))
		line.qty = flt(qty)
	if rate is not None:
		if flt(rate) < 0:
			frappe.throw(_("A price cannot be less than nothing."))
		line.rate = flt(rate)
	doc.save()
	return lines(name)


@frappe.whitelist()
def remove_line(name: str, row: str) -> dict:
	"""Take a part or a charge off the repair."""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)
	_editable(doc)

	line = _find_line(doc, row)
	# A part already taken off the shelf has to be put back before it leaves the
	# bill, or the stock and the paperwork stop agreeing.
	if line.parentfield == "parts" and (line.get("part_status") or "") in (
			"Issued", "Consumed"):
		frappe.throw(
			_("{0} has already been issued from the store. Return it first.").format(
				line.item_name or line.item_code),
			title=_("Already issued"),
		)
	doc.remove(line)
	doc.save()
	return lines(name)


def _editable(doc) -> None:
	if doc.sales_invoice:
		frappe.throw(
			_("This repair has been billed on {0}. What the customer was charged "
			  "cannot be changed here.").format(doc.sales_invoice),
			title=_("Already billed"),
		)
	if doc.status in st.TERMINAL_STATUSES:
		frappe.throw(_("This job is finished."), title=_("Closed"))


def _find_line(doc, row: str):
	for field in ("parts", "labour"):
		for line in doc.get(field) or []:
			if line.name == row:
				return line
	frappe.throw(_("That line is no longer on this repair."), title=_("Not found"))


@frappe.whitelist()
def invoice_now(name: str) -> dict:
	"""Bill the repair from the bench, and hand back something to print."""
	_open_booking(name)   # branch guard

	from a3_retail.api.service_pos import generate_invoice

	return generate_invoice(name)


@frappe.whitelist()
def technicians() -> list[dict]:
	"""Who can be put on a repair at this branch."""
	_me()
	from a3_retail.api.service_pos import technicians as bench

	return bench()


@frappe.whitelist()
def add_note(name: str, text: str) -> dict:
	"""A line in the booking's own timeline — a Comment, like anywhere else."""
	doc = _open_booking(name)
	require_permission("Service Job Card", "write", doc)

	text = (text or "").strip()
	if not text:
		frappe.throw(_("Write the note first."), title=_("Nothing to add"))

	comment = doc.add_comment("Comment", text)
	return {"comment": comment.name, "at": str(now_datetime())}


@frappe.whitelist()
def collect(name: str, amount: float, mode_of_payment: str = "Cash") -> dict:
	"""Take money against a repair — the service module's own advance."""
	from a3_retail.api.service import take_advance

	doc = _open_booking(name)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("How much did the customer hand over?"), title=_("Amount needed"))

	owed = flt(doc.outstanding_amount)
	if owed > 0 and amount > owed + 0.005:
		frappe.throw(
			_("That is more than the {0} still owed on this repair.").format(
				frappe.utils.fmt_money(owed, currency="INR")),
			title=_("More than the balance"),
		)

	taken = take_advance(doc.name, amount, mode_of_payment)
	doc.reload()
	return {
		"payment_entry": taken["payment_entry"],
		"advance": flt(taken["advance_amount"]),
		"balance": flt(doc.outstanding_amount),
		"payment_status": doc.payment_status,
	}


@frappe.whitelist()
def notify(name: str, channel: str = "WhatsApp") -> dict:
	"""Tell the customer where their repair stands — the counter's own message."""
	from a3_retail.api.service_pos import notify as counter_notify

	_open_booking(name)
	return counter_notify(name, channel)


@frappe.whitelist()
def resend_otp(name: str) -> dict:
	"""Re-send the collection OTP for a device that is ready."""
	from a3_retail.api.service_pos import resend_otp as counter_resend

	_open_booking(name)
	return counter_resend(name)


@frappe.whitelist()
def invoice(name: str) -> dict:
	"""Bill the repair. The service module owns the accounting."""
	from a3_retail.api.service_pos import generate_invoice

	_open_booking(name)
	return generate_invoice(name)
