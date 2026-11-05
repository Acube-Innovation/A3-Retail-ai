# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Give the Select Problem box something to select.

The list was empty, so every booking's complaint was free text and nothing
downstream could key off what was actually wrong with the device. These are the
faults a mobile counter books in week after week, grouped the way the doctype
groups them.

FRP Lock is the one that matters immediately: an account lock is cleared
through the maker and every one of them is asked for by IMEI, so picking it now
makes the booking insist on the number (`service_pos._check_frp_needs_imei`).
A locked phone will not show its IMEI on screen, which is exactly why it has to
be read off the box while the customer is still standing there.
"""

import frappe

ISSUES = [
	("FRP Lock / Google Account Lock", "Software", 48),
	("Screen Broken", "Display", 24),
	("Display Not Working", "Display", 24),
	("Touch Not Working", "Display", 24),
	("Battery Draining Fast", "Battery", 24),
	("Not Charging", "Charging", 24),
	("Charging Port Loose", "Charging", 24),
	("Speaker Not Working", "Audio", 24),
	("Microphone Not Working", "Audio", 24),
	("Camera Not Working", "Camera", 24),
	("No Network / No Signal", "Network", 48),
	("Software Hang / Restart", "Software", 24),
	("Dead / Not Switching On", "Board Level", 72),
	("Water Damage", "Liquid Damage", 72),
	("Physically Damaged", "Physical Damage", 48),
	("Slow Performance", "Performance", 24),
	("Other", "Other", 24),
]


def execute():
	made = 0
	for name, category, hours in ISSUES:
		if frappe.db.exists("Service Issue Type", name):
			continue
		doc = frappe.new_doc("Service Issue Type")
		doc.issue_name = name
		doc.category = category
		doc.standard_tat_hours = hours
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		made += 1
	print(f"  {made} service issue type(s) added, {len(ISSUES)} in the list")
