# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""QR helpers for print formats (scope 13.3).

Three codes appear on paper: a tracking code that opens the portal page for a job
card or dispatch, a UPI code the customer can scan to pay, and the signed
e-Invoice QR that india_compliance receives from the IRP.

Everything returns a data URI so the PDF renderer never has to fetch a file —
wkhtmltopdf runs with `--disable-local-file-access`.
"""

import base64
import io
from urllib.parse import quote

import frappe
from frappe.utils import flt


def qr_data_uri(text: str, scale: int = 4) -> str:
	"""PNG data URI for `text`, or an empty string when there is nothing to encode."""
	if not text:
		return ""

	try:
		import pyqrcode
	except ImportError:  # pragma: no cover - pyqrcode ships with the bench
		frappe.log_error("pyqrcode is not installed", "A3 Retail: QR")
		return ""

	stream = io.BytesIO()
	pyqrcode.create(text, error="M").png(stream, scale=scale, quiet_zone=1)
	encoded = base64.b64encode(stream.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"


def site_url(path: str) -> str:
	base = (frappe.utils.get_url() or "").rstrip("/")
	return f"{base}/{path.lstrip('/')}"


def tracking_url(doc) -> str:
	"""The portal page a customer lands on when they scan the document."""
	if doc.doctype == "Service Job Card":
		return site_url(f"/track-repair?job={quote(doc.name)}")
	if doc.doctype == "Service Estimate":
		return site_url(f"/approve-estimate/{doc.get('portal_token') or ''}")
	if doc.doctype == "Warranty Registration":
		return site_url(f"/verify-warranty?ref={quote(doc.name)}")
	if doc.doctype == "Courier Dispatch":
		return site_url(f"/track-shipment?awb={quote(doc.get('awb_number') or doc.name)}")
	return site_url(f"/{frappe.scrub(doc.doctype)}/{quote(doc.name)}")


def tracking_qr(doc, scale: int = 3) -> str:
	return qr_data_uri(tracking_url(doc), scale=scale)


def upi_uri(amount: float, note: str = "", payee: str | None = None) -> str:
	"""`upi://pay` deep link built from the VPA in A3 Retail Settings."""
	vpa = frappe.db.get_single_value("A3 Retail Settings", "upi_vpa")
	if not vpa:
		return ""

	company = payee or frappe.db.get_single_value("Global Defaults", "default_company") or ""
	parts = [f"pa={quote(vpa)}", f"pn={quote(company)}", "cu=INR"]
	if flt(amount):
		parts.append(f"am={flt(amount, 2)}")
	if note:
		parts.append(f"tn={quote(note[:50])}")
	return "upi://pay?" + "&".join(parts)


def upi_qr(amount: float, note: str = "", scale: int = 3) -> str:
	return qr_data_uri(upi_uri(amount, note), scale=scale)


def einvoice_qr(doc, scale: int = 3) -> str:
	"""The IRP-signed QR, when india_compliance has generated one."""
	signed = doc.get("signed_qr_code") if hasattr(doc, "get") else None
	if not signed:
		return ""
	return qr_data_uri(signed, scale=scale)


def payment_qr(doc, scale: int = 3) -> str:
	"""e-Invoice QR when the invoice is signed, otherwise a UPI code."""
	return einvoice_qr(doc, scale) or upi_qr(
		doc.get("outstanding_amount") or doc.get("grand_total"), doc.name, scale
	)


def barcode(value: str, height: int = 40) -> str:
	"""Code128 barcode as a data URI — job cards are pulled off a rack by scan."""
	if not value:
		return ""
	try:
		from frappe.utils import get_barcode  # type: ignore
	except ImportError:
		get_barcode = None

	if get_barcode:
		try:
			return get_barcode(value, height=height)
		except Exception:
			pass
	# No barcode writer on the bench — the QR carries the same value.
	return qr_data_uri(value, scale=3)
