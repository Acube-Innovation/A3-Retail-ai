# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The protection plans PhoneXpert actually sells.

Financiers who write cover on a handset, and the makers' own programmes. The
list is a starting point, not a closed set — the counter can add one the moment
a new scheme turns up, which is the whole reason this is a master and not a
fixed dropdown.
"""

import frappe

PARTNERS = ("Bajaj", "TVS", "HDB", "DMI", "Home Credit",
            "Vivo", "Realme", "Apple", "Samsung")


def execute():
	made = 0
	for name in PARTNERS:
		if frappe.db.exists("Insurance Partner", name):
			continue
		doc = frappe.new_doc("Insurance Partner")
		doc.partner_name = name
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		made += 1
	print(f"  {made} insurance partner(s) added, {len(PARTNERS)} in the list")
