"""A3 Retail — service desk API (scope 3.5, 3.9).

Advances, invoicing and OTP-verified delivery. Every money movement goes through
a standard ERPNext document (golden rule 4): this module orchestrates, it never
writes GL or stock ledger entries itself.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import parse_payload, require_branch_access, require_permission, require_role
from a3_retail.utils import money
from a3_retail.utils.branch import get_branch_profile, get_user_branch


# ---------------------------------------------------------------------------
# Lookups (used by the Reception Desk and POS)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def lookup_customer(mobile_no: str) -> dict:
	"""Customer, their devices, past jobs and outstanding — by mobile number."""
	from a3_retail.api.customer import find_by_mobile

	require_permission("Customer", "read")
	profile = find_by_mobile(mobile_no)
	return profile or {"found": False, "mobile_no": mobile_no}


@frappe.whitelist()
def lookup_imei(imei: str) -> dict:
	"""Device history for an IMEI — counter staff only, it exposes a customer."""
	from a3_retail.overrides.serial_no import lookup_imei as _lookup

	require_permission("Serial No", "read")
	return _lookup(imei)


@frappe.whitelist()
def dashboard_counters(branch: str | None = None) -> dict:
	"""Reception header counters (scope 3.9)."""
	require_permission("Service Job Card", "read")
	branch = branch or get_user_branch()
	require_branch_access(branch)

	base = {"docstatus": 1}
	if branch:
		base["branch"] = branch

	today = nowdate()
	return {
		"branch": branch,
		"today_in": frappe.db.count(
			"Service Job Card", {**base, "received_on": [">=", f"{today} 00:00:00"]}
		),
		"delivered_today": frappe.db.count(
			"Service Job Card", {**base, "status": st.DELIVERED, "delivered_on": [">=", f"{today} 00:00:00"]}
		),
		"pending": frappe.db.count("Service Job Card", {**base, "status": ["in", list(st.OPEN_STATUSES)]}),
		"ready": frappe.db.count("Service Job Card", {**base, "status": st.READY_FOR_DELIVERY}),
		"delayed": frappe.db.count("Service Job Card", {**base, "is_delayed": 1,
		                                                "status": ["not in", list(st.TERMINAL_STATUSES)]}),
	}


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
@frappe.whitelist()
def create_job_card(payload) -> dict:
	"""One-call intake from the Reception Desk (scope 3.9)."""
	from a3_retail.api.customer import get_or_create

	require_permission("Service Job Card", "create")
	data = parse_payload(payload)

	branch = data.get("branch") or get_user_branch()
	require_branch_access(branch)

	customer = data.get("customer")
	if not customer:
		profile = get_or_create(
			mobile_no=data.get("mobile_no"),
			customer_name=data.get("customer_name"),
			branch=branch,
			marketing_optin=data.get("marketing_optin", 1),
		)
		customer = profile["name"]

	doc = frappe.new_doc("Service Job Card")
	doc.branch = branch
	doc.customer = customer
	doc.device_type = data.get("device_type") or "Mobile"
	doc.brand = data.get("brand")
	doc.device_model = data.get("device_model")
	doc.imei_1 = data.get("imei_1")
	doc.imei_2 = data.get("imei_2")
	doc.complaint_description = data.get("complaint_description")
	doc.repair_category = data.get("repair_category")
	doc.priority = data.get("priority") or "Normal"
	doc.physical_condition = data.get("physical_condition")
	doc.device_password = data.get("device_password")
	doc.data_backup_required = cint(data.get("data_backup_required"))
	doc.data_loss_consent = cint(data.get("data_loss_consent"))
	doc.customer_signature = data.get("customer_signature")
	doc.lead_source = data.get("lead_source") or "Walk-in"
	doc.delivery_mode = data.get("delivery_mode") or "Counter Pickup"
	doc.received_on = data.get("received_on") or now_datetime()

	for index in range(1, 5):
		photo = data.get(f"device_photo_{index}")
		if photo:
			doc.set(f"device_photo_{index}", photo)

	for issue in data.get("reported_issues") or []:
		doc.append("reported_issues", {"issue_type": issue})

	for accessory in data.get("accessories") or []:
		doc.append(
			"device_condition_checklist",
			{
				"accessory": accessory.get("accessory"),
				"received": cint(accessory.get("received")),
				"condition": accessory.get("condition") or "Good",
			},
		)

	doc.insert()
	doc.submit()

	result = {
		"job_card": doc.name,
		"status": doc.status,
		"promised": str(doc.estimated_delivery_date or ""),
		"customer": customer,
	}

	advance = flt(data.get("advance_amount"))
	if advance > 0:
		result["payment_entry"] = take_advance(
			doc.name, advance, data.get("advance_mode") or "Cash"
		)["payment_entry"]

	return result


# ---------------------------------------------------------------------------
# Advances (scope 3.5)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def take_advance(job_card: str, amount: float, mode_of_payment: str = "Cash") -> dict:
	"""Collect an advance as a standard Payment Entry (Receive, is_advance)."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)
	require_permission("Payment Entry", "create")

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Advance amount must be greater than zero."))

	profile = get_branch_profile(doc.branch)
	company = doc.company or (profile.company if profile else None)

	payment = frappe.new_doc("Payment Entry")
	payment.payment_type = "Receive"
	payment.party_type = "Customer"
	payment.party = doc.customer
	payment.company = company
	payment.posting_date = getdate(nowdate())
	payment.mode_of_payment = mode_of_payment
	payment.paid_amount = amount
	payment.received_amount = amount
	payment.source_exchange_rate = 1
	payment.target_exchange_rate = 1
	payment.paid_to = _mode_account(mode_of_payment, company)
	payment.paid_from = _receivable_account(company)
	payment.branch = doc.branch
	if payment.meta.has_field("a3_service_job_card"):
		payment.a3_service_job_card = doc.name
	if payment.meta.has_field("cost_center") and profile:
		payment.cost_center = profile.service_cost_center or profile.cost_center
	payment.reference_no = doc.name
	payment.reference_date = getdate(nowdate())
	payment.remarks = _("Advance against Service Job Card {0}").format(doc.name)

	payment.flags.ignore_permissions = False
	payment.insert()
	payment.submit()

	total_advance = money(flt(doc.advance_amount) + amount)
	doc.db_set("advance_amount", total_advance, update_modified=False)
	doc.db_set("advance_payment_entry", payment.name, update_modified=False)
	doc.db_set("outstanding_amount", money(flt(doc.customer_payable) - total_advance),
	           update_modified=False)
	# "Paid" only once there is a charge and the advance covers it — an advance
	# taken at intake, before any parts or labour exist, is not a paid job.
	payable = flt(doc.customer_payable)
	doc.db_set(
		"payment_status",
		"Paid" if payable > 0 and total_advance >= payable else "Partly Paid (Advance)",
		update_modified=False,
	)

	return {"payment_entry": payment.name, "advance_amount": total_advance}


def _mode_account(mode_of_payment: str, company: str) -> str:
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
	)
	if account:
		return account

	fallback = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
	)
	if not fallback:
		frappe.throw(_("No cash or bank account is configured for {0}.").format(company))
	return fallback


def _receivable_account(company: str) -> str:
	account = frappe.get_cached_value("Company", company, "default_receivable_account")
	if account:
		return account
	return frappe.db.get_value(
		"Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
	)


# ---------------------------------------------------------------------------
# Invoicing (scope 3.5, 3.11)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def create_sales_invoice(job_card: str) -> dict:
	"""Invoice the approved work, consuming parts from the Service Bay.

	`update_stock=1` with `set_warehouse` on the service warehouse is what turns
	the issued parts into a stock consumption at the moment of billing (3.11).
	Warranty-borne lines are billed at zero and the cost lands in Warranty Expense.
	"""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)
	require_permission("Sales Invoice", "create")

	if doc.sales_invoice:
		return {"sales_invoice": doc.sales_invoice, "created": False}

	profile = get_branch_profile(doc.branch)
	service_warehouse = profile.service_warehouse if profile else None

	invoice = frappe.new_doc("Sales Invoice")
	invoice.customer = doc.customer
	invoice.company = doc.company
	invoice.posting_date = getdate(nowdate())
	invoice.due_date = getdate(nowdate())
	invoice.branch = doc.branch
	invoice.update_stock = 1
	invoice.set_warehouse = service_warehouse
	if invoice.meta.has_field("a3_service_job_card"):
		invoice.a3_service_job_card = doc.name
	if doc.sales_order:
		invoice.items = []

	for row in doc.get("parts") or []:
		if row.is_customer_provided:
			continue
		invoice.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.qty),
				# Warranty-covered lines are billed at zero to the customer.
				"rate": 0 if row.is_warranty_covered else flt(row.rate),
				"warehouse": row.warehouse or service_warehouse,
				"serial_no": row.serial_no,
				"sales_order": doc.sales_order or None,
			},
		)

	for row in doc.get("labour") or []:
		invoice.append(
			"items",
			{
				"item_code": row.service_item,
				"qty": flt(row.qty),
				"rate": 0 if row.is_warranty_covered else flt(row.rate),
				"sales_order": doc.sales_order or None,
			},
		)

	if not invoice.items:
		frappe.throw(_("There is nothing to invoice on {0}.").format(doc.name))

	if doc.tax_template:
		invoice.taxes_and_charges = doc.tax_template
		invoice.set_taxes()
	else:
		# A repair is a taxable supply like any other. Without this the invoice
		# went out at the pre-tax amount while the job card had already told the
		# customer the figure with GST on it.
		from a3_retail.api.pos import _apply_gst

		_apply_gst(invoice, doc.branch)

	# The role check above is the gate. The document itself is written with
	# permissions bypassed because pricing a service invoice makes ERPNext read
	# the income accounts and cost centers that shop-floor staff are deliberately
	# not allowed to see (scope 11.1) — the same reason the sales counter writes
	# its invoice this way.
	invoice.flags.ignore_permissions = True
	invoice.set_missing_values()
	_stamp_service_cost_center(invoice, profile)
	invoice.insert(ignore_permissions=True)

	# Pull the advance in so the customer ledger nets to zero (scope 3.5).
	# Allocating it walks back into the advance's own Payment Entry, and ERPNext
	# re-checks read permission on it document by document — a check a counter
	# cannot pass on an entry the system raised. The gate is the role check above.
	if flt(doc.advance_amount) > 0:
		frappe.flags.ignore_permissions = True
		try:
			invoice.set_advances()
			invoice.save(ignore_permissions=True)
		finally:
			frappe.flags.ignore_permissions = False

	_stamp_service_cost_center(invoice, profile)
	invoice.submit()

	doc.db_set("sales_invoice", invoice.name, update_modified=False)
	doc.db_set("outstanding_amount", flt(invoice.outstanding_amount), update_modified=False)
	doc.db_set(
		"payment_status", "Paid" if flt(invoice.outstanding_amount) <= 0 else "Partly Paid (Advance)",
		update_modified=False,
	)

	return {"sales_invoice": invoice.name, "created": True,
	        "outstanding": flt(invoice.outstanding_amount)}


def _stamp_service_cost_center(invoice, profile):
	"""The repair's postings belong to the branch's service cost center."""
	from a3_retail.api import stamp_cost_center

	stamp_cost_center(
		invoice, (profile.service_cost_center or profile.cost_center) if profile else None
	)


# ---------------------------------------------------------------------------
# Delivery (scope 3.5)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def deliver_job_card(job_card: str, otp: str, receiver: str | None = None,
                     signature: str | None = None, accessories_returned: int = 1,
                     collect_amount: float = 0, mode_of_payment: str = "Cash") -> dict:
	"""Hand the device back: OTP, signature, accessories and the balance."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	if doc.status != st.READY_FOR_DELIVERY:
		frappe.throw(_("Only a job card that is Ready for Delivery can be delivered."))

	if not doc.delivery_otp or str(otp).strip() != str(doc.delivery_otp):
		frappe.throw(_("The delivery OTP does not match."), title=_("OTP Mismatch"))

	if not cint(accessories_returned):
		frappe.throw(_("Return the customer's accessories before completing delivery."))

	# Any accessory that came in must be handed back.
	unreturned = [
		row.accessory
		for row in doc.get("device_condition_checklist") or []
		if row.received and not row.returned
	]
	if unreturned:
		for row in doc.get("device_condition_checklist") or []:
			if row.received:
				row.returned = 1

	payment_entry = None
	if flt(collect_amount) > 0:
		payment_entry = take_advance(doc.name, flt(collect_amount), mode_of_payment)["payment_entry"]
		doc.reload()

	doc.otp_verified = 1
	doc.receiver_name = receiver
	doc.receiver_signature = signature
	doc.accessories_returned = 1
	doc.delivered_by = _session_employee()
	doc.status = st.DELIVERED
	doc.flags.ignore_permissions = False
	doc.save()

	_stamp_serial_service_history(doc)

	return {
		"job_card": doc.name,
		"status": doc.status,
		"delivered_on": str(doc.delivered_on),
		"payment_entry": payment_entry,
		"outstanding": flt(doc.outstanding_amount),
	}


def _session_employee() -> str | None:
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


def _stamp_serial_service_history(doc):
	"""Increment the device's service counters on delivery (scope 3.5, item 5)."""
	if not doc.serial_no or not frappe.db.exists("Serial No", doc.serial_no):
		return

	count = cint(frappe.db.get_value("Serial No", doc.serial_no, "a3_service_count"))
	frappe.db.set_value(
		"Serial No",
		doc.serial_no,
		{"a3_service_count": count + 1, "a3_last_service_date": getdate(nowdate())},
		update_modified=False,
	)

	if doc.customer:
		frappe.db.set_value(
			"Customer", doc.customer, "a3_last_service_date", getdate(nowdate()), update_modified=False
		)


@frappe.whitelist()
def refund_advance(job_card: str, reason: str | None = None) -> dict:
	"""Refund an advance on a cancelled or not-repairable job (scope 3.5)."""
	require_role("Branch Manager", "Accounts Manager")

	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	amount = flt(doc.advance_amount)
	if amount <= 0:
		frappe.throw(_("There is no advance to refund on {0}.").format(doc.name))

	if doc.status not in (st.CANCELLED, st.NOT_REPAIRABLE, st.ESTIMATE_REJECTED):
		frappe.throw(_("Advances are refunded only on cancelled or not-repairable job cards."))

	profile = get_branch_profile(doc.branch)
	payment = frappe.new_doc("Payment Entry")
	payment.payment_type = "Pay"
	payment.party_type = "Customer"
	payment.party = doc.customer
	payment.company = doc.company
	payment.posting_date = getdate(nowdate())
	payment.paid_amount = amount
	payment.received_amount = amount
	payment.source_exchange_rate = 1
	payment.target_exchange_rate = 1
	payment.paid_from = _mode_account("Cash", doc.company)
	payment.paid_to = _receivable_account(doc.company)
	payment.branch = doc.branch
	if payment.meta.has_field("a3_service_job_card"):
		payment.a3_service_job_card = doc.name
	if profile and payment.meta.has_field("cost_center"):
		payment.cost_center = profile.service_cost_center or profile.cost_center
	payment.remarks = reason or _("Advance refund for {0}").format(doc.name)
	payment.insert()
	payment.submit()

	doc.db_set("advance_amount", 0, update_modified=False)
	doc.db_set("payment_status", "Unpaid", update_modified=False)

	return {"payment_entry": payment.name, "refunded": amount}


@frappe.whitelist()
def resend_delivery_otp(job_card: str) -> dict:
	"""Regenerate and re-send the collection OTP."""
	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	if doc.status != st.READY_FOR_DELIVERY:
		frappe.throw(_("The device is not ready for delivery yet."))

	doc.generate_delivery_otp()
	doc.db_set("delivery_otp", doc.delivery_otp, update_modified=False)
	doc.db_set("otp_verified", 0, update_modified=False)

	from a3_retail.communication.engine import notify

	notify("repair_ready", doc=doc, to_number=doc.customer_mobile,
	       params={"1": doc.customer_name, "4": doc.delivery_otp})

	return {"sent": True}
