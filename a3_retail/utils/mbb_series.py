# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""myBillBook's numbering, carried on where it is safe to carry on.

PhoneXpert billed for years on myBillBook, one numbering series per business:
`PT/SL/26-27/2064` is a sales invoice from "PhoneXpert The Digital store",
`PD/EX/26-27/450` an expense at "Digital Store & Care". Customers, suppliers
and the GST portal all know these shapes, so where a branch maps cleanly onto
one old business, its documents keep counting in the same series rather than
starting a parallel history.

Only two mappings are clean, and only they are wired:

    PT/  →  Sales PSLA and Sales UK, together — one business then, one series now
    PD/  →  Accessories UK

The other four branches are left exactly as they are, on instruction.
Accessories PSLA and Distribution both used the bare `P/` prefix in myBillBook
and were already duplicating numbers against each other under one GSTIN —
`P/SL/26-27/1` exists twice — so carrying either forward would carry the
collision forward. The service branches never billed on myBillBook at all.

The financial year is written in, not computed, also on instruction: the shop
says what the new series is each April, and the counter starts again at 1
because the series name is new.

Two-letter codes, as myBillBook used them:
    SL sale · SR sales return · PU purchase · PR purchase return
    DN scheme debit note · EX expense · PI payment in · PT payment out
    PO purchase order
"""

import re

import frappe

FY = "26-27"
# The year alone, for amendment names. PT/SL/26-27/2065 is exactly the sixteen
# characters GST allows a document number, so ERPNext's own "-1" suffix pushes
# an amendment to eighteen and India Compliance refuses to save it. The
# amendment keeps its bill's number and drops half the year instead:
# PT/SL/26/2065-1, fifteen. Regular bills stay on the full year, as instructed.
FY_SHORT = FY.split("-")[0]

LONG = re.compile(r"^(PT|PD)/(SL|SR)/" + re.escape(FY) + r"/(\d+)$")
SHORT = re.compile(r"^(PT|PD)/(SL|SR)/" + re.escape(FY_SHORT) + r"/(\d+)-(\d+)$")

PREFIX_BY_BRANCH = {
	"PhoneXpert Sales PSLA": "PT",
	"PhoneXpert Sales UK": "PT",
	"PhoneXpert Accessories UK": "PD",
}


def series(prefix: str, code: str) -> str:
	# `.#` and not `.####`: myBillBook never padded, and PT/SL/26-27/0002065
	# would be a different number than the one the customer's copy carries.
	return f"{prefix}/{code}/{FY}/.#"


def _prefix(doc) -> str | None:
	branch = doc.get("branch")
	if not branch:
		from a3_retail.utils.branch import get_user_branch

		branch = get_user_branch()
	return PREFIX_BY_BRANCH.get(branch)


def _code(doc) -> str | None:
	"""Which series a document belongs to — myBillBook's own split.

	The one subtlety is the purchase side, where ERPNext keeps three of
	myBillBook's documents in a single doctype: a Purchase Invoice that moves
	stock out is a purchase return (PR), one that moves nothing but is a
	return is a scheme debit note (DN), and the rest are purchases (PU).
	"""
	if doc.doctype == "Sales Invoice":
		return "SR" if doc.get("is_return") else "SL"
	if doc.doctype == "Purchase Invoice":
		if doc.get("is_return"):
			return "PR" if doc.get("update_stock") else "DN"
		return "PU"
	if doc.doctype == "Payment Entry":
		return "PI" if doc.get("payment_type") == "Receive" else "PT"
	if doc.doctype == "Branch Expense":
		return "EX"
	if doc.doctype == "Purchase Order":
		return "PO"
	return None


def apply(doc, method=None):
	"""`before_naming` — put the document on its branch's myBillBook series.

	Runs last before autoname, so it wins over whatever default the field
	carried; a branch with no mapping falls through untouched and numbers
	exactly as yesterday.
	"""
	if doc.get("amended_from"):
		# Named from the bill it amends, not from a series — see `autoname`.
		return

	prefix = _prefix(doc)
	code = _code(doc)
	if prefix and code and doc.meta.has_field("naming_series"):
		doc.naming_series = series(prefix, code)


def autoname(doc, method=None):
	"""Name an amended Sales Invoice, keeping ERPNext's chain inside 16 chars.

	Reached because Amended Document Naming Settings routes Sales Invoice
	amendments to "Default Naming", which leaves the name empty for this hook
	instead of stamping `amended_from + "-1"` itself. For every bill that is
	not on a myBillBook series this does exactly what Frappe would have done —
	SINV-26-00498 becomes SINV-26-00498-1 — so nothing changes anywhere else.

	A myBillBook bill keeps its number and gives up half the year:
	PT/SL/26-27/2065 amends to PT/SL/26/2065-1. Same bill, same count, one
	character to spare against the GST limit, and the chain survives a second
	amendment as PT/SL/26/2065-2.
	"""
	if doc.name or not doc.get("amended_from"):
		return

	source = doc.amended_from

	long = LONG.match(source)
	if long:
		prefix, code, number = long.groups()
		doc.name = f"{prefix}/{code}/{FY_SHORT}/{number}-1"
		return

	short = SHORT.match(source)
	if short:
		prefix, code, number, count = short.groups()
		doc.name = f"{prefix}/{code}/{FY_SHORT}/{number}-{int(count) + 1}"
		return

	# Everyone else: Frappe's own rule, replicated because routing the doctype
	# through Default Naming turned the built-in version off for all of it.
	if frappe.db.get_value(doc.doctype, source, "amended_from"):
		count = frappe.utils.cint(source.rsplit("-", 1)[-1]) + 1
		doc.name = f"{source.rsplit('-', 1)[0]}-{count}"
	else:
		doc.name = f"{source}-1"
