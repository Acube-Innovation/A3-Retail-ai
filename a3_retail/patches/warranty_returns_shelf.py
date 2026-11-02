# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""A Warranty Returns shelf at the Distribution godown.

A faulty accessory replaced at a counter goes to Distribution to wait for the
dealer. Put on Distribution's own shelf it would be counted as stock for sale —
in the tiles, at the POS, in what other branches are told Distribution holds —
so it gets a warehouse of its own:

- belonging to no branch, which keeps it out of every branch's sellable stock
  without each of those screens having to know about it;
- named on Distribution's Branch Profile, which is how the Stock page there
  knows to offer the Warranty Returns view;
- the Replace window's starting godown, in A3 Retail Settings.

Safe to run again, and on any site: a site with no Distribution branch is passed
over, the shelf is made once, and a godown somebody has deliberately chosen in
the settings is left alone.
"""

import frappe

DISTRIBUTION = "PhoneXpert Distribution"


def execute():
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": DISTRIBUTION},
		["name", "company", "default_warehouse", "warranty_returns_warehouse"], as_dict=True)
	if not profile or not profile.default_warehouse:
		return

	shelf = profile.warranty_returns_warehouse or _make_shelf(profile)
	frappe.db.set_value("Branch Profile", profile.name, "warranty_returns_warehouse", shelf)

	# Left alone if somebody chose a godown, unless it is Distribution's selling
	# shelf — where an earlier build of this pointed it, and where faulty stock
	# would be counted as stock for sale.
	chosen = frappe.db.get_single_value("A3 Retail Settings", "faulty_accessory_warehouse")
	if not chosen or chosen == profile.default_warehouse:
		frappe.db.set_single_value("A3 Retail Settings", "faulty_accessory_warehouse", shelf)


def _make_shelf(profile) -> str:
	name = f"{DISTRIBUTION} - Warranty Returns"
	existing = frappe.db.get_value("Warehouse",
	                               {"warehouse_name": name, "company": profile.company})
	if existing:
		return existing

	selling = frappe.db.get_value("Warehouse", profile.default_warehouse,
	                              ["parent_warehouse", "account"], as_dict=True)
	shelf = frappe.new_doc("Warehouse")
	shelf.warehouse_name = name
	shelf.company = profile.company
	shelf.parent_warehouse = selling.parent_warehouse
	shelf.account = selling.account
	shelf.is_group = 0
	shelf.flags.ignore_permissions = True
	shelf.insert()
	return shelf.name
