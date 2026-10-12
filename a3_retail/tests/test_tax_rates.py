# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""What rate an Item Tax Template charges.

Worth a test of its own because the number is read in two places — the card at
the till and the Create New Item form — and both have to agree with the rate
the invoice actually posts.

Nothing is created here. india_compliance writes these templates, and a
hand-built imitation of one is only a guess at their shape; the templates on
the site are the real thing, and a template called "GST 12%" charging anything
other than 12 is the bug this guards against.
"""

import re

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.utils import tax

#: "GST 18% - PT" — the rate is in the name, which is what the shop reads.
NAMED_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


class TestTemplateRate(FrappeTestCase):
	def test_a_template_charges_the_rate_in_its_name(self):
		"""CGST and SGST are halves; IGST is the whole charge.

		This used to be read as "the largest row, doubled if under 15", on the
		assumption that the largest row was one half of a pair. It is not — it
		is the undivided IGST row — so a 12% item read as 24% and a 5% item as
		10%.
		"""
		checked = 0
		for name in frappe.get_all("Item Tax Template", pluck="name"):
			named = NAMED_RATE.search(name)
			if not named:
				continue
			expected = float(named.group(1))
			self.assertEqual(
				tax.template_rate(name), expected,
				f"{name} should charge {expected}%, not a half of it nor a sum of its rows")
			checked += 1
		if not checked:
			self.skipTest("no tax template on this site names its rate")

	def test_a_template_that_charges_nothing_reads_zero(self):
		for name in ("Nil-Rated", "Exempted", "Non-GST"):
			found = frappe.get_all("Item Tax Template",
			                       filters={"name": ["like", f"{name}%"]}, pluck="name")
			for template in found:
				self.assertEqual(tax.template_rate(template), 0.0, template)

	def test_no_template_is_not_a_rate(self):
		self.assertEqual(tax.template_rate(None), 0.0)
		self.assertEqual(tax.template_rate(""), 0.0)

	def test_an_item_with_no_template_falls_back_to_the_usual_rate(self):
		"""Most of what this shop sells is 18%, so an unmarked item is read as
		18% rather than as untaxed — an invoice that quietly charges nothing is
		worse than one that charges the usual rate."""
		plain = frappe.db.sql(
			"""select i.name from `tabItem` i
			   where i.disabled = 0 and not exists (
			       select 1 from `tabItem Tax` t
			       where t.parenttype = 'Item' and t.parent = i.name)
			   limit 1""", pluck=True)
		if not plain:
			self.skipTest("every item carries a tax template")
		self.assertEqual(tax.item_rate(plain[0]), tax.DEFAULT_GST_RATE)

	def test_an_item_is_taxed_at_its_own_templates_rate(self):
		row = frappe.get_all("Item Tax", filters={"parenttype": "Item"},
		                     fields=["parent", "item_tax_template"], limit=1)
		if not row:
			self.skipTest("no item on this site carries a tax template")
		self.assertEqual(tax.item_rate(row[0].parent),
		                 tax.template_rate(row[0].item_tax_template))

	def test_every_rate_on_offer_is_listed_lowest_first(self):
		"""The Create New Item form offers these, so they come out ordered and
		each one carries the number the shop would say out loud."""
		rows = tax.templates()
		if not rows:
			self.skipTest("no tax templates on this site")
		for row in rows:
			self.assertIn("name", row)
			self.assertGreaterEqual(row["rate"], 0)
			named = NAMED_RATE.search(row["name"])
			if named:
				self.assertEqual(row["rate"], float(named.group(1)), row["name"])
		self.assertEqual([r["rate"] for r in rows], sorted(r["rate"] for r in rows))
