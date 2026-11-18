# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Put the reverse-charge purchase templates in the shape that will post.

The RCM templates were built the way ERPNext did it before india_compliance
existed: the tax added in `Input Tax CGST RCM` and deducted again in
`Output Tax CGST RCM`, netting to the base amount payable. The ledger that
produces is right, and india_compliance will not accept it:

    Row #3: Output Tax CGST RCM - PT is not a valid GST account for this
    transaction

It sorts every GST account into a type in GST Settings, and `Output Tax * RCM`
is "Sales Reverse Charge" — the self-invoice's accounts, not a purchase's. A
bill built on one of these templates could not be saved at all.

The shape it does accept credits the *ordinary* input account and debits the
reverse-charge one:

    Input Tax CGST       9%   Add      -> the ITC
    Input Tax CGST RCM   9%   Deduct   -> the liability paid in cash

which also puts the ITC where `gst_itemised_purchase_register` and GSTR-2B
matching look for it, rather than in an account of its own that neither reads.

Only the rows change. The templates keep their names, so a held bill or a
supplier default pointing at one still points at it afterwards.
"""

import frappe

from a3_retail.setup.tax import rcm_template_rows


def execute():
	fixed, untouched, skipped = [], 0, []

	for template in frappe.get_all("Purchase Taxes and Charges Template",
	                               filters={"title": ["like", "Input GST RCM %"]},
	                               fields=["name", "title", "company"]):
		rate, out_of_state = _what_it_is_for(template.title)
		if rate is None:
			skipped.append((template.name, "cannot read a rate from the title"))
			continue

		rows = rcm_template_rows(template.company, rate, out_of_state)
		if not rows:
			skipped.append((template.name, "the company is missing a GST account"))
			continue

		doc = frappe.get_doc("Purchase Taxes and Charges Template", template.name)
		if _already_right(doc, rows):
			untouched += 1
			continue

		was = [f"{row.account_head} {row.add_deduct_tax}" for row in doc.taxes]
		doc.taxes = []
		for row in rows:
			doc.append("taxes", row)
		if doc.meta.has_field("is_reverse_charge"):
			doc.is_reverse_charge = 1
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		fixed.append((template.name, was,
		              [f"{row['account_head']} {row['add_deduct_tax']}" for row in rows]))

	frappe.db.commit()

	print(f"  {len(fixed)} reverse-charge template(s) re-shaped, {untouched} already right")
	for name, was, now in sorted(fixed):
		print(f"      {name}")
		print(f"          was: {', '.join(was) or '(no rows)'}")
		print(f"          now: {', '.join(now)}")
	if skipped:
		print(f"  {len(skipped)} left alone:")
		for name, why in sorted(skipped):
			print(f"      {name}: {why}")

	_warn_about_bills_already_posted()


def _what_it_is_for(title: str) -> tuple[int | None, bool]:
	"""The rate and direction a template's own name states."""
	out_of_state = "Out-state" in title
	for word in title.replace("%", " ").split():
		if word.isdigit():
			return int(word), out_of_state
	return None, out_of_state


def _already_right(doc, rows: list[dict]) -> bool:
	"""Same accounts, same sides, same rates — so a re-run reports honestly."""
	def shape(account, rate, side):
		return (account, round(float(rate or 0), 3), side)

	have = {shape(row.account_head, row.rate, row.add_deduct_tax) for row in doc.taxes}
	want = {shape(row["account_head"], row["rate"], row["add_deduct_tax"])
	        for row in rows}
	return have == want and len(doc.taxes) == len(rows)


def _warn_about_bills_already_posted():
	"""A bill posted on the old shape keeps the ledger it was posted with.

	Nothing here rewrites one — a submitted invoice is the shop's record and a
	GST return may already have been filed on it. If any exist, they want a
	person to look at them rather than a patch.
	"""
	posted = frappe.db.sql("""select pi.name, pi.taxes_and_charges
	                          from `tabPurchase Invoice` pi
	                          where pi.docstatus = 1
	                            and pi.taxes_and_charges like '%%Input GST RCM%%'
	                          order by pi.name""", as_dict=True)
	if not posted:
		return

	print(f"  {len(posted)} submitted bill(s) were posted on the old shape and are "
	      "left exactly as they are. Their ledgers hold Output Tax RCM rather "
	      "than Input Tax RCM — worth an accountant's eye before the next return:")
	for row in posted:
		print(f"      {row.name} ({row.taxes_and_charges})")
