# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Bills — invoice management for the branch app (`/branch/bills`).

Reads the invoices the counters wrote. It creates nothing of its own: the sales
counter owns the Sales Invoice, the service counter owns the repair, and the
print template is the one `api.pos.print_url` already points at, so a bill looks
the same whether it is printed from the till, from this list or from the invoice
page.

The one thing it writes is a payment against a bill that is still short, which
is what a counter does when a customer comes back to settle.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission, stamp_cost_center
from a3_retail.api.pos import print_url, resolve_mode
from a3_retail.api.staff import _me

PAGE_SIZES = (20, 50, 100)

# What the counter calls the state of the money, from what ERPNext records.
PAID = "Paid"
PARTLY = "Partially Paid"
UNPAID = "Unpaid"
REFUNDED = "Refunded"


def _branch() -> str:
	return _me().branch


def _payment_status(row) -> str:
	if row.get("is_return"):
		return REFUNDED
	outstanding = flt(row.get("outstanding_amount"))
	total = flt(row.get("rounded_total")) or flt(row.get("grand_total"))
	if outstanding <= 0.005:
		return PAID
	if outstanding < total - 0.005:
		return PARTLY
	return UNPAID


def _doc_status(docstatus: int) -> str:
	return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(cint(docstatus), "Draft")


def _filters(data: dict) -> tuple[str, dict]:
	"""Turn the filter bar into one where-clause everything on the page shares."""
	employee = _me()
	conditions = ["si.company = %(company)s"]
	values = {
		"company": frappe.db.get_single_value("Global Defaults", "default_company"),
		"branch": employee.branch,
	}

	if (data.get("branch") or "current") != "all":
		conditions.append("si.branch = %(branch)s")

	if data.get("query"):
		conditions.append(
			"(si.name like %(like)s or si.customer_name like %(like)s "
			"or si.contact_mobile like %(like)s or si.customer like %(like)s)"
		)
		values["like"] = f"%{data['query']}%"

	if data.get("from_date"):
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = getdate(data["from_date"])
	if data.get("to_date"):
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = getdate(data["to_date"])
	if data.get("customer"):
		conditions.append("si.customer = %(customer)s")
		values["customer"] = data["customer"]

	status = data.get("status") or "all"
	if status == "Draft":
		conditions.append("si.docstatus = 0")
	elif status == "Cancelled":
		conditions.append("si.docstatus = 2")
	elif status == PAID:
		conditions.append(
			"si.docstatus = 1 and si.is_return = 0 and si.outstanding_amount <= 0.005")
	elif status == UNPAID:
		conditions.append(
			"si.docstatus = 1 and si.is_return = 0 and si.outstanding_amount >= "
			"ifnull(nullif(si.rounded_total, 0), si.grand_total) - 0.005"
		)
	elif status == PARTLY:
		conditions.append(
			"si.docstatus = 1 and si.is_return = 0 and si.outstanding_amount > 0.005 "
			"and si.outstanding_amount < "
			"ifnull(nullif(si.rounded_total, 0), si.grand_total) - 0.005"
		)

	if (data.get("mode") or "all") != "all":
		conditions.append(
			"exists (select 1 from `tabSales Invoice Payment` p "
			"where p.parent = si.name and p.mode_of_payment like %(mode)s)"
		)
		values["mode"] = f"%{data['mode']}%"

	return " and ".join(conditions), values


@frappe.whitelist()
def summary(filters=None) -> dict:
	"""The six cards over the list — the same filters, so they always agree."""
	_me()
	require_permission("Sales Invoice", "read")
	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _filters(data)

	rows = frappe.db.sql(
		f"""
		select si.docstatus, si.is_return, si.grand_total, si.rounded_total,
		       si.outstanding_amount, si.posting_date
		from `tabSales Invoice` si where {where}
		""",
		values,
		as_dict=True,
	)

	def total(subset) -> float:
		return sum(flt(row.rounded_total) or flt(row.grand_total) for row in subset)

	live = [row for row in rows if cint(row.docstatus) == 1]
	today = getdate(nowdate())

	return {
		"total": {"count": len(rows), "amount": total(rows)},
		"paid": {"count": len([r for r in live if _payment_status(r) == PAID]),
		         "amount": total([r for r in live if _payment_status(r) == PAID])},
		"partly": {"count": len([r for r in live if _payment_status(r) == PARTLY]),
		           "amount": sum(flt(r.outstanding_amount)
		                         for r in live if _payment_status(r) == PARTLY)},
		"unpaid": {"count": len([r for r in live if _payment_status(r) == UNPAID]),
		           "amount": sum(flt(r.outstanding_amount)
		                         for r in live if _payment_status(r) == UNPAID)},
		"cancelled": {"count": len([r for r in rows if cint(r.docstatus) == 2]),
		              "amount": total([r for r in rows if cint(r.docstatus) == 2])},
		"today": {"count": len([r for r in live if getdate(r.posting_date) == today]),
		          "amount": total([r for r in live if getdate(r.posting_date) == today])},
	}


@frappe.whitelist()
def list_bills(filters=None, page: int = 1, page_size: int = 20) -> dict:
	"""The table: one row per invoice, with every column the page shows."""
	_me()
	require_permission("Sales Invoice", "read")

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	where, values = _filters(data)

	page = max(cint(page), 1)
	size = cint(page_size) if cint(page_size) in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	total = frappe.db.sql(f"select count(*) from `tabSales Invoice` si where {where}", values)[0][0]

	rows = frappe.db.sql(
		f"""
		select si.name, si.posting_date, si.customer, si.customer_name, si.contact_mobile,
		       si.docstatus, si.is_return, si.branch, si.net_total, si.discount_amount,
		       si.total_taxes_and_charges, si.grand_total, si.rounded_total,
		       si.outstanding_amount, si.remarks,
		       (select count(*) from `tabSales Invoice Item` it where it.parent = si.name) as items,
		       (select group_concat(distinct p.mode_of_payment separator ', ')
		          from `tabSales Invoice Payment` p where p.parent = si.name) as modes,
		       (select group_concat(distinct t.sales_person separator ', ')
		          from `tabSales Team` t where t.parent = si.name) as sales_person
		from `tabSales Invoice` si
		where {where}
		order by si.posting_date desc, si.creation desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		payable = flt(row.rounded_total) or flt(row.grand_total)
		row["payable"] = payable
		row["paid"] = max(payable - flt(row.outstanding_amount), 0)
		row["balance"] = flt(row.outstanding_amount)
		row["payment_status"] = _payment_status(row)
		row["status"] = _doc_status(row.docstatus)
		row["editable"] = cint(row.docstatus) == 0
		row["mobile_no"] = row.contact_mobile or frappe.db.get_value(
			"Customer", row.customer, "a3_mobile_no"
		)

	return {
		"rows": rows,
		"total": total,
		"page": page,
		"page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


@frappe.whitelist()
def customers(query: str = "", limit: int = 20) -> list[dict]:
	"""The customer filter's own lookup."""
	_me()
	require_permission("Customer", "read")
	from a3_retail.api.pos import search_customers

	return search_customers(query=query, limit=limit)


# ---------------------------------------------------------------------------
# One invoice
# ---------------------------------------------------------------------------
@frappe.whitelist()
def invoice(name: str) -> dict:
	"""Everything the invoice page shows, read from the invoice itself."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	doc = frappe.get_doc("Sales Invoice", name)
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))

	payable = flt(doc.rounded_total) or flt(doc.grand_total)
	paid = max(payable - flt(doc.outstanding_amount), 0)
	status = _doc_status(doc.docstatus)

	return {
		"name": doc.name,
		"status": status,
		"payment_status": _payment_status({
			"is_return": doc.is_return, "outstanding_amount": doc.outstanding_amount,
			"grand_total": doc.grand_total, "rounded_total": doc.rounded_total,
		}),
		"editable": status == "Draft",
		"posting_date": str(doc.posting_date),
		"posting_time": str(doc.posting_time or "")[:5],
		"branch": doc.branch,
		"company": doc.company,
		"warehouse": doc.set_warehouse,
		"sales_person": ", ".join([row.sales_person for row in doc.get("sales_team") or []]),
		"customer": _customer_block(doc),
		"device": _device_block(doc),
		"items": _items(doc),
		"totals": {
			"subtotal": flt(doc.total),
			"discount": flt(doc.discount_amount),
			"taxable": flt(doc.net_total),
			"taxes": [{"label": row.description or row.account_head, "rate": flt(row.rate),
			           "amount": flt(row.tax_amount)} for row in doc.get("taxes") or []],
			"tax_total": flt(doc.total_taxes_and_charges),
			"grand_total": flt(doc.grand_total),
			"rounded_total": flt(doc.rounded_total),
			"payable": payable,
			"paid": paid,
			"balance": flt(doc.outstanding_amount),
		},
		"payments": _payments(doc),
		"service": _service_block(doc),
		"warranty": _warranty_block(doc),
		"timeline": _timeline(doc),
		# ERPNext writes "No Remarks" when there are none, which is not a note.
		"notes": None if (doc.remarks or "").strip() in ("", "No Remarks") else doc.remarks,
		"terms": doc.terms,
		"payment_terms": doc.payment_terms_template,
		"print_url": print_url(doc.name),
		"receipt_url": print_url(doc.name, "POS Receipt")
		if frappe.db.exists("Print Format", {"name": "POS Receipt", "doc_type": "Sales Invoice"})
		else None,
	}


def _customer_block(doc) -> dict:
	address = ""
	if doc.customer_address:
		address = (frappe.db.get_value("Address", doc.customer_address, "address_line1") or "")
		city, state, pin = frappe.db.get_value(
			"Address", doc.customer_address, ["city", "state", "pincode"]
		) or ("", "", "")
		address = ", ".join([part for part in (address, city, state, pin) if part])
	else:
		from a3_retail.api.customer_desk import _address

		address = _address(doc.customer)

	return {
		"name": doc.customer,
		"customer_name": doc.customer_name,
		"mobile_no": doc.contact_mobile or frappe.db.get_value(
			"Customer", doc.customer, "a3_mobile_no"),
		"email": doc.contact_email or frappe.db.get_value("Customer", doc.customer, "email_id"),
		"address": address,
		"gstin": frappe.db.get_value("Customer", doc.customer, "gstin")
		if frappe.db.has_column("Customer", "gstin") else None,
	}


def _device_block(doc) -> dict | None:
	"""A handset on the bill, if one of the lines carries a serial."""
	for row in doc.get("items") or []:
		serials = _serials_of(row)
		if not serials:
			continue
		if not frappe.db.get_value("Item", row.item_code, "a3_is_device"):
			continue

		serial = serials[0]
		expiry = frappe.db.get_value("Serial No", serial, "warranty_expiry_date")
		return {
			"item_name": row.item_name,
			"item_code": row.item_code,
			"model": frappe.db.get_value("Item", row.item_code, "a3_device_model"),
			"imei": frappe.db.get_value("Serial No", serial, "a3_imei_1") or serial,
			"serial_no": serial,
			"warranty_expiry": str(expiry or ""),
			"warranty": ("In Warranty" if expiry and getdate(expiry) >= getdate(nowdate())
			             else "Out of Warranty"),
		}
	return None


def _serials_of(row) -> list[str]:
	"""Serial numbers on a line, however this invoice happens to carry them."""
	if row.get("serial_no"):
		return [s.strip() for s in str(row.serial_no).replace(",", "\n").split("\n") if s.strip()]
	if row.get("serial_and_batch_bundle"):
		return frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": row.serial_and_batch_bundle},
			pluck="serial_no",
		)
	return []


def _items(doc) -> list[dict]:
	lines = []
	for index, row in enumerate(doc.get("items") or [], start=1):
		lines.append({
			"idx": index,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"hsn": row.get("gst_hsn_code") or frappe.db.get_value(
				"Item", row.item_code, "gst_hsn_code"),
			"serials": _serials_of(row),
			"qty": flt(row.qty),
			"rate": flt(row.rate),
			"discount": flt(row.discount_amount) * flt(row.qty),
			"tax_rate": _line_tax_rate(doc, row),
			"amount": flt(row.amount),
		})
	return lines


def _line_tax_rate(doc, row) -> float:
	"""What this line was actually taxed at, from its own tax template."""
	if row.get("item_tax_template"):
		rates = frappe.get_all(
			"Item Tax Template Detail", filters={"parent": row.item_tax_template},
			pluck="tax_rate",
		)
		if rates:
			return sum(flt(rate) for rate in rates)
	return sum(flt(tax.rate) for tax in doc.get("taxes") or [])


def _payments(doc) -> list[dict]:
	"""What the customer has actually handed over, from both places it can live."""
	out = [
		{"name": doc.name, "date": str(doc.posting_date), "mode": row.mode_of_payment,
		 "reference": _("At the counter"), "amount": flt(row.amount)}
		for row in doc.get("payments") or [] if flt(row.amount)
	]

	for row in frappe.db.sql(
		"""
		select pe.name, pe.posting_date, pe.mode_of_payment, pe.reference_no,
		       per.allocated_amount
		from `tabPayment Entry Reference` per
		join `tabPayment Entry` pe on pe.name = per.parent
		where per.reference_doctype = 'Sales Invoice' and per.reference_name = %s
		  and pe.docstatus = 1
		order by pe.posting_date
		""",
		doc.name,
		as_dict=True,
	):
		out.append({
			"name": row.name, "date": str(row.posting_date), "mode": row.mode_of_payment,
			"reference": row.reference_no or "", "amount": flt(row.allocated_amount),
		})
	return out


def _service_block(doc) -> dict | None:
	"""The repair this bill came out of, when it came out of one."""
	card = None
	if doc.meta.has_field("a3_service_job_card") and doc.get("a3_service_job_card"):
		card = doc.a3_service_job_card
	else:
		card = frappe.db.get_value("Service Job Card", {"sales_invoice": doc.name}, "name")
	if not card:
		return None

	job = frappe.get_doc("Service Job Card", card)
	return {
		"job_card": job.name,
		"repair_category": job.repair_category,
		"complaint": job.complaint_description,
		"device_model": job.device_model,
		"imei": job.imei_1,
		"technician": frappe.db.get_value("Employee", job.assigned_technician, "employee_name")
		if job.assigned_technician else None,
		"status": job.status,
		"promised": str(job.estimated_delivery_date or ""),
		"delivered": str(job.delivered_on or ""),
	}


def _warranty_block(doc) -> dict | None:
	if not frappe.db.exists("DocType", "Warranty Registration"):
		return None

	row = frappe.db.get_value(
		"Warranty Registration", {"sales_invoice": doc.name, "docstatus": ["<", 2]},
		["name", "status", "ew_plan", "ew_start_date", "ew_expiry_date",
		 "brand_warranty_expiry", "registration_type"],
		as_dict=True,
	)
	if not row:
		return None

	expiry = row.ew_expiry_date or row.brand_warranty_expiry
	return {
		"registration": row.name,
		"status": "Active" if expiry and getdate(expiry) >= getdate(nowdate()) else "Expired",
		"plan": row.ew_plan,
		"type": row.registration_type,
		"start": str(row.ew_start_date or ""),
		"end": str(expiry or ""),
	}


def _timeline(doc) -> list[dict]:
	"""What happened to this bill, in the order it happened."""
	events = [{"label": _("Created"), "at": str(doc.creation)[:16]}]

	if cint(doc.docstatus) >= 1:
		submitted = frappe.db.get_value(
			"Version", {"ref_doctype": "Sales Invoice", "docname": doc.name}, "creation",
			order_by="creation",
		)
		events.append({"label": _("Submitted"), "at": str(submitted or doc.modified)[:16]})

	for payment in _payments(doc):
		events.append({
			"label": _("Payment received"),
			"at": payment["date"],
			"note": f"{payment['mode'] or ''} {frappe.utils.fmt_money(payment['amount'], currency='INR')}".strip(),
		})

	if cint(doc.docstatus) == 2:
		events.append({"label": _("Cancelled"), "at": str(doc.modified)[:16]})

	return events


# ---------------------------------------------------------------------------
# The one thing this page writes
# ---------------------------------------------------------------------------
@frappe.whitelist()
def collect_payment(name: str, amount: float, mode_of_payment: str = "Cash",
                    reference: str | None = None) -> dict:
	"""Take money against a bill that is still short.

	A Payment Entry allocated to the invoice, the same document the desk would
	raise — not a second payment system living on this page.
	"""
	employee = _me()
	require_permission("Payment Entry", "create")

	doc = frappe.get_doc("Sales Invoice", name)
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))
	if cint(doc.docstatus) != 1:
		frappe.throw(_("Only a submitted bill can take a payment."))

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("How much did the customer hand over?"))
	if amount > flt(doc.outstanding_amount) + 0.005:
		frappe.throw(
			_("That is more than the {0} still owed on this bill.").format(
				frappe.utils.fmt_money(doc.outstanding_amount, currency="INR"))
		)

	# Built by hand rather than through `get_payment_entry`, which reads an
	# account balance off the ledger — a counter has no read on GL Entry and
	# should not need one to take ₹500 over the desk. Same document, same
	# accounts, same route the service counter's advance already takes.
	from a3_retail.api.service import _mode_account, _receivable_account

	mode = resolve_mode(mode_of_payment)
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": doc.branch},
		["sales_cost_center", "cost_center"], as_dict=True,
	) or frappe._dict()

	payment = frappe.new_doc("Payment Entry")
	payment.payment_type = "Receive"
	payment.party_type = "Customer"
	payment.party = doc.customer
	payment.company = doc.company
	payment.posting_date = nowdate()
	payment.mode_of_payment = mode
	payment.paid_amount = amount
	payment.received_amount = amount
	payment.source_exchange_rate = 1
	payment.target_exchange_rate = 1
	payment.paid_to = _mode_account(mode, doc.company)
	payment.paid_from = _receivable_account(doc.company)
	payment.reference_no = reference or doc.name
	payment.reference_date = nowdate()
	payment.remarks = _("Payment against {0}").format(doc.name)
	if payment.meta.has_field("branch"):
		payment.branch = doc.branch

	payment.append("references", {
		"reference_doctype": "Sales Invoice",
		"reference_name": doc.name,
		"total_amount": flt(doc.rounded_total) or flt(doc.grand_total),
		"outstanding_amount": flt(doc.outstanding_amount),
		"allocated_amount": amount,
	})
	stamp_cost_center(payment, profile.get("sales_cost_center") or profile.get("cost_center"))

	payment.flags.ignore_permissions = True
	payment.insert(ignore_permissions=True)
	payment.submit()

	doc.reload()
	return {
		"payment_entry": payment.name,
		"paid": amount,
		"balance": flt(doc.outstanding_amount),
		"payment_status": _payment_status({
			"is_return": doc.is_return, "outstanding_amount": doc.outstanding_amount,
			"grand_total": doc.grand_total, "rounded_total": doc.rounded_total,
		}),
	}


@frappe.whitelist()
def send(name: str, channel: str = "WhatsApp") -> dict:
	"""Send the customer their bill on the channel they read."""
	_me()
	invoice_data = invoice(name)
	customer = invoice_data["customer"]

	if channel == "Email":
		if not customer.get("email"):
			frappe.throw(_("This customer has no email address on file."), title=_("No email"))
		frappe.sendmail(
			recipients=[customer["email"]],
			subject=_("{0} — invoice {1}").format(
				frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail",
				name),
			message=_("<p>Dear {0},</p><p>Your invoice {1} for {2} is attached.</p>").format(
				customer["customer_name"], name,
				frappe.utils.fmt_money(invoice_data["totals"]["payable"], currency="INR")),
			attachments=[frappe.attach_print("Sales Invoice", name,
			                                 print_format="Retail Tax Invoice")],
			reference_doctype="Sales Invoice", reference_name=name,
		)
		return {"sent": True, "channel": channel}

	from a3_retail.communication import engine

	if not customer.get("mobile_no"):
		frappe.throw(_("This customer has no mobile number on file."), title=_("No number"))
	sent = engine.notify("sale_invoice", doc=frappe.get_doc("Sales Invoice", name),
	                     to_number=customer["mobile_no"], stream="Sales")
	return {"sent": bool(sent), "channel": channel}
