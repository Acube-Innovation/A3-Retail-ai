# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""The branch app's calendar, and the ready-made spans it offers a date range."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

RANGE_PAGES = ("bills", "bookings", "emi", "returns")


def _script(name: str) -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", name)).read()


class TestDateRangePresets(FrappeTestCase):
	def test_the_calendar_offers_the_spans_the_shop_asked_for(self):
		body = _script("a3_branch.js")
		spans = body[body.index("function presets("):body.index("function open(")]
		labels = ["This Month", "Previous Month", "This Week", "Previous Week", "Today",
		          "Yesterday", "This Month till date"]
		positions = [spans.index(f'["{label}"') for label in labels]
		self.assertEqual(positions, sorted(positions), "in the order the counter reads them")

	def test_a_span_fills_both_dates_before_either_is_announced(self):
		body = _script("a3_branch.js")
		pick = body[body.index('closest("[data-span]")'):body.index('closest("[data-ok]")')]
		self.assertLess(pick.index("range.to.value = to"), pick.index("dispatchEvent"))

	def test_a_span_stays_inside_the_box_s_own_limits(self):
		"""The filter sheet's dates stop at today; "This Month" there is the 1st
		to today, not a month end the box would refuse."""
		body = _script("a3_branch.js")
		self.assertIn("within(to, range.to)", body)
		self.assertIn('data-range-to="fs-to"', body)
		self.assertIn('data-range-from="fs-from"', body)

	def test_every_date_from_and_date_to_filter_is_a_range(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for page in RANGE_PAGES:
			markup = open(os.path.join(folder, f"{page}.html")).read()
			self.assertIn('id="from-date" type="date" data-range-to="to-date"', markup, page)
			self.assertIn('id="to-date" type="date" data-range-from="from-date"', markup, page)

		self.assertIn('data-range-to="t-to"', _script("a3_emi.js"), "the settlement window")

	def test_each_list_reads_the_pair_so_no_reload_has_half_a_range(self):
		for page in RANGE_PAGES:
			body = _script(f"a3_{page}.js")
			self.assertIn('state.filters.from_date = $("from-date").value', body, page)
			self.assertIn('state.filters.to_date = $("to-date").value', body, page)
