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


# The shop's label printer is a TVS LP 46 Neo, an SNBC BTP-U100t underneath.
# Its head is built to a round metric pitch — eight dots to the millimetre,
# which is 203.2dpi — but it is *sold* as 203dpi, and 203 is the number every
# driver carries. A page is therefore rasterised at 203/25.4 dots to the
# millimetre, not 8, and the tenth of a percent between those two is not
# academic: computing a symbol at 8 and having it drawn at 203/25.4 left a
# quarter of a dot of drift across the barcode, which is enough for an edge to
# round the wrong way and an element to come out a dot wide or narrow.
#
# So the figure here is the renderer's, not the hardware's. The symbol is laid
# out in the dots the driver will actually produce; the head then lays those
# dots down at its own slightly finer pitch, which makes the printed symbol
# about four hundredths of a millimetre narrower than asked for and is not
# visible on a sticker. Being right about this is also what makes it portable:
# the shop's Windows driver calls itself 203dpi too.
LABEL_DOTS_PER_MM = 203 / 25.4


def barcode_dot_width(text: str, max_mm: float,
                      dots_per_mm: float = LABEL_DOTS_PER_MM,
                      module_dots: int = 2, quiet_modules: int = 10) -> float:
	"""How wide to place a Code 128 so one module is `module_dots` whole dots.

	`quiet_modules` is the clear margin each side, counted in modules; GS1 asks
	for ten on a Code 128, and it is what a scanner looks for to find the
	symbol's edges at all.

	Returns 0.0 when the symbol will not fit `max_mm`, so a label can leave the
	barcode off rather than print one too cramped to read.
	"""
	modules = barcode_modules(text)
	if not modules or module_dots < 1 or dots_per_mm <= 0:
		return 0.0
	width = (modules + 2 * quiet_modules) * module_dots / dots_per_mm
	return round(width, 4) if width <= max_mm else 0.0


def barcode_bars_uri(text: str, height_mm: float = 9.0,
                     module_dots: int = 2, quiet_modules: int = 10,
                     dots_per_mm: float = LABEL_DOTS_PER_MM) -> str:
	"""Code 128 as vector bars, which a renderer cannot dither.

	A bitmap barcode only survives if it lands on the paper at exactly one
	image pixel per printer dot. Nothing in the chain between this template and
	the print head will promise that: Chrome rounds a page box to the nearest
	hundredth of an inch, CUPS rounds the raster to whole dots at a nominal
	203dpi that is not quite the head's 203.2, and the shop's Windows driver
	will round differently again. Miss by a third of a dot and the resampler
	starts interpolating, and a one-bit image interpolated comes out as bars
	with dotted, ragged edges — which is what a 2-up sticker showed down its
	middle third, where the drift reached half a dot.

	Drawn as rectangles there is nothing to resample. `shape-rendering` of
	`crispEdges` turns off anti-aliasing, so every bar is laid down solid and
	its edges snap to whichever dot they land nearest. A bar may come out a dot
	wider or narrower than its neighbour, which a scanner takes in its stride
	because it reads the symbol's widths relative to each other — but no bar is
	ever a grey smear, which is what it cannot read.

	The `viewBox` is in modules, so the symbol's proportions are exact whatever
	width the label places it at, and `preserveAspectRatio="none"` keeps the
	bars filling that width rather than being letterboxed inside it.
	"""
	if not text:
		return ""

	try:
		import barcode
	except ImportError:  # pragma: no cover - python-barcode ships with the bench
		frappe.log_error("python-barcode is not installed", "A3 Retail: barcode")
		return ""

	if module_dots < 1 or dots_per_mm <= 0:
		return ""

	pattern = "".join(barcode.get("code128", str(text)).build())
	if not pattern:
		return ""

	# Height in module units, so the viewBox stays in one set of units.
	module_mm = module_dots / dots_per_mm
	tall = max(round(flt(height_mm) / module_mm, 3), 1)
	wide = len(pattern) + 2 * quiet_modules

	rects, run_start = [], None
	for index, module in enumerate(pattern + "0"):
		if module == "1" and run_start is None:
			run_start = index
		elif module != "1" and run_start is not None:
			rects.append(f'<rect x="{quiet_modules + run_start}" y="0"'
			             f' width="{index - run_start}" height="{tall}"/>')
			run_start = None

	# The width and height are stated on the element, in millimetres, because
	# `preserveAspectRatio="none"` tells a browser the viewBox carries no
	# meaningful aspect ratio — and with nothing to go on, `height: auto` in the
	# label falls back to the 300x150 default every SVG without dimensions gets,
	# which came out at 14mm of bars running off the bottom of the sticker.
	width_mm = round(wide * module_mm, 4)
	svg = (f'<svg xmlns="http://www.w3.org/2000/svg"'
	       f' width="{width_mm}mm" height="{round(flt(height_mm), 4)}mm"'
	       f' viewBox="0 0 {wide} {tall}"'
	       f' preserveAspectRatio="none" shape-rendering="crispEdges"'
	       f' fill="#000">{"".join(rects)}</svg>')
	encoded = base64.b64encode(svg.encode()).decode()
	return f"data:image/svg+xml;base64,{encoded}"


def barcode_dot_uri(text: str, height_mm: float = 8.0,
                    dots_per_mm: float = LABEL_DOTS_PER_MM,
                    module_dots: int = 2, quiet_modules: int = 10) -> str:
	"""Code 128 painted a dot at a time, every module exactly the same width.

	`barcode_data_uri` asks python-barcode for a symbol in millimetres drawn at
	a fine resolution, and leaves the printer to scale it down. That reads as
	the careful thing to do and is not. Measured on the 40mm sticker at the
	shop's own 203 dots to the inch, it put 38 of the symbol's narrow bars at a
	single dot, two at two dots and nine at three, and left a quiet zone of
	1.1mm where ten modules is 2.5mm. A scanner takes the narrowest element it
	can find as the yardstick for every other width in the symbol, so that
	spread is not a cosmetic matter: it is the difference between a sticker the
	bench reads first time and one it gives up on.

	So the bars are laid out here in the printer's own dots. The module pattern
	comes from python-barcode, which is what it is good at, and each module is
	then painted as exactly `module_dots` columns of pixels. Nothing is scaled
	and nothing is rounded, so every bar in the symbol is identical by
	construction whatever the rasteriser downstream chooses to do.

	The image comes back at its natural size in dots. The label must place it at
	`barcode_dot_width` millimetres, which is that same size expressed in paper
	units, so that one pixel lands on one dot.
	"""
	if not text:
		return ""

	try:
		import barcode
		from PIL import Image
	except ImportError:  # pragma: no cover - both ship with the bench
		frappe.log_error("python-barcode or Pillow is not installed",
		                 "A3 Retail: barcode")
		return ""

	if module_dots < 1 or dots_per_mm <= 0:
		return ""

	pattern = "".join(barcode.get("code128", str(text)).build())
	if not pattern:
		return ""

	width = (len(pattern) + 2 * quiet_modules) * module_dots
	height = max(int(round(flt(height_mm) * dots_per_mm)), 1)

	# Mode "1" is one bit a pixel: a bar is either burnt or it is not, which is
	# all the print head can do anyway, and it keeps the data URI small enough
	# to sit in the page without comment.
	image = Image.new("1", (width, height), 1)
	pixels = image.load()
	x = quiet_modules * module_dots
	for module in pattern:
		if module == "1":
			for column in range(x, x + module_dots):
				for row in range(height):
					pixels[column, row] = 0
		x += module_dots

	stream = io.BytesIO()
	image.save(stream, format="PNG")
	encoded = base64.b64encode(stream.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
