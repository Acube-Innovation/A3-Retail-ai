# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stop rounding the GST on each bill, and stop the deploy switching it back.

`setup/tax.py` ran on every migrate and set GST Settings → Round Off GST Values
to 1. The shop turned it off in the desk; the next deploy turned it on again,
and the one after that. That setting is the shop's call — india_compliance's
own default for it is off — so the installer no longer touches it, and this
turns it off once on a site the installer already switched on.

Nothing already billed changes. The flag only adds the GST accounts to the list
ERPNext rounds when a document is saved, so it decides what the next bill does
and leaves every bill behind it exactly as it was posted.

This is written to be run again safely: a site that already has it off is left
alone and says nothing.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "GST Settings"):
		return

	settings = frappe.get_single("GST Settings")
	if not settings.meta.has_field("round_off_gst_values"):
		return
	if not settings.get("round_off_gst_values"):
		return

	settings.round_off_gst_values = 0
	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	print("  GST round off switched off; the installer no longer sets it")
