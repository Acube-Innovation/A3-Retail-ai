# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stop refusing a booking for want of a photograph.

A photograph is the shop's evidence of the scratch that was already there, and
it is worth taking — but a counter with a queue in front of them was being
refused at the one moment they cannot stop, and the camera is right there to
use whenever there is time for it. The gate goes; the button stays.

Only the gate is touched. `min_photos` is left as it is, so turning the
requirement back on in A3 Retail Settings restores exactly what was there.
"""

import frappe


def execute():
	frappe.db.set_single_value("A3 Retail Settings", "require_device_photos", 0)
	print("  device photos are no longer required to book a device in")
