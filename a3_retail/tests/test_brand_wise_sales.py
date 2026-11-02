# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Brand Wise Sales, and what the reports page learned to draw for it."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.a3_retail_sales.report.brand_wise_sales import brand_wise_sales as report
from a3_retail.api import reports

NAME = "Brand Wise Sales"
WINDOW = {"from_date": "2026-01-01", "to_date": "2026-12-31"}


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestBrandWiseSales(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_it_is_on_the_sales_shelf(self):
		listed = {row["name"]: row for row in reports.catalogue()["reports"]}
		self.assertIn(NAME, listed)
		self.assertEqual(listed[NAME]["category"], "sales")

	def test_the_filters_are_dates_brands_and_the_grouping_tick(self):
		filters = {row["fieldname"]: row for row in reports.definition(NAME)["filters"]}
		self.assertEqual(filters["from_date"]["fieldtype"], "Date")
		self.assertEqual(filters["to_date"]["fieldtype"], "Date")
		self.assertEqual(filters["brand"]["fieldtype"], "MultiSelectList")
		self.assertEqual(filters["group_by_brand"]["fieldtype"], "Check")
		# The brand list, and the bucket for everything without one.
		self.assertEqual(filters["brand"]["choices"][-1], report.OTHERS)

	def test_every_line_has_a_brand_even_without_one_on_record(self):
		result = reports.run(NAME, WINDOW)
		for row in result["rows"]:
			self.assertTrue(row["brand"], row["invoice"])

	def test_the_number_boxes_are_the_report_s_own(self):
		result = reports.run(NAME, WINDOW)
		boxes = {kpi["label"]: kpi["value"] for kpi in result["kpis"]}
		self.assertEqual(boxes["Bills"], len({row["invoice"] for row in result["rows"]}))
		self.assertAlmostEqual(boxes["Net Sales"],
		                       sum(flt(row["net_amount"]) for row in result["rows"]), places=2)

	def test_ungrouped_there_is_one_table(self):
		self.assertIsNone(reports.run(NAME, WINDOW)["summary"])

	def test_grouped_there_is_a_summary_that_adds_up_to_the_register(self):
		result = reports.run(NAME, {**WINDOW, "group_by_brand": 1})
		summary = result["summary"]
		self.assertTrue(summary)
		self.assertEqual(len({row["brand"] for row in summary["rows"]}), len(summary["rows"]))
		self.assertAlmostEqual(summary["totals"]["net_amount"],
		                       sum(flt(row["net_amount"]) for row in result["rows"]), places=2)
		# A bill with two brands counts for each; the total is distinct bills.
		self.assertEqual(summary["totals"]["bills"],
		                 len({row["invoice"] for row in result["rows"]}))
		if summary["rows"]:
			self.assertAlmostEqual(sum(row["share"] for row in summary["rows"]), 100, delta=0.1)

	def test_the_amount_with_gst_adds_back_to_each_bill(self):
		rows = reports.run(NAME, WINDOW)["rows"]
		billed = {}
		for row in rows:
			billed[row["invoice"]] = billed.get(row["invoice"], 0) + flt(row["gross_amount"])
		for invoice, amount in list(billed.items())[:25]:
			self.assertAlmostEqual(
				amount, flt(frappe.db.get_value("Sales Invoice", invoice, "base_grand_total")),
				delta=0.05, msg=invoice)

	def test_picking_brands_keeps_only_those_brands(self):
		result = reports.run(NAME, {**WINDOW, "brand": [report.OTHERS]})
		for row in result["rows"]:
			self.assertEqual(row["brand"], report.OTHERS)

	def test_a_branch_employee_only_sees_their_own_branch(self):
		result = reports.run(NAME, {**WINDOW, "branch": "Kozhikode"})
		self.assertEqual(result["branch"], "Kochi")
		for row in result["rows"]:
			self.assertEqual(row["branch"], "Kochi")


class TestTheReportsPageDrawsIt(FrappeTestCase):
	def test_the_page_has_room_for_a_second_table(self):
		markup = open(os.path.join(frappe.get_app_path("a3_retail", "www", "retail"),
		                           "reports.html")).read()
		self.assertIn('id="summary-panel"', markup)
		self.assertIn('id="table-title"', markup)

	def test_the_page_draws_a_tick_and_a_many_pick(self):
		script = open(frappe.get_app_path("a3_retail", "public", "js", "a3_reports.js")).read()
		self.assertIn('filter.fieldtype === "Check"', script)
		self.assertIn('filter.fieldtype === "MultiSelectList"', script)
		self.assertIn("function pickMany(", script)
		self.assertIn('data-range-to="rf-to_date"', script)

	def test_every_filter_in_the_file_reaches_the_page(self):
		"""The page reads filters out of the report's .js with a pattern that
		cannot see past nested braces — a `get_data` with a body would vanish."""
		body = open(frappe.get_app_path(
			"a3_retail", "a3_retail_sales", "report", "brand_wise_sales",
			"brand_wise_sales.js")).read()
		parsed = reports.FILTER_BLOCK.findall(body[body.index("filters:"):])
		self.assertEqual(len(parsed), body.count("fieldname:"))
