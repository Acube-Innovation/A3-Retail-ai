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


def barcode_modules(text: str) -> int:
	"""How many bars and spaces a Code 128 of `text` comes to.

	What decides whether a barcode fits a label legibly: the symbol is this
	many modules wide whatever size it is drawn, so the width of one module —
	and so whether a printer can lay it down cleanly — falls out of this and
	the space available.
	"""
	if not text:
		return 0
	try:
		import barcode
	except ImportError:  # pragma: no cover - python-barcode ships with the bench
		return 0
	return len("".join(barcode.get("code128", str(text)).build()))


def barcode_svg_uri(text: str, height: float = 6.0, module_width: float = 0.26,
                    width_mm: float | None = None, quiet_zone: float = 2.0) -> str:
	"""SVG data URI of a Code 128 barcode for `text`.

	Vector, not pixels, and on a label that is the whole difference. A barcode
	drawn as a PNG has to be stretched to the width of the sticker, and the
	bars land wherever the scaling puts them — a 0.29mm bar that comes out
	0.24mm beside a 0.34mm one is what a scanner refuses to read. An SVG is
	redrawn at the printer's own resolution, so every bar is the width it was
	meant to be.

	Safe because the label is only ever rendered through the browser's print
	view (`service_pos.label_url`), which draws SVG properly. The PNG above
	stays for anything that goes through wkhtmltopdf.
	"""
	if not text:
		return ""

	try:
		import barcode
	except ImportError:  # pragma: no cover - python-barcode ships with the bench
		frappe.log_error("python-barcode is not installed", "A3 Retail: barcode")
		return ""

	# `width_mm` is the room the label has for the symbol. python-barcode's SVG
	# carries no viewBox, so it will not scale to its box — stretching the
	# `<img>` leaves the drawing at natural size in the corner. The bars are
	# sized to fit here instead, which is better anyway: every module comes out
	# the width it was asked for rather than whatever the scaling rounded it to.
	modules = barcode_modules(text)
	if width_mm and modules:
		module_width = max((float(width_mm) - 2 * quiet_zone) / modules, 0.1)

	stream = io.BytesIO()
	# No writer argument: python-barcode draws SVG by default.
	code = barcode.get("code128", str(text))
	code.write(stream, options={
		"module_height": height,
		"module_width": module_width,
		# The number is printed under the code by the label itself, in the
		# shop's own type, rather than in whatever this library defaults to.
		"write_text": False,
		"quiet_zone": quiet_zone,
	})
	encoded = base64.b64encode(stream.getvalue()).decode()
	return f"data:image/svg+xml;base64,{encoded}"


def barcode_data_uri(text: str, height: float = 12.0, module_width: float = 0.26,
                     width_mm: float | None = None, quiet_zone: float = 2.0,
                     dpi: int = 600) -> str:
	"""PNG data URI of a Code 128 barcode for `text`.

	A label printer is pointed at a shelf or a repair bay and the number is
	read by a gun, not by a person, so this is a 1D code rather than the QR
	used on the customer's paperwork — every cheap scanner reads Code 128, and
	it is what the shop's own stock labels already carry.

	A data URI because wkhtmltopdf runs with `--disable-local-file-access` and
	cannot fetch an image off the disk.
	"""
	if not text:
		return ""

	try:
		import barcode
		from barcode.writer import ImageWriter
	except ImportError:  # pragma: no cover - python-barcode ships with the bench
		frappe.log_error("python-barcode is not installed", "A3 Retail: barcode")
		return ""

	# `width_mm` is the room the label has for the symbol: the bars are drawn
	# to fill exactly that, rather than being drawn at some other size and
	# stretched to fit. Stretching is what turns a 0.28mm bar into a 0.24mm one
	# beside a 0.34mm one, which is a barcode a scanner argues with.
	modules = barcode_modules(text)
	if width_mm and modules:
		module_width = max((float(width_mm) - 2 * quiet_zone) / modules, 0.1)

	stream = io.BytesIO()
	code = barcode.get("code128", str(text), writer=ImageWriter())
	code.write(stream, options={
		"module_height": height,
		"module_width": module_width,
		# The number is printed under the code by the label itself, in the
		# shop's own type, rather than in whatever this library defaults to.
		"write_text": False,
		"quiet_zone": quiet_zone,
		# Drawn far finer than any label printer, so that scaling it down to
		# the printer's own dots can only ever lose detail it does not need.
		"dpi": dpi,
	})
	encoded = base64.b64encode(stream.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
