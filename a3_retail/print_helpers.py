# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Jinja helpers available inside every print format (scope 13.3).

Registered through `hooks.jinja.methods`, so a template can call
`a3_tracking_qr(doc)` or `a3_hsn_summary(doc)` directly. Anything that needs a
loop, a lookup or arithmetic lives here rather than in the template — a print
format is hard to debug, and the sandbox makes non-trivial Jinja awkward.
"""

import frappe
from frappe.utils import flt, fmt_money, money_in_words

from a3_retail.utils import qr as qr_utils


# ------------------------------------------------------------------ QR / codes
def a3_qr(text: str, scale: int = 3) -> str:
	return qr_utils.qr_data_uri(text, scale=scale)


def a3_tracking_qr(doc, scale: int = 3) -> str:
	return qr_utils.tracking_qr(doc, scale=scale)


def a3_tracking_url(doc) -> str:
	return qr_utils.tracking_url(doc)


def a3_upi_qr(amount, note: str = "", scale: int = 3) -> str:
	return qr_utils.upi_qr(flt(amount), note, scale=scale)


def a3_payment_qr(doc, scale: int = 3) -> str:
	return qr_utils.payment_qr(doc, scale=scale)


def a3_barcode(value: str, height: int = 40) -> str:
	return qr_utils.barcode(value, height=height)


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
		["name", "branch", "address", "contact_no", "branch_email", "gstin", "letter_head"],
		as_dict=True,
	)
	if not profile:
		return {}

	flat = {
		"name": profile.name,
		"branch": profile.branch,
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


def a3_payment_lines(doc) -> list[tuple]:
	return [
		(row.get("mode_of_payment") or "Payment", a3_money(row.get("amount")))
		for row in doc.get("payments") or []
	]


def a3_thermal_total_lines(doc) -> list[tuple]:
	lines = [("Net", a3_money(doc.get("base_net_total")))]
	lines += [(label, a3_money(amount)) for label, amount in a3_tax_lines(doc)]
	if flt(doc.get("discount_amount")):
		lines.append(("Discount", a3_money(-flt(doc.get("discount_amount")))))
	return lines


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
