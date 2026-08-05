# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Custom fields on core ERPNext/HRMS doctypes.

Golden rule 1: never edit core files. Everything here is created through
`create_custom_fields`, tagged with an A3 Retail module so it is exported by the
`Custom Field` fixture in hooks.py, and is safe to re-run.

Naming: our own fields are prefixed `a3_` so they can never collide with a future
ERPNext field. The two exceptions are `custom_branch` on Warehouse / Cost Center /
POS Profile, which the scope document names explicitly (6.1) because reports and
the Stock Explorer query it by name.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OPS_MODULE = "A3 Retail Operations"


def branch_link(label="Branch", **kwargs):
	field = {
		"fieldname": "custom_branch",
		"label": label,
		"fieldtype": "Link",
		"options": "Branch",
		"module": OPS_MODULE,
		"read_only": 1,
		"no_copy": 1,
		"description": "Set from Branch Profile. Used by branch-wise reports and the Stock Explorer.",
	}
	field.update(kwargs)
	return field


# Step 2 — branch back-references on the stock/accounting masters.
BRANCH_BACKREF_FIELDS = {
	"Warehouse": [branch_link(insert_after="company", in_standard_filter=1)],
	"Cost Center": [branch_link(insert_after="company")],
	"POS Profile": [branch_link(insert_after="company")],
}


def run():
	"""Create every custom field this app owns. Idempotent."""
	create_custom_fields(BRANCH_BACKREF_FIELDS, ignore_validate=True, update=True)
	_tag_module()


def _tag_module():
	"""Ensure every field we own carries an A3 module so fixtures pick it up."""
	fieldnames = set()
	for fields in BRANCH_BACKREF_FIELDS.values():
		fieldnames.update(f["fieldname"] for f in fields)

	for name in frappe.get_all(
		"Custom Field",
		filters={"fieldname": ["in", list(fieldnames)], "module": ["in", [None, ""]]},
		pluck="name",
	):
		frappe.db.set_value("Custom Field", name, "module", OPS_MODULE, update_modified=False)
