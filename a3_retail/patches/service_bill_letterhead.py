# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Give the service bill the head the shop's own pad carries.

The printed service bill takes its heading from the branch it was raised at —
the trade name, the line under it, the address and the number — so that a
second service counter prints its own and not Parassala's. None of the service
branches had any of it on file, so the bill would have come out with a blank
head.

What goes on here is what is printed on the pad itself: the strapline on every
one of them, and for Parassala the address and number from the top of the
bill. Anything already filled in is left exactly as it is, because the shop
knows its own branches better than this patch does.
"""

import frappe

TAGLINE = "The Professional Grade Phone Service Centre"

# Straight off the top of the pad.
PARASSALA = {
	"branch": "PhoneXpert Services PSLA",
	"phone": "9447929607",
	"address_line1": "Karakonam Road, Opp. BSNL Office",
	"address_line2": "Post Office Jn",
	"city": "Parassala",
	"state": "Kerala",
	"pincode": "695502",
}


def execute():
	if not frappe.db.has_column("Branch Profile", "service_tagline"):
		# The doctype change has not landed on this site yet.
		return

	tagged = _tagline_on_service_branches()
	addressed = _address_for_parassala()

	frappe.db.commit()
	print(f"  {tagged} service branch(es) given the strapline")
	print(f"  {addressed} given the address off the pad")


def _tagline_on_service_branches() -> int:
	"""The same line under the shop's name wherever it repairs phones."""
	changed = 0
	for row in frappe.get_all("Branch Profile",
	                          fields=["name", "branch", "service_tagline"]):
		if (row.service_tagline or "").strip():
			continue
		if "service" not in (row.branch or "").lower():
			continue
		frappe.db.set_value("Branch Profile", row.name, "service_tagline", TAGLINE,
		                    update_modified=False)
		changed += 1
	return changed


def _address_for_parassala() -> int:
	"""The head of the bill, for the counter the pad belongs to.

	Only where the branch has no address at all: one typed by hand at the shop
	is better than this, and must not be written over.
	"""
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": PARASSALA["branch"]},
		["name", "address", "contact_no"], as_dict=True)
	if not profile:
		return 0

	if not (profile.contact_no or "").strip():
		frappe.db.set_value("Branch Profile", profile.name, "contact_no",
		                    PARASSALA["phone"], update_modified=False)

	if profile.address and frappe.db.exists("Address", profile.address):
		return 0

	title = f"{PARASSALA['branch']} - Service Bill"
	name = frappe.db.get_value("Address", {"address_title": title}, "name")
	if not name:
		address = frappe.get_doc({
			"doctype": "Address",
			"address_title": title,
			"address_type": "Office",
			"address_line1": PARASSALA["address_line1"],
			"address_line2": PARASSALA["address_line2"],
			"city": PARASSALA["city"],
			"state": PARASSALA["state"],
			"pincode": PARASSALA["pincode"],
			"country": "India",
			"phone": PARASSALA["phone"],
		})
		address.flags.ignore_permissions = True
		address.insert(ignore_permissions=True)
		name = address.name

	frappe.db.set_value("Branch Profile", profile.name, "address", name,
	                    update_modified=False)
	return 1
