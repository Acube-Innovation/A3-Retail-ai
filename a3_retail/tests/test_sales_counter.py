# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Lifting the sales numbering clear of the numbers myBillBook has issued.

The shop bills in both books while the cutover runs, under one GSTIN, so a
number both books hand out is two tax invoices with one number. The patch
moves the ERPNext counter above myBillBook's reach. Everything here is about
the one direction it must never move: down, over numbers already given to a
customer.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.patches import sales_counter_clear_of_mybillbook as C

# A series no document uses, so the real counters are never touched.
FAKE = ("ZZ", "TS")
SERIES = f"{FAKE[0]}/{FAKE[1]}/{C.FY}/"


def _current():
	row = frappe.db.sql("select current from tabSeries where name = %s", SERIES)
	return int(row[0][0]) if row else None


class TestLiftingTheCounter(FrappeTestCase):
	def tearDown(self):
		frappe.db.sql("delete from tabSeries where name = %s", SERIES)

	def test_a_series_nobody_has_used_yet_starts_at_the_number_given(self):
		C._lift(*FAKE, 2135, 0)
		self.assertEqual(_current(), 2135, "the next bill should be 2136")

	def test_headroom_is_added_on_top(self):
		C._lift(*FAKE, 2135, 100)
		self.assertEqual(_current(), 2235,
		                 "myBillBook keeps billing, so the counter has to clear "
		                 "where it will be, not where it is")

	def test_a_counter_already_past_the_number_is_left_alone(self):
		C._lift(*FAKE, 2135, 0)
		C._lift(*FAKE, 2000, 0)
		self.assertEqual(_current(), 2135,
		                 "a stale number must never walk the counter back over "
		                 "bills that already exist")

	def test_it_rises_when_mybillbook_has_moved_on(self):
		C._lift(*FAKE, 2135, 0)
		C._lift(*FAKE, 2200, 0)
		self.assertEqual(_current(), 2200)


class TestItCannotReissueANumberThisSiteHasUsed(FrappeTestCase):
	"""The second guard: the documents in front of us beat a typed-in figure."""

	def test_the_highest_bill_here_is_read_off_the_bills_themselves(self):
		real = "PT/SL/26-27/"
		highest = C._highest_here(real)
		ours = frappe.db.sql("""
			select name from `tabSales Invoice` where name like %s
		""", (real + "%",), pluck=True)
		expected = max((int(n[len(real):]) for n in ours
		                if n[len(real):].isdigit()), default=0)
		self.assertEqual(highest, expected)

	def test_an_unused_series_reads_as_zero(self):
		self.assertEqual(C._highest_here(SERIES), 0)


class TestWhatItRefusesToDo(FrappeTestCase):
	def test_it_does_nothing_at_all_without_a_number(self):
		source = open(frappe.get_app_path(
			"a3_retail", "patches", "sales_counter_clear_of_mybillbook.py"),
			encoding="utf-8").read()
		self.assertIn("no myBillBook numbers given", source,
		              "an empty LAST_ISSUED has to be a no-op with a reason, "
		              "not a counter set to nothing")

	def test_it_never_renumbers_a_bill(self):
		source = open(frappe.get_app_path(
			"a3_retail", "patches", "sales_counter_clear_of_mybillbook.py"),
			encoding="utf-8").read()
		self.assertNotIn("rename", source.lower())
		self.assertNotIn("update `tabSales Invoice`", source)

	def test_it_is_registered_to_run_on_a_live_site(self):
		listed = open(frappe.get_app_path("a3_retail", "patches.txt"),
		              encoding="utf-8").read()
		self.assertIn("a3_retail.patches.sales_counter_clear_of_mybillbook", listed)
