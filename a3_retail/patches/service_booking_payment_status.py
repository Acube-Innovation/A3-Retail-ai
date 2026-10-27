# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Bring every existing repair's payment state in line with its bill.

Until now a Service Job Card was stamped once, when its invoice was raised, and
the money almost always arrived afterwards — so the bookings list showed repairs
as unpaid long after the customer had settled and gone. Going forward the card
follows the bill (see `overrides/service_payment.py`); this is the catching up.

Nothing is invented: a repair is only moved if it has a submitted bill, and what
it is moved to is read off that bill. A repair with no bill is left alone, and
so is one whose bill is still owed.
"""

import frappe


def execute():
	from a3_retail.overrides.service_payment import refresh

	# Both directions: a card that names its bill, and a bill that names its
	# card where the card never recorded it. The second has not happened on any
	# site so far, but it is the cheaper of the two to be wrong about.
	cards = set(frappe.get_all(
		"Service Job Card",
		filters={"docstatus": 1, "sales_invoice": ("is", "set")}, pluck="name"))

	orphans = frappe.db.sql("""
		select si.a3_service_job_card as card, si.name as invoice
		from `tabSales Invoice` si
		join `tabService Job Card` jc on jc.name = si.a3_service_job_card
		where si.docstatus = 1 and ifnull(si.a3_service_job_card, '') <> ''
		  and ifnull(jc.sales_invoice, '') = ''
		""", as_dict=True) if frappe.db.has_column("Sales Invoice", "a3_service_job_card") else []

	for row in orphans:
		frappe.db.set_value("Service Job Card", row.card, "sales_invoice",
		                    row.invoice, update_modified=False)
		cards.add(row.card)

	moved, counts = 0, {}
	for name in sorted(cards):
		before = frappe.db.get_value("Service Job Card", name, "payment_status")
		after = refresh(name)
		if after and after != before:
			moved += 1
			counts[f"{before} -> {after}"] = counts.get(f"{before} -> {after}", 0) + 1

	left = frappe.db.sql("""
		select count(*) from `tabService Job Card` jc
		join `tabSales Invoice` si on si.name = jc.sales_invoice
		where jc.docstatus = 1 and si.docstatus = 1
		  and jc.payment_status <> 'Paid' and si.outstanding_amount <= 0.005
		""")[0][0]

	print(f"  Service bookings: {len(cards)} with a bill, {moved} restated"
	      + (f", {len(orphans)} bill links repaired" if orphans else ""))
	for move, n in sorted(counts.items()):
		print(f"    {n:>4}  {move}")
	if left:
		print(f"  WARNING: {left} settled bills still not showing Paid")
