# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Reports in the branch app (`/branch/reports`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import reports
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestReportsPage(FrappeTestCase):
	def test_the_page_is_one_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("reports.html", "reports.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "reports.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_reports.js", markup)
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_the_catalogue_and_the_report_share_the_page(self):
		"""One page, two states — not two pages."""
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "reports.html")
		).read()
		self.assertIn('id="catalogue"', markup)
		self.assertIn('id="viewer"', markup)
		self.assertIn("Back to Reports", markup)
		self.assertIn("Print Report", markup)

	def test_reports_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("reports", "Reports", "/branch/reports"', sidebar)

	def test_there_is_one_print_routine_for_every_report(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_reports.js")).read()
		self.assertEqual(body.count("function printReport("), 1)
		self.assertIn("size: A4", body)


class TestReportsAccess(FrappeTestCase):
	def test_a_guest_cannot_list_the_reports(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, reports.catalogue)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, reports.catalogue)


class TestReportCatalogue(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_catalogue_is_the_reports_the_erp_already_has(self):
		catalogue = reports.catalogue()
		self.assertTrue(catalogue["reports"])
		for report in catalogue["reports"]:
			self.assertTrue(frappe.db.exists("Report", report["name"]), report["name"])
			for key in ("description", "category", "favourite", "last_run"):
				self.assertIn(key, report, key)

	def test_a_report_this_person_may_not_run_is_not_offered(self):
		"""The gate is Frappe's own: the report's roles and its doctype."""
		offered = {report["name"] for report in reports.catalogue()["reports"]}
		for name in frappe.get_all("Report", filters={"module": ["like", "A3 Retail%"]},
		                           pluck="name"):
			if name in offered:
				continue
			self.assertFalse(reports._may_run(name), name)

	def test_every_offered_report_lands_in_a_category(self):
		catalogue = reports.catalogue()
		keys = {category["key"] for category in catalogue["categories"]}
		for report in catalogue["reports"]:
			self.assertIn(report["category"], keys, report["name"])

	def test_the_counts_on_the_cards_match_the_list(self):
		catalogue = reports.catalogue()
		for category in catalogue["categories"]:
			listed = len([r for r in catalogue["reports"] if r["category"] == category["key"]])
			self.assertEqual(category["count"], listed, category["key"])

	def test_a_favourite_survives_the_next_page_load(self):
		name = reports.catalogue()["reports"][0]["name"]

		starred = reports.toggle_favourite(name)
		self.assertTrue(starred["favourite"])
		self.assertIn(name, reports.catalogue()["favourites"])

		unstarred = reports.toggle_favourite(name)
		self.assertFalse(unstarred["favourite"])
		self.assertNotIn(name, reports.catalogue()["favourites"])


class TestReportDefinition(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_filters_come_from_the_report_s_own_file(self):
		"""Adding a report brings its filters with it; this page needs no edit."""
		definition = reports.definition("Branch Sales Register")
		fields = {row["fieldname"] for row in definition["filters"]}
		self.assertEqual(fields, {"from_date", "to_date", "branch"})

		dates = [row for row in definition["filters"] if row["fieldtype"] == "Date"]
		self.assertTrue(all(row["default"] for row in dates), "a date filter arrives filled in")

	def test_a_report_with_one_filter_says_so(self):
		definition = reports.definition("Stock Ageing and Dead Stock")
		self.assertEqual([row["fieldname"] for row in definition["filters"]], ["branch"])

	def test_a_branch_employee_cannot_widen_the_branch(self):
		definition = reports.definition("Branch Sales Register")
		self.assertTrue(definition["branch_locked"])
		self.assertEqual(definition["branch"], "Kochi")

	def test_a_report_out_of_reach_is_refused_by_name(self):
		blocked = [name for name in frappe.get_all(
			"Report", filters={"module": ["like", "A3 Retail%"]}, pluck="name")
			if not reports._may_run(name)]
		if not blocked:
			self.skipTest("this person can run everything")
		self.assertRaises(frappe.PermissionError, reports.definition, blocked[0])


class TestRunningAReport(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_report_answers_with_what_the_page_draws(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		for key in ("columns", "rows", "totals", "kpis", "generated_on", "generated_by", "branch"):
			self.assertIn(key, result, key)
		self.assertTrue(result["columns"])
		self.assertEqual(result["row_count"], len(result["rows"]))

	def test_the_rows_are_the_erp_s_own(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		if not result["rows"]:
			self.skipTest("no sales in the window")

		row = result["rows"][0]
		self.assertTrue(frappe.db.exists("Sales Invoice", row["name"]))
		self.assertAlmostEqual(
			flt(row["base_grand_total"]),
			flt(frappe.db.get_value("Sales Invoice", row["name"], "base_grand_total")),
			places=2,
		)

	def test_an_average_column_is_not_added_up(self):
		"""Three technicians' average turnaround times do not sum to anything."""
		result = reports.run("Technician Productivity",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		averages = [column["fieldname"] for column in result["columns"]
		            if column["fieldtype"] in ("Float", "Percent")]
		for fieldname in averages:
			self.assertNotIn(fieldname, result["totals"], fieldname)

	def test_the_totals_are_the_sum_of_the_rows(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		for fieldname, total in result["totals"].items():
			self.assertAlmostEqual(
				total, sum(flt(row.get(fieldname)) for row in result["rows"]), places=2
			)

	def test_a_branch_employee_only_ever_sees_their_own_branch(self):
		"""A raw SQL report does not go through user permissions, so the branch
		is applied on the way in rather than trusted from the browser."""
		result = reports.run("Branch Sales Register", {
			"from_date": "2026-01-01", "to_date": "2026-12-31", "branch": "Kozhikode",
		})
		self.assertEqual(result["branch"], "Kochi")
		for row in result["rows"]:
			self.assertEqual(row.get("branch"), "Kochi")

	def test_the_kpis_are_the_money_on_the_report(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		self.assertEqual(result["kpis"][0]["label"], "Rows")
		self.assertEqual(result["kpis"][0]["value"], result["row_count"])
		for kpi in result["kpis"][1:]:
			self.assertIn(kpi["fieldtype"], ("Currency", "Int"))

	def test_a_report_with_nothing_in_the_window_is_empty_not_broken(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "1999-01-01", "to_date": "1999-01-31"})
		self.assertEqual(result["rows"], [])
		self.assertEqual(result["row_count"], 0)
		self.assertIsNone(result["chart"])

	def test_a_chart_is_offered_only_when_the_data_has_a_shape(self):
		result = reports.run("Branch Sales Register",
		                     {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		if not result["chart"]:
			self.skipTest("not enough days in the window")
		self.assertIn(result["chart"]["kind"], ("line", "bar"))
		self.assertGreaterEqual(len(result["chart"]["points"]), 2)

	def test_running_a_report_out_of_reach_is_refused(self):
		blocked = [name for name in frappe.get_all(
			"Report", filters={"module": ["like", "A3 Retail%"]}, pluck="name")
			if not reports._may_run(name)]
		if not blocked:
			self.skipTest("this person can run everything")
		self.assertRaises(frappe.PermissionError, reports.run, blocked[0], {})

	def test_every_offered_report_actually_runs(self):
		"""The catalogue must not offer a report that falls over when opened."""
		for report in reports.catalogue()["reports"]:
			with self.subTest(report=report["name"]):
				result = reports.run(report["name"], {
					row["fieldname"]: row["default"]
					for row in reports.definition(report["name"])["filters"] if row["default"]
				})
				self.assertIsInstance(result["rows"], list)


class TestBranchIsReadable(FrappeTestCase):
	"""Every screen is branch-scoped; the people at a branch must be able to
	read the branch they work at."""

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_branch_employee_can_read_their_branch(self):
		self.assertTrue(frappe.has_permission("Branch", "read"))

	def test_but_cannot_change_it(self):
		self.assertFalse(frappe.has_permission("Branch", "write"))
