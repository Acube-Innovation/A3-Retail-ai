# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Print styles, branch letter heads and the 24 print formats (scope 13.3).

Each Print Format document is a thin wrapper — its `html` includes the template
of the same name under `templates/print_formats/`, so the markup lives in files
that can be diffed and reviewed rather than inside a database field. The
documents themselves are exported as fixtures so a fresh site gets them on
install.
"""

import frappe

TEMPLATE_PATH = "a3_retail/templates/print_formats"
MODULE = "A3 Retail Operations"

A4_STYLE = "A3 Retail A4"
THERMAL_STYLE = "A3 Retail Thermal 80mm"

# name, doctype, template, size, margins (top/bottom/left/right)
FORMATS = [
	("Job Card Receipt (Thermal)", "Service Job Card", "job_card_receipt_thermal", "80mm"),
	("Job Card Acknowledgement", "Service Job Card", "job_card_acknowledgement", "A5"),
	("Service Estimate", "Service Estimate", "service_estimate", "A4"),
	("Service Invoice", "Sales Invoice", "service_tax_invoice", "A4"),
	("Retail Tax Invoice", "Sales Invoice", "retail_tax_invoice", "A4"),
	("POS Receipt", "POS Invoice", "pos_receipt", "80mm"),
	("Delivery Challan", "Delivery Note", "delivery_challan", "A4"),
	("Device Delivery Note", "Service Job Card", "device_delivery_note", "A5"),
	("Warranty Certificate", "Warranty Registration", "warranty_certificate", "A4"),
	("Extended Warranty Card", "Warranty Registration", "extended_warranty_card", "A5"),
	("EMI Application Form", "EMI Application", "emi_application_form", "A4"),
	("EMI Document Checklist", "EMI Application", "emi_document_checklist", "A4"),
	("Financier Settlement Statement", "Financier Settlement",
	 "financier_settlement_statement", "A4"),
	("A3 Quotation", "Quotation", "quotation", "A4"),
	("A3 Purchase Order", "Purchase Order", "purchase_order", "A4"),
	("Stock Transfer Note", "Stock Request", "stock_transfer_note", "A4"),
	("Gate Pass", "Courier Dispatch", "gate_pass", "A5"),
	("Stock Damage Report", "Stock Damage Report", "stock_damage_report", "A4"),
	("Device Exchange Receipt", "Device Exchange", "device_exchange_receipt", "A5"),
	("Payment Receipt", "Payment Entry", "payment_receipt", "A5"),
	("Advance Receipt (Thermal)", "Payment Entry", "advance_receipt_thermal", "80mm"),
	("A3 Salary Slip", "Salary Slip", "salary_slip", "A4"),
	("Asset Custody Acknowledgement", "Asset Movement", "asset_custody_acknowledgement", "A4"),
	("RCM Self Invoice", "Purchase Invoice", "rcm_self_invoice", "A4"),
	("Courier Manifest", "Courier Dispatch", "courier_manifest", "A4"),
]

THERMAL_SIZES = {"80mm"}

A4_CSS = """
.print-format { font-family: "Inter", "Helvetica Neue", Helvetica, sans-serif; font-size: 9.5pt;
	color: #1f2937; }
.print-format table { page-break-inside: auto; }
.print-format tr { page-break-inside: avoid; }
.print-format thead { display: table-header-group; }
.print-format h4 { font-size: 8.5pt; text-transform: uppercase; letter-spacing: .6px;
	color: #374151; margin: 10px 0 2px; }
@page { size: A4; margin: 12mm 12mm 18mm 12mm; }
"""

THERMAL_CSS = """
@page { size: 80mm auto; margin: 2mm; }
.print-format { width: 76mm; font-family: "DejaVu Sans Mono", "Courier New", monospace;
	font-size: 8pt; color: #000; }
.print-format .letter-head, .print-format .letter-head-footer { display: none !important; }
"""


def run():
	ensure_print_styles()
	ensure_print_settings()
	ensure_letter_heads()
	ensure_print_formats()


# ------------------------------------------------------------------- styles
def ensure_print_styles():
	for name, css in ((A4_STYLE, A4_CSS), (THERMAL_STYLE, THERMAL_CSS)):
		if frappe.db.exists("Print Style", name):
			frappe.db.set_value("Print Style", name, "css", css, update_modified=False)
			continue
		doc = frappe.new_doc("Print Style")
		doc.print_style_name = name
		doc.css = css
		doc.standard = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def ensure_print_settings():
	settings = frappe.get_single("Print Settings")
	settings.print_style = A4_STYLE
	settings.repeat_header_footer = 1
	settings.with_letterhead = 1
	settings.add_draft_heading = 1
	settings.pdf_page_size = "A4"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


# -------------------------------------------------------------- letter heads
def ensure_letter_heads() -> int:
	"""One letter head per branch, carrying that branch's address and GSTIN."""
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		return 0

	from a3_retail.print_helpers import a3_branch_profile

	created = 0
	profiles = []
	for row in frappe.get_all("Branch Profile", fields=["name", "branch", "is_head_office"]):
		profile = frappe._dict(a3_branch_profile(row.branch))
		profile.is_head_office = row.is_head_office
		profile.name = row.name
		profiles.append(profile)

	for profile in profiles:
		name = f"{profile.branch} Letter Head"
		content = _letter_head_html(company, profile)
		footer = _letter_head_footer(profile)

		if frappe.db.exists("Letter Head", name):
			frappe.db.set_value(
				"Letter Head", name, {"content": content, "footer": footer}, update_modified=False
			)
		else:
			doc = frappe.new_doc("Letter Head")
			doc.letter_head_name = name
			doc.source = "HTML"
			doc.content = content
			doc.footer_source = "HTML"
			doc.footer = footer
			doc.is_default = 1 if profile.is_head_office else 0
			doc.disabled = 0
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created += 1

		if frappe.db.has_column("Branch Profile", "letter_head"):
			frappe.db.set_value("Branch Profile", profile.name, "letter_head", name,
			                    update_modified=False)

	if not frappe.db.exists("Letter Head", {"is_default": 1}) and profiles:
		frappe.db.set_value("Letter Head", f"{profiles[0].branch} Letter Head", "is_default", 1,
		                    update_modified=False)
	return created


def _letter_head_html(company: str, profile) -> str:
	address = profile.get("address") or ""
	contact = " · ".join(part for part in (profile.get("phone"), profile.get("email")) if part)
	return f"""<div class="a3-letter-head" style="display:flex;justify-content:space-between;
	align-items:flex-start;border-bottom:2px solid #0F62FE;padding-bottom:6px;margin-bottom:8px">
	<div>
		<div style="font-size:14pt;font-weight:700;color:#0F62FE">{company}</div>
		<div style="font-size:8pt;color:#4b5563">{profile.branch} Branch</div>
	</div>
	<div style="text-align:right;font-size:8pt;color:#4b5563;line-height:1.4">
		{address}<br>
		{contact}<br>
		GSTIN: {profile.get("gstin") or "—"}
	</div>
</div>"""


def _letter_head_footer(profile) -> str:
	contact = " · ".join(part for part in (profile.get("phone"), profile.get("email")) if part)
	return (
		'<div style="border-top:1px solid #E5E7EB;padding-top:4px;font-size:7.5pt;color:#6B7280">'
		f"{profile.branch} · {contact}</div>"
	)


# ------------------------------------------------------------- print formats
def ensure_print_formats() -> int:
	created = 0
	for name, doctype, template, size in FORMATS:
		if not frappe.db.exists("DocType", doctype):
			continue
		if _upsert_format(name, doctype, template, size):
			created += 1
	return created


def _upsert_format(name: str, doctype: str, template: str, size: str) -> bool:
	html = '{%% include "%s/%s.html" %%}' % (TEMPLATE_PATH, template)
	thermal = size in THERMAL_SIZES

	values = {
		"doc_type": doctype,
		"module": MODULE,
		"standard": "No",
		"print_format_type": "Jinja",
		"custom_format": 1,
		"disabled": 0,
		"html": html,
		"css": THERMAL_CSS if thermal else A4_CSS,
		"font_size": 8 if thermal else 9,
		"margin_top": 2 if thermal else 12,
		"margin_bottom": 2 if thermal else 18,
		"margin_left": 2 if thermal else 12,
		"margin_right": 2 if thermal else 12,
		# Thermal rolls have no page furniture; A4/A5 carry "Page x of y".
		"page_number": "Hide" if thermal else "Bottom Center",
		"align_labels_right": 0,
		"line_breaks": 0,
	}

	if frappe.db.exists("Print Format", name):
		frappe.db.set_value("Print Format", name, values, update_modified=False)
		return False

	doc = frappe.new_doc("Print Format")
	doc.name = name
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return True


# ------------------------------------------------------------ before_print
# Which field on each doctype names the branch.
BRANCH_FIELDS = ("branch", "a3_branch", "requesting_branch")


def apply_branch_letter_head(doc, method=None, print_settings=None):
	"""Pick the branch's letter head unless the user chose one explicitly.

	`printview.get_letter_head` reads `doc.letter_head` whether or not the doctype
	declares the field, so this works on our own doctypes too — none of them carry
	a letter-head selector on the form.
	"""
	if doc.get("letter_head"):
		return

	branch = None
	for fieldname in BRANCH_FIELDS:
		if doc.get(fieldname):
			branch = doc.get(fieldname)
			break

	if not branch:
		return

	letter_head = frappe.db.get_value("Branch Profile", {"branch": branch}, "letter_head") \
		if frappe.db.has_column("Branch Profile", "letter_head") else None
	letter_head = letter_head or f"{branch} Letter Head"

	if frappe.db.exists("Letter Head", letter_head):
		doc.letter_head = letter_head


def rendered_formats() -> list[tuple[str, str]]:
	"""(print format, doctype) pairs — used by the PDF smoke test."""
	return [(name, doctype) for name, doctype, _template, _size in FORMATS]


# ---------------------------------------------------------------- smoke test
def sample_doc(doctype: str):
	"""The newest real document of `doctype`, or an empty one to render against.

	A blank document still exercises every macro — the templates are written to
	survive missing values — so a format is never skipped just because that part
	of the demo dataset has not been seeded yet.
	"""
	name = frappe.db.get_value(doctype, {"docstatus": 1}, "name", order_by="modified desc") \
		or frappe.db.get_value(doctype, {}, "name", order_by="modified desc")
	if name:
		return frappe.get_doc(doctype, name), True

	doc = frappe.new_doc(doctype)
	doc.name = f"NEW-{frappe.scrub(doctype).upper()}"
	return doc, False


def smoke_test(as_pdf: bool = True, verbose: bool = True) -> dict:
	"""Render every format; fail loudly on an exception or an empty document.

	    bench --site <site> execute a3_retail.setup.print_formats.smoke_test

	`as_pdf` needs the site's web server running — wkhtmltopdf fetches the
	stylesheet over HTTP and exits non-zero if the connection is refused. Start
	`bench serve` first, or pass `as_pdf=False` to check the HTML only.
	"""
	from frappe.utils.pdf import get_pdf

	rows, failures = [], []
	for name, doctype, _template, size in FORMATS:
		if not frappe.db.exists("DocType", doctype):
			rows.append((name, doctype, "skipped", "doctype not installed"))
			continue

		doc, real = sample_doc(doctype)
		try:
			html = frappe.get_print(doctype, doc.name, print_format=name, doc=doc,
			                        no_letterhead=1 if size in THERMAL_SIZES else 0)
			if not (html or "").strip():
				raise ValueError("rendered empty")

			size_bytes = len(html)
			if as_pdf:
				pdf = get_pdf(html)
				if not pdf:
					raise ValueError("zero-byte PDF")
				size_bytes = len(pdf)

			rows.append((name, doctype, "ok" if real else "ok (blank doc)", f"{size_bytes} bytes"))
		except Exception as exc:
			message = str(exc)
			if "ConnectionRefused" in message:
				# The renderer could not reach the site for its stylesheet; that is
				# the bench, not the format.
				rows.append((name, doctype, "no server", "start `bench serve` for PDF checks"))
				continue
			failures.append(name)
			rows.append((name, doctype, "FAILED", message.split("\n")[0][:120]))

	if verbose:
		width = max(len(row[0]) for row in rows) + 2
		print(f"\n{'Print Format'.ljust(width)}{'Status'.ljust(18)}Detail")
		print("-" * (width + 50))
		for name, _doctype, status, detail in rows:
			print(f"{name.ljust(width)}{status.ljust(18)}{detail}")
		print(f"\n{len(rows) - len(failures)}/{len(rows)} formats rendered")

	return {"total": len(rows), "failed": failures, "rows": rows}
