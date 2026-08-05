"""Seed 01 — Company, Fiscal Year, cost centers, letter head (scope 14.2)."""

import frappe

from a3_retail.setup import accounts, company


def run():
	company.run()
	accounts.run()
	_letter_head()


def _letter_head():
	"""A default letter head so print formats render before branch ones exist."""
	name = "A3 Retail Default"
	if frappe.db.exists("Letter Head", name):
		return

	doc = frappe.new_doc("Letter Head")
	doc.letter_head_name = name
	doc.is_default = 1
	doc.source = "HTML"
	doc.content = (
		'<div style="padding:6px 0;border-bottom:2px solid #0F62FE">'
		'<div style="font-size:15pt;font-weight:600">Mobile World Retail Pvt Ltd</div>'
		'<div style="font-size:8.5pt;color:#6B7280">'
		"GSTIN 32AABCM1234K1Z5 &middot; Kochi, Kerala &middot; care@mobileworld.in</div></div>"
	)
	doc.footer = (
		'<div style="font-size:7.5pt;color:#6B7280;border-top:1px solid #E5E7EB;padding-top:4px">'
		"This is a computer-generated document.</div>"
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
