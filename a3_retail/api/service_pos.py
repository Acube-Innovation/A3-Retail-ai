# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The service counter (`/branch/service`).

Intake, estimate and hand-over for a device left in for repair, scoped the same
way as the sales counter: `_me()` is the gate, the signed-in employee's branch
answers every question, and no endpoint takes a branch from the caller.

The document behind the screen is the Service Job Card, which already carries
the whole lifecycle — warranty detection, TAT, status transitions, parts and
labour, advance, invoice, delivery OTP. Nothing here re-implements any of that;
it collects what a reception counter can see and hands it to the same routines
the desk uses (scope 3.1–3.9).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

# The six tiles on the screen, in the order they are drawn. Each is a shorthand
# for a repair category the job card already understands.
SERVICE_TYPES = [
	("general", "General Repair", "Hardware - Component", "wrench"),
	("screen", "Screen Repair", "Display", "phone"),
	("battery", "Battery Issue", "Battery", "battery"),
	("water", "Water Damage", "Liquid Damage", "drop"),
	("software", "Software Issue", "Software", "chip"),
	("other", "Other Issue", "Accessory", "file"),
]

CATEGORY_BY_KEY = {key: category for key, _label, category, _icon in SERVICE_TYPES}

# What the counter can charge for, and which table the line belongs in.
LINE_TYPES = {"Part": "parts", "Service": "labour", "Accessory": "parts"}

# The message the customer should get, for where the repair actually is.
TEMPLATE_BY_STATUS = {
	"Open": "job_card_created",
	"Under Diagnosis": "job_card_created",
	"Estimate Sent": "estimate_sent",
	"Estimate Approved": "estimate_approved_ack",
	"Awaiting Parts": "awaiting_parts",
	"Ready for Delivery": "repair_ready",
	"Delivered": "device_delivered",
}


def _branch() -> str:
	return _me().branch


@frappe.whitelist()
def bootstrap() -> dict:
	"""Everything the page needs before the counter touches anything."""
	employee = _me()
	return {
		"branch": employee.branch,
		"service_types": [
			{"key": key, "label": label, "category": category, "icon": icon}
			for key, label, category, icon in SERVICE_TYPES
		],
		"issues": issue_types(),
		"technicians": technicians(),
		"brands": _brands(),
		"device_types": (frappe.get_meta("Service Job Card")
		                 .get_field("device_type").options or "").split("\n"),
		"can_add_model": bool(frappe.has_permission("Device Model", "create")),
		# What this shop insists on before it takes someone's device in. The
		# screen asks for these up front rather than at the end of the booking.
		"require_photos": bool(frappe.db.get_single_value("A3 Retail Settings",
		                                                 "require_device_photos")),
		"min_photos": cint(frappe.db.get_single_value("A3 Retail Settings", "min_photos")) or 1,
		"require_signature": bool(frappe.db.get_single_value("A3 Retail Settings",
		                                                     "require_signature")),
		"lead_sources": ["Walk-in", "Phone Call", "WhatsApp", "Website", "Referral"],
		"warranty_types": ["Brand Warranty", "Extended Warranty", "Screen Protection Plan",
		                   "Insurance Claim", "Out of Warranty", "Goodwill/Free"],
	}


def _brands() -> list[str]:
	"""The makes this counter can pick. ERPNext's own test fixtures are not
	makes anybody services, so they stay out of the list."""
	return [
		brand for brand in frappe.get_all("Brand", pluck="name", order_by="name")
		if not brand.startswith("_Test")
	]


@frappe.whitelist()
def issue_types() -> list[dict]:
	"""The problems a counter can pick from, newest data first."""
	_me()
	return frappe.get_all(
		"Service Issue Type",
		filters={"is_active": 1},
		fields=["name", "issue_name", "category", "default_labour_item",
		        "default_part_item", "standard_tat_hours", "requires_data_backup"],
		order_by="category, issue_name",
	)


@frappe.whitelist()
def technicians() -> list[dict]:
	"""Technicians who work at this branch, for the optional assignment."""
	employee = _me()
	rows = frappe.get_all(
		"Technician Profile",
		filters={"branch": employee.branch, "is_active": 1},
		fields=["employee", "employee_name"],
		order_by="employee_name",
	)
	return [{"employee": row.employee, "employee_name": row.employee_name} for row in rows]


# ---------------------------------------------------------------------------
# The device
# ---------------------------------------------------------------------------
@frappe.whitelist()
def device(code: str) -> dict | None:
	"""Everything the counter should know about the handset in front of it.

	Takes an IMEI, a serial number or a job card number. A device this shop
	sold answers with its own sale — model, purchase date, what went in the box
	— so reception does not have to ask the customer to remember.
	"""
	employee = _me()
	code = (code or "").strip()
	if not code:
		return None

	if frappe.db.exists("Service Job Card", code):
		return booking(code)

	serial = frappe.db.get_value(
		"Serial No", {"name": code}, ["name", "item_code", "warehouse", "a3_imei_1", "warranty_expiry_date"],
		as_dict=True,
	) or frappe.db.get_value(
		"Serial No", {"a3_imei_1": code},
		["name", "item_code", "warehouse", "a3_imei_1", "warranty_expiry_date"], as_dict=True,
	)

	if not serial:
		# Not a device this shop sold — the counter still books it in, it just
		# types the model itself.
		return {"known": False, "imei_1": code if code.isdigit() else "",
		        "warranty_type": "Out of Warranty"}

	item = frappe.db.get_value(
		"Item", serial.item_code,
		["item_name", "brand", "a3_device_model", "a3_is_device"], as_dict=True,
	) or frappe._dict()
	model = item.a3_device_model or _guess_model(item)

	sale = _last_sale(serial.name)
	registration = _warranty_registration(serial.name)
	expiry = serial.warranty_expiry_date or (registration or {}).get("ew_expiry_date")
	warranty = _warranty_type(serial.warranty_expiry_date, registration)

	return {
		"known": True,
		"serial_no": serial.name,
		"imei_1": serial.a3_imei_1 or serial.name,
		"item_code": serial.item_code,
		"device_name": item.item_name,
		"brand": item.brand,
		"device_model": model,
		"device_type": _device_type(serial.item_code),
		"purchase_date": str(sale.get("posting_date") or "") if sale else "",
		"purchase_invoice": (sale or {}).get("invoice"),
		"sold_by_us": bool(sale),
		"warranty_type": warranty,
		"warranty_expiry_date": str(expiry or ""),
		"warranty_registration": (registration or {}).get("name"),
		"accessories": _accessories_sold_with(sale),
		"image": frappe.db.get_value("Item", serial.item_code, "image"),
		"history": _service_history(serial.name, employee.branch),
	}


def _guess_model(item) -> str | None:
	"""A catalogue nobody linked still names the model in the item's own name."""
	if not item.get("brand"):
		return None
	name = (item.get("item_name") or "").lower()
	for row in frappe.get_all("Device Model", filters={"brand": item["brand"], "is_active": 1},
	                          fields=["name", "model_name"]):
		if row.model_name and row.model_name.lower() in name:
			return row.name
	return None


@frappe.whitelist()
def device_models(query: str = "", limit: int = 40) -> list[dict]:
	"""Every model the shop services, for a handset we did not sell."""
	_me()
	filters = {"is_active": 1}
	if query:
		filters["name"] = ["like", f"%{query}%"]
	return frappe.get_all(
		"Device Model", filters=filters, fields=["name", "model_name", "brand", "device_type"],
		order_by="brand, model_name", limit=cint(limit) or 40,
	)


@frappe.whitelist()
def create_device_model(brand: str, model_name: str, device_type: str = "Mobile") -> dict:
	"""Name a model the shop has never sold, so it can service one.

	Deliberately thin: a brand, a name and what kind of thing it is. Everything
	else on a Device Model — standard parts, average turnaround — is filled in
	later by whoever owns the service catalogue.
	"""
	_me()
	require_permission("Device Model", "create")

	brand = (brand or "").strip()
	model_name = (model_name or "").strip()
	if not brand or not model_name:
		frappe.throw(_("A model needs a brand and a name."), title=_("Not enough to go on"))

	if not frappe.db.exists("Brand", brand):
		frappe.throw(_("{0} is not a brand this shop carries.").format(brand))

	name = f"{brand} {model_name}"
	if frappe.db.exists("Device Model", name):
		return {"name": name, "created": False}

	doc = frappe.new_doc("Device Model")
	doc.__newname = name
	doc.model_name = model_name
	doc.brand = brand
	doc.device_type = device_type or "Mobile"
	doc.is_active = 1
	doc.insert()

	return {"name": doc.name, "created": True, "brand": brand,
	        "device_type": doc.device_type}


def _device_type(item_code: str) -> str:
	group = (frappe.db.get_value("Item", item_code, "item_group") or "").lower()
	if "tablet" in group:
		return "Tablet"
	if "wearable" in group or "watch" in group:
		return "Smartwatch"
	if "earbud" in group or "audio" in group:
		return "Earbuds"
	return "Mobile"


def _last_sale(serial_no: str) -> dict | None:
	rows = frappe.db.sql(
		"""
		select si.name as invoice, si.posting_date, si.customer, si.customer_name
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		join `tabSerial and Batch Entry` sbe on sbe.parent = sii.serial_and_batch_bundle
		where si.docstatus = 1 and sbe.serial_no = %s
		order by si.posting_date desc limit 1
		""",
		serial_no,
		as_dict=True,
	)
	if rows:
		return rows[0]

	# Older stock moved before bundles, or a bundle that was cleared.
	rows = frappe.db.sql(
		"""
		select si.name as invoice, si.posting_date, si.customer, si.customer_name
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and sii.serial_no like %s
		order by si.posting_date desc limit 1
		""",
		f"%{serial_no}%",
		as_dict=True,
	)
	return rows[0] if rows else None


def _accessories_sold_with(sale: dict | None) -> str:
	"""What went in the box, taken from the same bill."""
	if not sale:
		return ""
	names = frappe.db.sql(
		"""
		select i.item_name from `tabSales Invoice Item` sii
		join `tabItem` i on i.name = sii.item_code
		where sii.parent = %s and ifnull(i.a3_is_device, 0) = 0
		  and ifnull(i.is_stock_item, 1) = 1
		""",
		sale["invoice"],
		pluck=True,
	)
	return ", ".join(names[:4])


def _warranty_registration(serial_no: str) -> dict | None:
	if not frappe.db.exists("DocType", "Warranty Registration"):
		return None
	return frappe.db.get_value(
		"Warranty Registration",
		{"serial_no": serial_no, "docstatus": ["<", 2]},
		["name", "ew_expiry_date", "ew_plan", "brand_warranty_expiry"],
		as_dict=True,
		order_by="creation desc",
	)


def _warranty_type(brand_expiry, registration) -> str:
	today = getdate(nowdate())
	if brand_expiry and getdate(brand_expiry) >= today:
		return "Brand Warranty"
	if registration and registration.get("ew_expiry_date") \
			and getdate(registration["ew_expiry_date"]) >= today:
		return "Extended Warranty"
	return "Out of Warranty"


def _service_history(serial_no: str, branch: str) -> list[dict]:
	return frappe.get_all(
		"Service Job Card",
		filters={"serial_no": serial_no},
		fields=["name", "status", "complaint_description", "received_on"],
		order_by="received_on desc",
		limit=3,
	)


# ---------------------------------------------------------------------------
# The bill of the repair
# ---------------------------------------------------------------------------
@frappe.whitelist()
def search_items(query: str = "", kind: str = "", limit: int = 20) -> list[dict]:
	"""Parts, labour and accessories the counter can add to a repair."""
	employee = _me()
	require_permission("Item", "read")

	groups = {
		"Part": ("Spare Parts",),
		"Service": ("Service Charges",),
		"Accessory": ("Accessories",),
	}
	wanted = groups.get(kind) or tuple(g for pair in groups.values() for g in pair)

	rows = frappe.db.sql(
		"""
		select i.name as item_code, i.item_name, i.item_group, i.gst_hsn_code as hsn,
		       ifnull(i.is_stock_item, 1) as is_stock_item,
		       ifnull(i.standard_rate, 0) as rate,
		       ifnull(bin.qty, 0) as branch_qty
		from `tabItem` i
		left join (
			select b.item_code, sum(b.actual_qty) qty from `tabBin` b
			join `tabWarehouse` w on w.name = b.warehouse
			where w.custom_branch = %(branch)s group by b.item_code
		) bin on bin.item_code = i.name
		where i.disabled = 0 and i.item_group in %(groups)s
		  and (%(query)s = '' or i.name like %(like)s or i.item_name like %(like)s)
		order by i.item_name
		limit %(limit)s
		""",
		{"branch": employee.branch, "groups": wanted, "query": query or "",
		 "like": f"%{query}%", "limit": cint(limit) or 20},
		as_dict=True,
	)

	for row in rows:
		row["rate"] = flt(_selling_rate(row["item_code"])) or flt(row["rate"])
		row["kind"] = ("Service" if row["item_group"] == "Service Charges"
		               else "Accessory" if row["item_group"] == "Accessories" else "Part")
	return rows


def _selling_rate(item_code: str) -> float:
	from a3_retail.api.pos import _price_list, _profile

	price_list = _price_list(_profile(_branch()))
	return flt(frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list, "selling": 1}, "price_list_rate"
	))


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
@frappe.whitelist()
def save_booking(payload) -> dict:
	"""Book the device in. One call, the way a counter works (scope 3.9)."""
	from a3_retail.api import parse_payload
	from a3_retail.api.customer import get_or_create

	employee = _me()
	require_permission("Service Job Card", "create")
	data = parse_payload(payload)

	if not (data.get("complaint_description") or "").strip():
		frappe.throw(_("Write down what the customer says is wrong."),
		             title=_("Complaint needed"))

	customer = data.get("customer")
	if not customer:
		if not data.get("mobile_no"):
			frappe.throw(_("A repair needs a customer to call back."), title=_("Customer needed"))
		customer = get_or_create(
			mobile_no=data.get("mobile_no"),
			customer_name=data.get("customer_name"),
			branch=employee.branch,
		)["name"]

	if not data.get("device_model"):
		frappe.throw(_("Pick the model of the device before booking it in."),
		             title=_("Model needed"))

	doc = frappe.new_doc("Service Job Card")
	doc.branch = employee.branch
	doc.customer = customer
	doc.device_type = data.get("device_type") or "Mobile"
	doc.brand = data.get("brand")
	doc.device_model = data.get("device_model")
	doc.imei_1 = data.get("imei_1")
	doc.imei_override = cint(data.get("imei_unreadable"))
	doc.serial_no = data.get("serial_no")
	doc.device_purchase_date = data.get("purchase_date") or None
	doc.warranty_type = data.get("warranty_type") or "Out of Warranty"
	doc.warranty_expiry_date = data.get("warranty_expiry_date") or None
	doc.warranty_registration = data.get("warranty_registration")
	doc.complaint_description = data.get("complaint_description")
	doc.repair_category = CATEGORY_BY_KEY.get(data.get("service_type"), data.get("repair_category"))
	doc.priority = data.get("priority") or "Normal"
	doc.lead_source = data.get("lead_source") or "Walk-in"
	doc.received_on = frappe.utils.now_datetime()
	doc.received_by = employee.name
	doc.assigned_technician = data.get("technician") or None
	doc.estimated_delivery_date = _promised(data.get("expected_delivery"))
	doc.data_backup_required = cint(data.get("data_backup_required"))
	doc.data_loss_consent = cint(data.get("data_loss_consent"))
	# The counter's note about the device doubles as its description when there is
	# no IMEI to identify it by.
	doc.physical_condition = data.get("device_condition") or data.get("notes")
	doc.customer_signature = data.get("signature")

	for index, photo in enumerate((data.get("photos") or [])[:4], start=1):
		doc.set(f"device_photo_{index}", photo)
	doc.is_chargeable = 1

	for issue in data.get("issues") or []:
		doc.append("reported_issues", {"issue_type": issue})

	for accessory in data.get("accessories") or []:
		doc.append("device_condition_checklist",
		           {"accessory": accessory, "received": 1, "condition": "Good"})

	_add_lines(doc, data.get("items") or [])
	doc.discount_amount = flt(data.get("discount_amount"))

	doc.insert()
	doc.submit()

	result = {
		"job_card": doc.name,
		"status": doc.status,
		"customer": customer,
		"customer_name": doc.customer_name,
		"grand_total": flt(doc.grand_total),
		"customer_payable": flt(doc.customer_payable),
		"warranty_borne": flt(doc.warranty_borne_amount),
		"warranty_type": doc.warranty_type,
		"promised": str(doc.estimated_delivery_date or ""),
		"print_url": estimate_url(doc.name),
	}

	advance = flt(data.get("advance_amount"))
	if advance > 0:
		from a3_retail.api.service import take_advance

		taken = take_advance(doc.name, advance, data.get("advance_mode") or "Cash")
		result["payment_entry"] = taken.get("payment_entry")
		result["advance"] = flt(taken.get("advance_amount"))
		result["balance"] = max(flt(doc.customer_payable) - result["advance"], 0)
	else:
		result["advance"] = 0.0
		result["balance"] = flt(doc.customer_payable)

	return result


def _add_lines(doc, items: list[dict]):
	"""Split what the counter typed into the parts table and the labour table."""
	for line in items:
		item_code = line.get("item_code")
		if not item_code:
			continue
		qty = flt(line.get("qty")) or 1
		rate = flt(line.get("rate"))
		table = LINE_TYPES.get(line.get("kind") or "Part", "parts")

		if table == "labour":
			doc.append("labour", {
				"service_item": item_code,
				"description": line.get("item_name"),
				"technician": line.get("technician") or doc.assigned_technician,
				"qty": qty,
				"rate": rate,
			})
		else:
			doc.append("parts", {
				"item_code": item_code,
				"item_name": line.get("item_name"),
				"qty": qty,
				"rate": rate,
			})


def _promised(value) -> str | None:
	"""A promised date from the counter is a promise for the end of that day."""
	if not value:
		return None
	value = str(value)
	return value if " " in value else f"{value} 18:00:00"


# ---------------------------------------------------------------------------
# The rest of the counter's day
# ---------------------------------------------------------------------------
@frappe.whitelist()
def booking(job_card: str) -> dict:
	"""Reload a card into the screen — for the Invoice and Delivery steps."""
	employee = _me()
	require_permission("Service Job Card", "read")

	doc = frappe.get_doc("Service Job Card", job_card)
	if doc.branch != employee.branch:
		frappe.throw(_("That job card belongs to another branch."), title=_("Not this branch"))

	return {
		"known": True,
		"job_card": doc.name,
		"status": doc.status,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"mobile_no": doc.customer_mobile,
		"device_name": frappe.db.get_value("Device Model", doc.device_model, "model_name")
		or doc.device_model,
		"device_model": doc.device_model,
		"brand": doc.brand,
		"device_type": doc.device_type,
		"imei_1": doc.imei_1,
		"serial_no": doc.serial_no,
		"purchase_date": str(doc.device_purchase_date or ""),
		"warranty_type": doc.warranty_type,
		"complaint_description": doc.complaint_description,
		"priority": doc.priority,
		"technician": doc.assigned_technician,
		"promised": str(doc.estimated_delivery_date or ""),
		"grand_total": flt(doc.grand_total),
		"advance": flt(doc.advance_amount),
		"balance": flt(doc.outstanding_amount or doc.customer_payable),
		"sales_invoice": doc.sales_invoice,
		"items": _lines_of(doc),
		"print_url": estimate_url(doc.name),
	}


def _lines_of(doc) -> list[dict]:
	lines = []
	for row in doc.get("parts") or []:
		lines.append({"item_code": row.item_code, "item_name": row.item_name,
		              "kind": "Part", "qty": flt(row.qty), "rate": flt(row.rate),
		              "hsn": frappe.db.get_value("Item", row.item_code, "gst_hsn_code")})
	for row in doc.get("labour") or []:
		lines.append({"item_code": row.service_item, "item_name": row.description,
		              "kind": "Service", "qty": flt(row.qty) or 1, "rate": flt(row.rate),
		              "hsn": frappe.db.get_value("Item", row.service_item, "gst_hsn_code")})
	return lines


@frappe.whitelist()
def recent_bookings(limit: int = 10) -> list[dict]:
	"""What this counter booked in today, for the Recent list."""
	employee = _me()
	require_permission("Service Job Card", "read")
	return frappe.get_all(
		"Service Job Card",
		filters={"branch": employee.branch, "docstatus": ["<", 2]},
		fields=["name", "customer_name", "device_model", "status", "grand_total", "received_on"],
		order_by="received_on desc",
		limit=cint(limit) or 10,
	)


@frappe.whitelist()
def generate_invoice(job_card: str) -> dict:
	"""Bill the repair. The service module owns the accounting."""
	from a3_retail.api.service import create_sales_invoice

	_me()
	booking(job_card)  # branch guard
	result = create_sales_invoice(job_card)
	result["print_url"] = _invoice_url(result["sales_invoice"])
	return result


@frappe.whitelist()
def mark_delivered(job_card: str, otp: str, receiver: str | None = None) -> dict:
	"""Hand the device back. The OTP is the customer's signature."""
	from a3_retail.api.service import deliver_job_card

	_me()
	booking(job_card)
	return deliver_job_card(job_card, otp=otp, receiver=receiver)


@frappe.whitelist()
def resend_otp(job_card: str) -> dict:
	from a3_retail.api.service import resend_delivery_otp

	_me()
	booking(job_card)
	return resend_delivery_otp(job_card)


@frappe.whitelist()
def notify(job_card: str, channel: str = "WhatsApp") -> dict:
	"""Tell the customer where their repair stands, on the channel they use."""
	_me()
	card = booking(job_card)

	from a3_retail.communication import engine

	doc = frappe.get_doc("Service Job Card", job_card)
	template = TEMPLATE_BY_STATUS.get(doc.status, "job_card_created")

	if channel == "Email":
		sent = _email_update(doc, card)
	else:
		# SMS rides the same log and the same compliance checks as WhatsApp —
		# the provider decides which wire it goes out on.
		sent = engine.notify(template, doc=doc, to_number=card.get("mobile_no"),
		                     stream="Service")

	return {"sent": bool(sent), "channel": channel, "template": template}


def _email_update(doc, card: dict) -> bool:
	"""The same update, for a customer who reads email."""
	recipient = doc.customer_email or frappe.db.get_value("Customer", doc.customer, "email_id")
	if not recipient:
		frappe.throw(_("This customer has no email address on file."), title=_("No email"))

	company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	frappe.sendmail(
		recipients=[recipient],
		subject=_("{0} — job card {1} is {2}").format(company, doc.name, doc.status),
		message=frappe.render_template(
			"<p>{{ _('Dear') }} {{ name }},</p>"
			"<p>{{ _('Your') }} {{ device }} ({{ imei }}) {{ _('is currently') }} "
			"<b>{{ status }}</b>.</p>"
			"<p>{{ _('Job card') }}: {{ card }}<br>{{ _('Promised') }}: {{ promised }}</p>"
			"<p>{{ company }}</p>",
			{"name": doc.customer_name, "device": card.get("device_name") or doc.device_model,
			 "imei": doc.imei_1 or "", "status": doc.status, "card": doc.name,
			 "promised": card.get("promised") or "", "company": company},
		),
		reference_doctype="Service Job Card",
		reference_name=doc.name,
	)
	return True


@frappe.whitelist()
def estimate_url(job_card: str) -> str:
	"""The acknowledgement the customer walks out with."""
	_me()
	return (
		"/api/method/frappe.utils.print_format.download_pdf"
		f"?doctype=Service%20Job%20Card&name={frappe.utils.quoted(job_card)}"
		"&format=Job%20Card%20Acknowledgement&no_letterhead=0"
	)


def _invoice_url(invoice: str) -> str:
	return (
		"/api/method/frappe.utils.print_format.download_pdf"
		f"?doctype=Sales%20Invoice&name={frappe.utils.quoted(invoice)}"
		"&format=Service%20Tax%20Invoice&no_letterhead=0"
	)
