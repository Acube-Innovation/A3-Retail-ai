# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Jinja helpers available inside every print format (scope 13.3).

Registered through `hooks.jinja.methods`, so a template can call
`a3_tracking_qr(doc)` or `a3_hsn_summary(doc)` directly. Anything that needs a
loop, a lookup or arithmetic lives here rather than in the template — a print
format is hard to debug, and the sandbox makes non-trivial Jinja awkward.
"""

import frappe
from frappe.utils import cint, flt, fmt_money, getdate, money_in_words

from a3_retail.utils import qr as qr_utils


# ------------------------------------------------------------------ QR / codes
def a3_qr(text: str, scale: int = 3) -> str:
	return qr_utils.qr_data_uri(text, scale=scale)


def a3_tracking_qr(doc, scale: int = 3) -> str:
	return qr_utils.tracking_qr(doc, scale=scale)


def a3_barcode(text: str, height: float = 12.0, width_mm: float | None = None) -> str:
	"""A Code 128 barcode, for a label a scanner will read rather than a person.

	`width_mm` is the room the label has for it; give it and the bars are drawn
	to fill exactly that, so the sticker never has to stretch them.
	"""
	return qr_utils.barcode_data_uri(text, height=height, width_mm=width_mm)


def a3_barcode_svg(text: str, height: float = 6.0, width_mm: float | None = None) -> str:
	"""The same Code 128, drawn as vector and sized to the room it has.

	`width_mm` is what the label can give the symbol; the bars are drawn to
	fill exactly that. See `qr.barcode_svg_uri`.
	"""
	return qr_utils.barcode_svg_uri(text, height=height, width_mm=width_mm)


def a3_barcode_module_mm(text: str, width_mm: float, quiet_zone: float = 2.0) -> float:
	"""How wide one bar comes out, for a label that wants to check its own work."""
	modules = qr_utils.barcode_modules(text)
	return round((width_mm - 2 * quiet_zone) / modules, 4) if modules else 0.0


def a3_label_barcode(text: str, height_mm: float = 8.0,
                     module_dots: int = 2) -> str:
	"""The barcode for a sticker, drawn as vector bars at whole-dot widths.

	Use this on anything going to the label roll rather than `a3_barcode`,
	which draws a bitmap in millimetres and leaves the renderer to scale it —
	see `qr.barcode_bars_uri` for what that does to the bars. Place the result
	at `a3_label_barcode_mm` millimetres wide, which is the width at which one
	module is a whole number of print-head dots.
	"""
	return qr_utils.barcode_bars_uri(text, height_mm=height_mm,
	                                 module_dots=module_dots)


def a3_label_barcode_mm(text: str, max_mm: float, module_dots: int = 2) -> float:
	"""The width to place `a3_label_barcode` at, or 0 when it will not fit."""
	return qr_utils.barcode_dot_width(text, max_mm, module_dots=module_dots)


def a3_scan_code(name: str) -> str:
	"""The part of a document number worth putting in a barcode.

	A job card is `JC-SVP-26-00053`. All fifteen characters come to two hundred
	Code 128 modules, and on a sticker small enough to live on the back of a
	phone each bar works out thinner than a printer can lay down cleanly.

	The branch and the `JC` are the same on every label a branch prints, so
	they cost bars and carry nothing: dropping them leaves `26-00053`, which is
	123 modules — a third narrower — and is still unique. It also still finds
	the job card, because every screen searches document numbers by what they
	contain, and `JC-SVP-26-00053` contains `26-00053`.

	The whole number is printed underneath in words a person can read, so
	nothing is lost to the counter.
	"""
	parts = (name or "").split("-")
	# JC · branch · year · serial. Anything shaped otherwise is left whole
	# rather than guessed at.
	return "-".join(parts[2:]) if len(parts) >= 4 else (name or "")


def a3_tracking_url(doc) -> str:
	return qr_utils.tracking_url(doc)


def a3_upi_qr(amount, note: str = "", scale: int = 3) -> str:
	return qr_utils.upi_qr(flt(amount), note, scale=scale)


def a3_payment_qr(doc, scale: int = 3) -> str:
	return qr_utils.payment_qr(doc, scale=scale)


# ------------------------------------------------------------------- lookups
def a3_branch_profile(branch: str) -> dict:
	"""Address, GSTIN and contacts for the branch strip on a document.

	Branch Profile links an Address rather than holding the lines itself, so the
	two are flattened here into the shape every template and letter head wants.
	"""
	if not branch:
		return {}

	profile = frappe.db.get_value(
		"Branch Profile",
		{"branch": branch},
		["name", "branch", "trade_name", "signature", "invoice_terms", "address",
		 "contact_no", "branch_email", "gstin", "letter_head"],
		as_dict=True,
	)
	if not profile:
		return {}

	flat = {
		"name": profile.name,
		"branch": profile.branch,
		# What customers call the shop, which is not always what the branch is
		# called in the system — "PhoneXpert Digital store & Care" rather than
		# "PhoneXpert Sales PSLA".
		"trade_name": profile.get("trade_name") or profile.branch,
		"signature": profile.get("signature"),
		"invoice_terms": profile.get("invoice_terms"),
		"phone": profile.contact_no,
		"email": profile.branch_email,
		"gstin": profile.gstin,
		"letter_head": profile.letter_head,
		"address_line1": "",
		"address_line2": "",
		"city": "",
		"state": "",
		"pincode": "",
	}

	if profile.address and frappe.db.exists("Address", profile.address):
		address = frappe.db.get_value(
			"Address", profile.address,
			["address_line1", "address_line2", "city", "state", "pincode", "phone",
			 "email_id"],
			as_dict=True,
		)
		flat.update(
			{
				"address_line1": address.address_line1 or "",
				"address_line2": address.address_line2 or "",
				"city": address.city or "",
				"state": address.state or "",
				"pincode": address.pincode or "",
				"phone": flat["phone"] or address.phone,
				"email": flat["email"] or address.email_id,
			}
		)

	flat["address"] = ", ".join(
		part for part in (flat["address_line1"], flat["address_line2"], flat["city"],
		                  flat["state"], flat["pincode"]) if part
	)
	return flat


def a3_company_name() -> str:
	return frappe.db.get_single_value("Global Defaults", "default_company") or ""


def a3_setting(fieldname: str):
	return frappe.db.get_single_value("A3 Retail Settings", fieldname)


def a3_money(value, currency: str | None = None) -> str:
	return fmt_money(flt(value), currency=currency or "INR")


def a3_words(value, currency: str | None = None) -> str:
	return money_in_words(flt(value), currency or "INR")


# ---------------------------------------------------------------- tax helpers
def a3_hsn_summary(doc) -> list[dict]:
	"""HSN-wise taxable value and tax, as required on a GST tax invoice."""
	buckets: dict[str, dict] = {}

	for row in doc.get("items") or []:
		hsn = row.get("gst_hsn_code") or "-"
		bucket = buckets.setdefault(
			hsn, {"hsn": hsn, "qty": 0.0, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0,
			      "cess": 0.0, "total": 0.0}
		)
		bucket["qty"] += flt(row.get("qty"))
		bucket["taxable"] += flt(row.get("base_net_amount") or row.get("net_amount"))

	taxable_total = sum(bucket["taxable"] for bucket in buckets.values()) or 1.0

	# Tax rows carry no HSN, so the tax is apportioned on taxable value — which is
	# how the statutory summary is meant to read anyway.
	for tax in doc.get("taxes") or []:
		head = (tax.get("account_head") or "").lower()
		key = "cgst" if "cgst" in head else "sgst" if "sgst" in head else \
			"igst" if "igst" in head else "cess" if "cess" in head else None
		if not key:
			continue
		amount = flt(tax.get("base_tax_amount_after_discount_amount") or tax.get("tax_amount"))
		for bucket in buckets.values():
			bucket[key] += amount * bucket["taxable"] / taxable_total

	for bucket in buckets.values():
		bucket["total"] = (bucket["taxable"] + bucket["cgst"] + bucket["sgst"] + bucket["igst"]
		                   + bucket["cess"])

	return sorted(buckets.values(), key=lambda b: b["hsn"])


def a3_tax_rows(doc) -> list[dict]:
	return [
		{
			"description": tax.get("description") or tax.get("account_head"),
			"amount": flt(tax.get("base_tax_amount_after_discount_amount") or tax.get("tax_amount")),
		}
		for tax in doc.get("taxes") or []
		if flt(tax.get("tax_amount"))
	]


def a3_tax_lines(doc) -> list[tuple]:
	"""(label, amount) pairs — Jinja has no list comprehensions."""
	return [(row["description"], row["amount"]) for row in a3_tax_rows(doc)]


def a3_invoice_total_lines(doc) -> list[tuple]:
	lines = [("Net Total", flt(doc.get("base_net_total")))]
	if flt(doc.get("discount_amount")):
		lines.append(("Discount", -flt(doc.get("discount_amount"))))
	lines += a3_tax_lines(doc)
	if flt(doc.get("rounding_adjustment")):
		lines.append(("Rounding", flt(doc.get("rounding_adjustment"))))
	return lines


def a3_gst_lines(doc) -> list[tuple]:
	"""GST on the slip the way the shop's old software wrote it: "CGST @9%".

	The rate matters to a customer checking the arithmetic, and ERPNext's own
	description — "Output Tax CGST - PT" — is an account name, not something to
	hand across a counter.
	"""
	lines = []
	for tax in doc.get("taxes") or []:
		amount = flt(tax.get("base_tax_amount_after_discount_amount")
		             or tax.get("tax_amount"))
		if not amount:
			continue
		head = (tax.get("account_head") or tax.get("description") or "").upper()
		kind = ("IGST" if "IGST" in head else
		        "CGST" if "CGST" in head else
		        "SGST" if "SGST" in head else
		        "CESS" if "CESS" in head else "GST")
		rate = flt(tax.get("rate"))
		label = f"{kind} @{rate:g}%" if rate else kind
		lines.append((label, amount))
	return lines


def a3_line_note(row, doc=None) -> str:
	"""The small print under an item: its list price and the rate it carries.

	Only what is true of this line. The MRP is shown where the shop sold below
	its own list price, because that is the only time the two differ and the
	only time a customer is looking for it.
	"""
	bits = []
	listed = flt(row.get("price_list_rate"))
	charged = flt(row.get("rate"))
	if listed and listed > charged + 0.01:
		bits.append(f"MRP: {listed:,.0f}")
	rate = a3_line_gst_rate(row, doc)
	if rate:
		bits.append(f"GST: {rate:g}%")
	return ", ".join(bits)


def a3_line_gst_rate(row, doc=None) -> float:
	"""The GST rate on one line.

	Off the line's own tax template where it has one. A counter sale usually
	does not — the rate comes from the template on the bill as a whole — so the
	bill's own rate is worked back out of what it carries, which is the figure
	the customer is reading on the same slip anyway.
	"""
	template = row.get("item_tax_template")
	if template:
		rates = frappe.get_all("Item Tax Template Detail",
		                       filters={"parent": template}, pluck="tax_rate")
		if rates:
			return flt(sum(rates))

	if doc is None:
		return 0.0
	net = flt(doc.get("net_total"))
	tax = sum(flt(t.get("base_tax_amount_after_discount_amount") or t.get("tax_amount"))
	          for t in doc.get("taxes") or [])
	if net <= 0 or tax <= 0:
		return 0.0
	# To the nearest half point: GST rates are 5, 12, 18 and 28.
	return round(tax / net * 200) / 2


def a3_place_of_supply(doc) -> str:
	"""`32-Kerala` is how GST files it; `Kerala` is how a receipt reads."""
	place = str(doc.get("place_of_supply") or "")
	return place.split("-", 1)[1].strip() if "-" in place else place


def a3_payment_lines(doc) -> list[tuple]:
	return [
		(row.get("mode_of_payment") or "Payment", a3_money(row.get("amount")))
		for row in doc.get("payments") or []
	]


def a3_received_lines(doc) -> list[dict]:
	"""How the received amount was paid, one {label, amount} per method.

	A till sale keeps its tender in `payments`; a bill the customer did not settle
	in full is posted without them and receipted by a Payment Entry instead (see
	`api.pos._receipt`), so both are read. Cash is shown net of the change handed
	back, so the rows add up to the RECEIVED AMOUNT printed above them. A draft
	has taken nothing and lists nothing.
	"""
	if doc.get("docstatus") != 1:
		return []

	split_banks = {}
	if doc.get("a3_split_accounts"):
		try:
			split_banks = frappe.parse_json(doc.a3_split_accounts) or {}
		except ValueError:
			split_banks = {}
	financed_mode = frappe.db.get_value(
		"Finance Partner", doc.get("a3_finance_partner"), "mode_of_payment"
	) if doc.get("a3_finance_partner") else None

	def label(mode, account=None):
		text = mode or "Payment"
		if mode and mode == financed_mode:
			text += " (financed)"
		account = account or split_banks.get(mode)
		if account and frappe.db.get_value("Account", account, "account_type") == "Bank":
			text += " · " + (frappe.db.get_value("Account", account, "account_name") or account)
		return text

	lines = []
	change = flt(doc.get("change_amount"))
	for row in doc.get("payments") or []:
		amount = flt(row.get("amount"))
		if change and frappe.db.get_value("Mode of Payment", row.get("mode_of_payment"), "type") == "Cash":
			amount, change = amount - change, 0
		if amount > 0:
			lines.append({"label": label(row.get("mode_of_payment"), row.get("account")),
			              "amount": amount})

	for entry in frappe.db.sql(
		"""select pe.mode_of_payment, pe.paid_to, ref.allocated_amount
		   from `tabPayment Entry Reference` ref
		   join `tabPayment Entry` pe on pe.name = ref.parent
		   where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %s
		     and pe.docstatus = 1
		   order by pe.posting_date, pe.creation""",
		doc.name, as_dict=True,
	):
		if flt(entry.allocated_amount) > 0:
			lines.append({"label": label(entry.mode_of_payment, entry.paid_to),
			              "amount": flt(entry.allocated_amount)})
	return lines


def a3_thermal_total_lines(doc) -> list[tuple]:
	lines = [("Net", a3_money(doc.get("base_net_total")))]
	lines += [(label, a3_money(amount)) for label, amount in a3_tax_lines(doc)]
	if flt(doc.get("discount_amount")):
		lines.append(("Discount", a3_money(-flt(doc.get("discount_amount")))))
	return lines


def a3_thermal_height(doc, extra_mm: float = 0) -> int:
	"""How long a roll this receipt needs, in millimetres.

	A thermal page has to declare a real height. `size: 80mm auto` reads like
	the right thing and is not valid CSS — the two-value form takes two
	lengths — so Chrome drops the whole declaration and falls back to the
	paper the browser was last set to, which is how an 80mm receipt came out
	on A4.

	Estimated rather than measured, because CSS cannot measure. It is
	deliberately generous: a page a few millimetres too long feeds a little
	more roll, while one a few too short cuts the total off and prints it on a
	second slip.
	"""
	lines = len(doc.get("items") or [])
	serial_lines = sum(1 for row in (doc.get("items") or []) if a3_serials(row))
	tax_lines = len(a3_tax_lines(doc) or [])
	payments = len(doc.get("payments") or [])

	# Measured off real receipts rendered at 80mm rather than added up from the
	# stylesheet: a one-line bill comes to 120mm of roll and a seven-line one to
	# 149mm, which is a 115mm base and about 5mm a line. The 8mm on the end is
	# slack — a slip a little too long feeds a little more roll, one a little
	# too short prints its total on a second slip.
	height = (
		115                     # header, bill details, totals, QR, footer
		+ 5 * lines
		+ 5 * serial_lines
		+ 4 * (tax_lines + payments)
		+ 8
		+ extra_mm
	)
	return int(max(120, min(height, 900)))


def a3_serial_lines(doc) -> list[str]:
	"""'Item: IMEI, IMEI' for every line that carries serials."""
	lines = []
	for row in doc.get("items") or []:
		serials = a3_serials(row)
		if serials:
			lines.append(f"{row.get('item_name') or row.get('item_code')}: {serials}")
	return lines


def a3_serials(row) -> str:
	"""IMEIs on an invoice line, whether typed or held in a bundle."""
	from a3_retail.overrides.sales_invoice import _row_serials

	return ", ".join(_row_serials(row))


def a3_terms(doc, fallback_template: str | None = None) -> str:
	if doc.get("terms"):
		return doc.terms
	name = doc.get("tc_name") or fallback_template
	if name and frappe.db.exists("Terms and Conditions", name):
		return frappe.db.get_value("Terms and Conditions", name, "terms") or ""
	return ""


def a3_job_card_totals(doc) -> list[tuple]:
	return [
		("Parts", flt(doc.get("parts_total"))),
		("Labour", flt(doc.get("labour_total"))),
		("Discount", -flt(doc.get("discount_amount"))),
		("Tax", flt(doc.get("tax_amount"))),
		("Warranty Borne", -flt(doc.get("warranty_borne_amount"))),
		("Advance Paid", -flt(doc.get("advance_amount"))),
	]


def a3_clock(value) -> str:
	"""Time as a shop prints it — "1:41 PM", not "13:41:00"."""
	if not value:
		return ""
	if isinstance(value, str):
		value = value.split(".")[0]
		parts = value.split(":")
		if len(parts) < 2:
			return value
		hour, minute = int(parts[0]), parts[1]
	else:
		total = int(value.total_seconds()) if hasattr(value, "total_seconds") else 0
		hour, minute = total // 3600, f"{(total % 3600) // 60:02d}"
	suffix = "AM" if hour < 12 else "PM"
	shown = hour % 12 or 12
	return f"{shown}:{minute} {suffix}"


def a3_daymonth(value) -> str:
	"""Date as a shop prints it — 29/09/2026."""
	if not value:
		return ""
	return getdate(value).strftime("%d/%m/%Y")


def a3_job_card_intake(doc) -> dict:
	"""What the shop's paper service bill asks for, off the job card behind
	this invoice.

	The pad the counter used for years takes the device, its IMEI, the symptom
	as the customer described it, what came with it, the lock code the customer
	handed over and any advance. None of that is on a Sales Invoice, so a
	repair bill printed from one read as a shop sale with a line item on it and
	the customer had nothing in writing about their own phone.

	Returns `{}` when the invoice is not a repair, so the block simply does not
	appear on an ordinary sale.
	"""
	# A Sales Invoice keeps it in `a3_service_job_card`; the delivery note and
	# the estimate use `a3_job_card`. Both are tried so one helper serves all
	# of them — and so that naming it wrongly cannot silently print nothing,
	# which is what the Warranty block on this very sheet had been doing.
	card = ""
	if hasattr(doc, "get"):
		card = (doc.get("a3_service_job_card") or doc.get("a3_job_card") or "").strip()
	if not card or not frappe.db.exists("Service Job Card", card):
		return {}

	job = frappe.get_doc("Service Job Card", card)

	make = (job.get("brand") or "").strip()
	model = (job.get("device_model") or "").strip()
	# "Samsung Samsung S24" is what naming the make twice looks like.
	device = model if (make and model.lower().startswith(make.lower())) else \
		" ".join(part for part in (make, model) if part)

	imeis = [str(job.get(field) or "").strip()
	         for field in ("imei_1", "imei_2")]
	imeis = [imei for imei in imeis if imei]

	issues = [str(row.get("issue") or row.get("service_issue_type") or "").strip()
	          for row in (job.get("reported_issues") or [])]
	issues = [issue for issue in issues if issue]

	# What came in with the phone — the pad's Battery and Sim Tray boxes.
	with_it = []
	for row in (job.get("device_condition_checklist") or []):
		if not cint(row.get("received")):
			continue
		named = (row.get("accessory") or "").strip()
		if named:
			with_it.append(named + (f" ({row.get('condition')})"
			                        if row.get("condition") else ""))

	# A Password field is encrypted at rest, so it is asked for rather than
	# read off the document.
	try:
		lock = job.get_password("device_password", raise_exception=False)
	except Exception:
		lock = None

	received_by = frappe.db.get_value("Employee", job.get("received_by"),
	                                  "employee_name") if job.get("received_by") else None

	return {
		"job_card": job.name,
		"device": device or None,
		"imei": " · ".join(imeis) or None,
		"symptom": (job.get("complaint_description") or "").strip() or None,
		"issues": ", ".join(issues) or None,
		"condition": (job.get("physical_condition") or "").strip() or None,
		"accessories": ", ".join(with_it) or None,
		"lock": (lock or "").strip() or None,
		"advance": flt(job.get("advance_amount")) or 0,
		"received_on": job.get("received_on"),
		"received_by": received_by,
	}
