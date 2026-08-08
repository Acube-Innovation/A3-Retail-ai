# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Customer management for the branch app (`/branch/customers`).

One person, everything about them: what they bought, what they left for repair,
what they owe, what is still under warranty, and every message the shop sent.
Scoped like the rest of the branch app — `_me()` is the gate and the signed-in
employee's branch decides which customers are listed.

Nothing here writes an invoice or a payment; the counters own that. This page
reads, and it can add a note, block a customer, or send them a message.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

PAGE_SIZE = 8

OPEN_JOB_STATUSES = (
	"Open", "Under Diagnosis", "Estimate Pending", "Estimate Sent", "Estimate Approved",
	"Awaiting Parts", "In Progress", "On Hold", "Repair Completed", "QC Passed",
	"Ready for Delivery",
)
DONE_JOB_STATUSES = ("Delivered", "Closed")


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------
@frappe.whitelist()
def list_customers(query: str = "", page: int = 1, page_size: int = PAGE_SIZE,
                   scope: str = "branch") -> dict:
	"""The left-hand list: this branch's customers, newest first.

	`scope="all"` looks beyond the branch, because a customer who bought in
	Kochi can walk into Kozhikode and the counter still has to find them.
	"""
	employee = _me()
	require_permission("Customer", "read")

	page = max(cint(page), 1)
	size = min(max(cint(page_size) or PAGE_SIZE, 1), 50)

	conditions = ["c.disabled in (0, 1)"]
	values = {"branch": employee.branch, "start": (page - 1) * size, "size": size}

	if scope != "all":
		conditions.append("(c.a3_source_branch = %(branch)s or c.a3_source_branch is null)")
	if query:
		conditions.append(
			"(c.customer_name like %(like)s or c.a3_mobile_no like %(like)s "
			"or c.email_id like %(like)s or c.name like %(like)s)"
		)
		values["like"] = f"%{query}%"

	where = " and ".join(conditions)
	total = frappe.db.sql(
		f"select count(*) from `tabCustomer` c where {where}", values
	)[0][0]

	rows = frappe.db.sql(
		f"""
		select c.name, c.customer_name, c.a3_mobile_no as mobile_no, c.email_id,
		       c.disabled, c.customer_group, c.a3_lifetime_value as lifetime_value
		from `tabCustomer` c
		where {where}
		order by c.modified desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		row["place"] = _place(row["name"])
		row["initials"] = _initials(row["customer_name"])
		row["active"] = not cint(row["disabled"])

	return {
		"rows": rows,
		"total": total,
		"page": page,
		"page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


def _initials(name: str) -> str:
	parts = [part for part in (name or "").split() if part]
	return "".join(part[0] for part in parts[:2]).upper() or "?"


def _place(customer: str) -> str:
	address = frappe.db.sql(
		"""
		select a.city, a.state from `tabAddress` a
		join `tabDynamic Link` l on l.parent = a.name
		where l.link_doctype = 'Customer' and l.link_name = %s
		order by a.is_primary_address desc, a.modified desc limit 1
		""",
		customer,
		as_dict=True,
	)
	if not address:
		return ""
	return ", ".join([part for part in (address[0].city, address[0].state) if part])


# ---------------------------------------------------------------------------
# One customer
# ---------------------------------------------------------------------------
@frappe.whitelist()
def profile(customer: str) -> dict:
	"""The header: who they are, what they carry, and what they are worth."""
	_me()
	require_permission("Customer", "read")

	doc = frappe.get_doc("Customer", customer)
	address = _address(customer)
	spent = _total_spent(customer)
	bookings = frappe.db.count("Service Job Card", {"customer": customer, "docstatus": ["<", 2]})

	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"initials": _initials(doc.customer_name),
		"active": not cint(doc.disabled),
		"mobile_no": doc.a3_mobile_no,
		"whatsapp_no": doc.a3_whatsapp_no,
		"email": doc.email_id,
		"address": address,
		"customer_group": doc.customer_group,
		"customer_since": str(doc.a3_customer_since or getdate(doc.creation)),
		"total_bookings": bookings,
		"total_spent": spent,
		"credit_limit": _credit_limit(doc),
		"available_credit": max(_credit_limit(doc) - _outstanding(customer), 0),
		"outstanding": _outstanding(customer),
		"primary_device": _primary_device(customer),
		"device_count": _device_count(customer),
	}


def _address(customer: str) -> str:
	rows = frappe.db.sql(
		"""
		select a.address_line1, a.city, a.state, a.pincode from `tabAddress` a
		join `tabDynamic Link` l on l.parent = a.name
		where l.link_doctype = 'Customer' and l.link_name = %s
		order by a.is_primary_address desc, a.modified desc limit 1
		""",
		customer,
		as_dict=True,
	)
	if not rows:
		return ""
	row = rows[0]
	return ", ".join([part for part in
	                  (row.address_line1, row.city, row.state, row.pincode) if part])


def _credit_limit(doc) -> float:
	for row in doc.get("credit_limits") or []:
		if flt(row.credit_limit):
			return flt(row.credit_limit)
	return 0.0


def _outstanding(customer: str) -> float:
	return flt(frappe.db.sql(
		"""select sum(outstanding_amount) from `tabSales Invoice`
		   where customer = %s and docstatus = 1""",
		customer,
	)[0][0])


def _total_spent(customer: str) -> float:
	return flt(frappe.db.sql(
		"""select sum(grand_total) from `tabSales Invoice`
		   where customer = %s and docstatus = 1""",
		customer,
	)[0][0])


def _device_count(customer: str) -> int:
	serials = frappe.db.count("Serial No", {"customer": customer})
	if serials:
		return serials
	return len(set(frappe.get_all(
		"Service Job Card", filters={"customer": customer}, pluck="imei_1"
	)) - {None, ""})


def _primary_device(customer: str) -> dict | None:
	"""The handset this customer is most likely holding: the last one we sold."""
	row = frappe.db.sql(
		"""
		select s.name as serial_no, s.item_code, s.a3_imei_1 as imei,
		       s.warranty_expiry_date, i.item_name, i.image, i.a3_device_model as device_model
		from `tabSerial No` s join `tabItem` i on i.name = s.item_code
		where s.customer = %s order by s.creation desc limit 1
		""",
		customer,
		as_dict=True,
	)
	if not row:
		card = frappe.get_all(
			"Service Job Card", filters={"customer": customer},
			fields=["device_model", "imei_1", "warranty_type"],
			order_by="received_on desc", limit=1,
		)
		if not card:
			return None
		return {"item_name": card[0].device_model, "imei": card[0].imei_1,
		        "warranty": card[0].warranty_type or "Out of Warranty", "image": None}

	device = row[0]
	expiry = device.warranty_expiry_date
	in_warranty = bool(expiry and getdate(expiry) >= getdate(nowdate()))
	return {
		"item_name": device.item_name,
		"device_model": device.device_model,
		"imei": device.imei or device.serial_no,
		"image": device.image,
		"warranty": "In Warranty" if in_warranty else "Out of Warranty",
		"warranty_expiry": str(expiry or ""),
	}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@frappe.whitelist()
def overview(customer: str) -> dict:
	"""The six tiles and the panels under them, all from this customer's own rows."""
	_me()
	require_permission("Customer", "read")

	jobs = frappe.get_all(
		"Service Job Card",
		filters={"customer": customer, "docstatus": ["<", 2]},
		fields=["name", "status", "device_model", "received_on", "grand_total"],
		order_by="received_on desc",
	)
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "docstatus": 1},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
		order_by="posting_date desc",
	)
	payments = _payments(customer)
	warranty = _warranty_counts(customer)

	in_progress = len([job for job in jobs if job.status in OPEN_JOB_STATUSES])
	completed = len([job for job in jobs if job.status in DONE_JOB_STATUSES])
	paid = len([inv for inv in invoices if flt(inv.outstanding_amount) <= 0])
	overdue = sum(flt(inv.outstanding_amount) for inv in invoices)

	return {
		"tiles": {
			"bookings": {"total": len(jobs), "sub": in_progress, "sub_label": _("In Progress")},
			"services": {"total": len(jobs), "sub": completed, "sub_label": _("Completed")},
			"invoices": {"total": len(invoices), "sub": paid, "sub_label": _("Paid")},
			"payments": {"total": payments["received"], "sub": payments["advance"],
			             "sub_label": _("Advance"), "money": True},
			"due": {"total": overdue, "sub": payments["advance_balance"],
			        "sub_label": _("Advance Balance"), "money": True},
			"warranty": {"total": warranty["active"], "sub": warranty["expired"],
			             "sub_label": _("Out of Warranty")},
		},
		"recent_bookings": [
			{"name": job.name, "date": str(job.received_on or "")[:10], "status": job.status}
			for job in jobs[:5]
		],
		"recent_services": [
			{"name": inv.name, "date": str(inv.posting_date), "amount": flt(inv.grand_total),
			 "status": "Paid" if flt(inv.outstanding_amount) <= 0
			 else ("Partial" if flt(inv.outstanding_amount) < flt(inv.grand_total) else "Unpaid")}
			for inv in invoices[:5]
		],
		"payments_summary": payments,
		"warranty_summary": warranty,
		"notes": notes(customer, limit=2),
		"documents": len(_files(customer)),
	}


def _payments(customer: str) -> dict:
	rows = frappe.db.sql(
		"""
		select payment_type, sum(paid_amount) amount, sum(unallocated_amount) unallocated
		from `tabPayment Entry`
		where party_type = 'Customer' and party = %s and docstatus = 1
		group by payment_type
		""",
		customer,
		as_dict=True,
	)
	received = sum(flt(row.amount) for row in rows if row.payment_type == "Receive")
	refunds = sum(flt(row.amount) for row in rows if row.payment_type == "Pay")
	unallocated = sum(flt(row.unallocated) for row in rows if row.payment_type == "Receive")

	advance = flt(frappe.db.sql(
		"""select sum(advance_amount) from `tabService Job Card`
		   where customer = %s and docstatus < 2""",
		customer,
	)[0][0])

	return {"received": received, "refunds": refunds, "advance": advance,
	        "advance_balance": unallocated}


def _warranty_counts(customer: str) -> dict:
	if not frappe.db.exists("DocType", "Warranty Registration"):
		return {"active": 0, "expired": 0, "amc": 0}

	rows = frappe.get_all(
		"Warranty Registration",
		filters={"customer": customer, "docstatus": ["<", 2]},
		fields=["name", "status", "ew_expiry_date"],
	)
	today = getdate(nowdate())
	active = len([r for r in rows if r.ew_expiry_date and getdate(r.ew_expiry_date) >= today
	              and r.status not in ("Void", "Cancelled")])
	return {"active": active, "expired": len(rows) - active, "amc": 0}


# ---------------------------------------------------------------------------
# The other tabs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def tab(customer: str, name: str, limit: int = 40) -> list[dict]:
	"""Whatever the open tab needs, as rows the page renders the same way."""
	_me()
	require_permission("Customer", "read")
	limit = min(cint(limit) or 40, 200)

	if name == "bookings":
		return [
			{"title": job.name, "sub": job.device_model or "",
			 "date": str(job.received_on or "")[:10], "amount": flt(job.grand_total),
			 "status": job.status}
			for job in frappe.get_all(
				"Service Job Card", filters={"customer": customer, "docstatus": ["<", 2]},
				fields=["name", "device_model", "received_on", "grand_total", "status"],
				order_by="received_on desc", limit=limit)
		]

	if name == "invoices":
		return [
			{"title": inv.name, "sub": _("Outstanding {0}").format(flt(inv.outstanding_amount))
			 if flt(inv.outstanding_amount) else "",
			 "date": str(inv.posting_date), "amount": flt(inv.grand_total),
			 "status": "Paid" if flt(inv.outstanding_amount) <= 0 else "Due"}
			for inv in frappe.get_all(
				"Sales Invoice", filters={"customer": customer, "docstatus": 1},
				fields=["name", "posting_date", "grand_total", "outstanding_amount"],
				order_by="posting_date desc", limit=limit)
		]

	if name == "payments":
		return [
			{"title": pay.name, "sub": pay.mode_of_payment or "",
			 "date": str(pay.posting_date), "amount": flt(pay.paid_amount),
			 "status": pay.payment_type}
			for pay in frappe.get_all(
				"Payment Entry",
				filters={"party_type": "Customer", "party": customer, "docstatus": 1},
				fields=["name", "posting_date", "paid_amount", "mode_of_payment", "payment_type"],
				order_by="posting_date desc", limit=limit)
		]

	if name == "warranty":
		if not frappe.db.exists("DocType", "Warranty Registration"):
			return []
		return [
			{"title": row.name, "sub": f"{row.item_name or ''} · {row.imei_1 or ''}".strip(" ·"),
			 "date": str(row.ew_expiry_date or ""), "amount": flt(row.plan_amount),
			 "status": row.status}
			for row in frappe.get_all(
				"Warranty Registration", filters={"customer": customer, "docstatus": ["<", 2]},
				fields=["name", "item_name", "imei_1", "ew_expiry_date", "plan_amount", "status"],
				order_by="creation desc", limit=limit)
		]

	if name == "emi":
		# The financing desk owns this; the customer page only shows it.
		from a3_retail.api.emi import customer_history

		return [
			{"title": row["name"],
			 "sub": " · ".join([part for part in (row["finance_partner"], row["emi_scheme"],
			                                     row["products"]) if part]),
			 "date": str(row["application_date"] or ""), "amount": flt(row["loan_amount"]),
			 "status": row["status"], "link": f"/branch/emi?application={row['name']}"}
			for row in customer_history(customer, limit=limit)
		]

	if name == "devices":
		return _devices(customer, limit)

	if name == "communication":
		return [
			{"title": row.template or row.stream or _("Message"),
			 "sub": (row.message_body or "")[:120],
			 "date": str(row.creation)[:16], "status": row.status}
			for row in frappe.get_all(
				"WhatsApp Message Log", filters={"customer": customer},
				fields=["name", "template", "stream", "message_body", "status", "creation"],
				order_by="creation desc", limit=limit)
		]

	if name == "documents":
		return _files(customer)

	if name == "notes":
		return notes(customer, limit=limit)

	return []


def _devices(customer: str, limit: int = 40) -> list[dict]:
	rows = frappe.db.sql(
		"""
		select s.name as serial_no, s.a3_imei_1 as imei, s.warranty_expiry_date,
		       i.item_name, s.creation
		from `tabSerial No` s join `tabItem` i on i.name = s.item_code
		where s.customer = %(customer)s order by s.creation desc limit %(limit)s
		""",
		{"customer": customer, "limit": limit},
		as_dict=True,
	)
	today = getdate(nowdate())
	out = [
		{"title": row.item_name, "sub": _("IMEI {0}").format(row.imei or row.serial_no),
		 "date": str(row.warranty_expiry_date or "")[:10], "amount": 0,
		 "status": "In Warranty" if row.warranty_expiry_date
		 and getdate(row.warranty_expiry_date) >= today else "Out of Warranty"}
		for row in rows
	]

	seen = {row["sub"] for row in out}
	for card in frappe.get_all(
		"Service Job Card", filters={"customer": customer},
		fields=["device_model", "imei_1", "warranty_type", "received_on"],
		order_by="received_on desc", limit=limit,
	):
		label = _("IMEI {0}").format(card.imei_1 or "—")
		if label in seen or not card.device_model:
			continue
		seen.add(label)
		out.append({"title": card.device_model, "sub": label,
		            "date": str(card.received_on or "")[:10], "amount": 0,
		            "status": card.warranty_type or "Out of Warranty"})
	return out


def _files(customer: str) -> list[dict]:
	return [
		{"title": row.file_name, "sub": row.file_url, "date": str(row.creation)[:10],
		 "amount": 0, "status": _("File"), "url": row.file_url}
		for row in frappe.get_all(
			"File", filters={"attached_to_doctype": "Customer", "attached_to_name": customer},
			fields=["file_name", "file_url", "creation"], order_by="creation desc", limit=40)
	]


@frappe.whitelist()
def notes(customer: str, limit: int = 20) -> list[dict]:
	"""What the counter wrote down about this person."""
	_me()
	return [
		{"title": (row.content or "").strip(), "sub": row.comment_email or row.owner,
		 "date": str(row.creation)[:16], "amount": 0, "status": _("Note")}
		for row in frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Customer", "reference_name": customer,
			         "comment_type": "Comment"},
			fields=["content", "comment_email", "owner", "creation"],
			order_by="creation desc", limit=cint(limit) or 20)
	]


# ---------------------------------------------------------------------------
# What the page can do
# ---------------------------------------------------------------------------
@frappe.whitelist()
def add_note(customer: str, text: str) -> dict:
	"""A note on the customer, not a field on a form — it keeps its author."""
	_me()
	require_permission("Customer", "write")
	text = (text or "").strip()
	if not text:
		frappe.throw(_("Write the note first."))

	doc = frappe.get_doc("Customer", customer)
	comment = doc.add_comment("Comment", text)
	return {"note": comment.name, "text": text}


@frappe.whitelist()
def set_blocked(customer: str, blocked: int = 1) -> dict:
	"""Stop taking new work for someone — without losing what they already did.

	`disabled` keeps every past bill, job card and warranty exactly where it is
	and refuses new documents, which is what "block" means at a counter.
	"""
	_me()
	require_permission("Customer", "write")

	doc = frappe.get_doc("Customer", customer)
	doc.disabled = cint(blocked)
	doc.save()
	doc.add_comment(
		"Comment",
		_("Blocked at the counter.") if cint(blocked) else _("Unblocked at the counter."),
	)
	return {"customer": customer, "active": not cint(blocked)}


@frappe.whitelist()
def message(customer: str, channel: str = "WhatsApp", text: str = "") -> dict:
	"""Say something to a customer on the channel they actually read."""
	employee = _me()
	require_permission("Customer", "read")

	doc = frappe.get_doc("Customer", customer)
	text = (text or "").strip()
	if not text:
		frappe.throw(_("Write the message first."))

	if channel == "Email":
		if not doc.email_id:
			frappe.throw(_("This customer has no email address on file."), title=_("No email"))
		frappe.sendmail(
			recipients=[doc.email_id],
			subject=_("A message from {0}").format(
				frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"),
			message=f"<p>{frappe.utils.escape_html(text)}</p>",
			reference_doctype="Customer", reference_name=customer,
		)
		sent = True
	else:
		from a3_retail.communication import dispatch

		number = doc.a3_whatsapp_no or doc.a3_mobile_no
		if not number:
			frappe.throw(_("This customer has no mobile number on file."), title=_("No number"))
		sent = dispatch.queue_message(
			template=None, to_number=number, params={"1": text}, stream="Service",
			reference_doc=doc, customer=customer,
		)

	doc.add_comment("Comment", _("{0} sent by {1}: {2}").format(channel, employee.employee_name, text))
	return {"sent": bool(sent), "channel": channel}


@frappe.whitelist()
def statement(customer: str) -> dict:
	"""Everything owed and everything paid, in one list the counter can print."""
	_me()
	require_permission("Customer", "read")

	invoices = frappe.get_all(
		"Sales Invoice", filters={"customer": customer, "docstatus": 1},
		fields=["name", "posting_date", "grand_total", "outstanding_amount"],
		order_by="posting_date",
	)
	payments = frappe.get_all(
		"Payment Entry",
		filters={"party_type": "Customer", "party": customer, "docstatus": 1},
		fields=["name", "posting_date", "paid_amount", "payment_type", "mode_of_payment"],
		order_by="posting_date",
	)

	lines = [
		{"date": str(inv.posting_date), "particulars": inv.name, "debit": flt(inv.grand_total),
		 "credit": 0.0}
		for inv in invoices
	] + [
		{"date": str(pay.posting_date),
		 "particulars": f"{pay.name} · {pay.mode_of_payment or ''}".strip(" ·"),
		 "debit": 0.0 if pay.payment_type == "Receive" else flt(pay.paid_amount),
		 "credit": flt(pay.paid_amount) if pay.payment_type == "Receive" else 0.0}
		for pay in payments
	]
	lines.sort(key=lambda row: row["date"])

	balance = 0.0
	for line in lines:
		balance += line["debit"] - line["credit"]
		line["balance"] = balance

	profile_data = profile(customer)
	return {
		"customer": customer,
		"customer_name": profile_data["customer_name"],
		"mobile_no": profile_data["mobile_no"],
		"address": profile_data["address"],
		"as_of": nowdate(),
		"lines": lines,
		"closing": balance,
	}
