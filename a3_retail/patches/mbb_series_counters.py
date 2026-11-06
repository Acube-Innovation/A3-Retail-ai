# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Continue the myBillBook numbering where the mapping is clean.

Seeds each series counter at the highest number myBillBook had issued when
the series were read from its API on 5 Nov 2026, and adds the new series to
the naming-series options so the desk recognises them.

A counter is only ever raised, never lowered: re-running this with stale
numbers cannot pull a series back over documents that already exist, and on
a site where the series has already moved past these marks the patch does
nothing. If the shop bills more on myBillBook before cutover, update COUNTS
and re-run (delete the Patch Log row for this patch first).

Series with no myBillBook history — PT/SR, and PD's purchase side — are not
seeded and simply start at 1 when first used.
"""

import frappe

from a3_retail.utils.mbb_series import FY

# prefix, code -> highest number issued in myBillBook (read 5 Nov 2026)
COUNTS = {
	("PT", "SL"): 2064,
	("PT", "PU"): 184,
	("PT", "PR"): 4,
	("PT", "DN"): 18,
	("PT", "EX"): 430,
	("PT", "PI"): 1954,
	("PT", "PT"): 68,
	("PT", "PO"): 1,
	("PD", "SL"): 5082,
	("PD", "SR"): 4,
	("PD", "EX"): 450,
	("PD", "PI"): 92,
}

# doctype -> the series codes it can carry, for the options property setter
OPTIONS = {
	"Sales Invoice": ("SL", "SR"),
	"Purchase Invoice": ("PU", "PR", "DN"),
	"Payment Entry": ("PI", "PT"),
	"Purchase Order": ("PO",),
}


def execute():
	_seed_counters()
	_extend_options()
	_route_amendments()


def _route_amendments():
	"""Send Sales Invoice amendments through the naming hook.

	Frappe's default stamps `amended_from + "-1"` before any hook can act, and
	on a sixteen-character myBillBook number that is an eighteen-character name
	India Compliance refuses at save. "Default Naming" is Frappe's own setting
	for handing an amendment to the ordinary naming path, where
	`mbb_series.autoname` names it — the same "-1" chain for every bill, with
	the myBillBook ones dropping half the year to stay inside the limit.
	"""
	settings = frappe.get_doc("Document Naming Settings")
	for row in settings.amend_naming_override or []:
		if row.document_type == "Sales Invoice":
			row.action = "Default Naming"
			break
	else:
		settings.append("amend_naming_override",
		                {"document_type": "Sales Invoice", "action": "Default Naming"})
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
	print("  Sales Invoice amendments routed through the naming hook")


def _seed_counters():
	raised = 0
	for (prefix, code), value in COUNTS.items():
		name = f"{prefix}/{code}/{FY}/"
		current = frappe.db.sql("select current from tabSeries where name = %s", name)
		if not current:
			frappe.db.sql(
				"insert into tabSeries (name, current) values (%s, %s)", (name, value))
			raised += 1
		elif int(current[0][0] or 0) < value:
			frappe.db.sql(
				"update tabSeries set current = %s where name = %s", (value, name))
			raised += 1
	print(f"  {raised} series counter(s) set; next PT/SL/{FY}/ number is "
	      f"{COUNTS[('PT', 'SL')] + 1}")


def _extend_options():
	"""Add the new series to each doctype's naming-series options.

	Appended to whatever the options already hold, so nothing a form offers
	today disappears; the per-branch hook picks the series, these entries only
	make the desk treat them as known.
	"""
	from frappe.custom.doctype.property_setter.property_setter import (
		make_property_setter,
	)

	for doctype, codes in OPTIONS.items():
		wanted = [f"{prefix}/{code}/{FY}/.#"
		          for prefix in ("PT", "PD") for code in codes]
		current = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "field_name": "naming_series", "property": "options"},
			"value") or ""
		lines = [line for line in current.split("\n")]
		added = [s for s in wanted if s not in lines]
		if not added:
			continue
		make_property_setter(
			doctype, "naming_series", "options",
			"\n".join(lines + added) if current else "\n".join(added),
			"Text", validate_fields_for_doctype=False)
	print("  naming-series options extended")
