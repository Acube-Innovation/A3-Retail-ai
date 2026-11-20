# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Give each shop its own Google review link.

The invoice message ends with a button asking the customer to review the shop.
Parassala and Udayankulangara are separate Google listings with entirely
different review links, so the button cannot be one fixed URL.

It does not need to be. A WhatsApp template may carry a dynamic URL button —
`https://share.google/{{1}}` — and the suffix is supplied per message. So one
approved template serves every counter, and what tells them apart is this
field: the code at the end of each shop's own review link.

Set by site rather than by branch, because Sales, Accessories and Service at
one address are one shop to a customer and share one Google listing.
"""

import frappe

# The part after share.google/ in each shop's review link.
CODES = {
	"PSLA": "tWgPDUra2Fzch0do7",   # PhoneXpert Parassala
	"UK": "jm2uSVaUBW3VbAnKq",     # PhoneXpert Udayankulangara
}


def execute():
	if not frappe.db.has_column("Branch Profile", "google_review_code"):
		# The doctype change has not landed on this site yet.
		return

	set_here, left = [], []
	for row in frappe.get_all("Branch Profile",
	                          fields=["name", "branch", "site", "google_review_code"]):
		if (row.google_review_code or "").strip():
			# Typed in at the shop beats anything written here.
			continue
		code = CODES.get((row.site or "").strip().upper())
		if not code:
			left.append((row.branch, row.site))
			continue
		frappe.db.set_value("Branch Profile", row.name, "google_review_code", code,
		                    update_modified=False)
		set_here.append((row.branch, code))

	frappe.db.commit()

	print(f"  {len(set_here)} branch(es) given their shop's review link")
	for branch, code in sorted(set_here):
		print(f"      {branch} -> share.google/{code}")
	if left:
		print(f"  {len(left)} left without one — no review link is known for that site, "
		      "so their invoices go out without the button:")
		for branch, site in sorted(left):
			print(f"      {branch} (site {site or 'not set'})")
