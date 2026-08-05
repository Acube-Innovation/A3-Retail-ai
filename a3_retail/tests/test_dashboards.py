# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Control tower, cards, charts, workspaces and the report register (step 25, scope 12)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, nowdate

from a3_retail.api import dashboard
from a3_retail.setup import dashboards, reports
from a3_retail.tests.fixtures import ensure_branch


class TestControlTowerContract(FrappeTestCase):
	"""Scope 12.1 — the payload the page is written against."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()
		cls.data = dashboard.control_tower()

	def test_every_section_is_present(self):
		for key in ("counters", "funnel", "tat", "job_cards", "parts", "delivery_delays",
		            "technician_load", "branches", "as_of"):
			self.assertIn(key, self.data, key)

	def test_counter_keys(self):
		for key in ("received_today", "ongoing", "awaiting_parts", "ready_for_delivery",
		            "delivered_today", "delayed", "service_revenue_today", "sales_revenue_today",
		            "footfall_today", "open_tickets"):
			self.assertIn(key, self.data["counters"], key)

	def test_the_funnel_lists_every_stage(self):
		statuses = [row["status"] for row in self.data["funnel"]]
		self.assertEqual(statuses, list(dashboard.FUNNEL_STATUSES))

	def test_tat_percentages_add_up(self):
		tat = self.data["tat"]
		if tat["delivered"]:
			self.assertAlmostEqual(tat["on_time"] + tat["breached"], 100, places=1)

	def test_job_board_rows_carry_a_flag(self):
		for row in self.data["job_cards"][:20]:
			self.assertIn(row["flag"], ("green", "amber", "red", "grey"), row["name"])

	def test_technician_load_reports_utilisation(self):
		for row in self.data["technician_load"]:
			self.assertGreaterEqual(row["capacity"], 1)
			self.assertGreaterEqual(row["utilisation"], 0)

	def test_a_branch_filter_drops_the_comparison_strip(self):
		data = dashboard.control_tower(branch="Kochi")
		self.assertEqual(data["branches"], [])
		self.assertEqual(data["branch"], "Kochi")

	def test_period_ranges(self):
		self.assertEqual(dashboard.period_range("today"), (nowdate(), nowdate()))
		week_start, week_end = dashboard.period_range("week")
		self.assertEqual(week_end, nowdate())
		self.assertLess(week_start, week_end)


class TestCounterCrossCheck(FrappeTestCase):
	"""Scope 12.8 — the tower and the raw SQL must agree."""

	def test_counters_match_the_validation_query(self):
		tower = dashboard.control_tower()["counters"]
		raw = dashboard.counter_cross_check()

		self.assertEqual(tower["received_today"], cint(raw["received_today"]))
		self.assertEqual(tower["ongoing"], cint(raw["wip"]))
		self.assertEqual(tower["ready_for_delivery"], cint(raw["ready"]))
		self.assertEqual(tower["delayed"], cint(raw["delayed"]))

	def test_the_branch_strip_sums_to_the_company_total(self):
		start, end = dashboard.period_range("today")
		strip = dashboard.branch_strip(start, end, use_cache=False)
		total = dashboard.counters(dashboard._visible_branches(None), start, end)
		self.assertEqual(sum(row["in"] for row in strip), total["received_today"])
		self.assertEqual(sum(row["wip"] for row in strip), total["ongoing"])


class TestFlagging(FrappeTestCase):
	def _row(self, **values):
		return frappe._dict({"status": "In Progress", "is_delayed": 0, "sla_due_on": None,
		                     "received_on": None, **values})

	def test_an_on_hold_card_is_grey(self):
		self.assertEqual(dashboard._flag(self._row(status="On Hold"), frappe.utils.now_datetime()),
		                 "grey")

	def test_a_delayed_card_is_red(self):
		self.assertEqual(dashboard._flag(self._row(is_delayed=1), frappe.utils.now_datetime()),
		                 "red")

	def test_a_fresh_card_is_green(self):
		now = frappe.utils.now_datetime()
		row = self._row(received_on=frappe.utils.add_to_date(now, hours=-1),
		                sla_due_on=frappe.utils.add_to_date(now, hours=+47))
		self.assertEqual(dashboard._flag(row, now), "green")

	def test_a_card_past_eighty_percent_of_tat_is_amber(self):
		now = frappe.utils.now_datetime()
		row = self._row(received_on=frappe.utils.add_to_date(now, hours=-9),
		                sla_due_on=frappe.utils.add_to_date(now, hours=+1))
		self.assertEqual(dashboard._flag(row, now), "amber")

	def test_a_card_past_its_due_time_is_red(self):
		now = frappe.utils.now_datetime()
		row = self._row(received_on=frappe.utils.add_to_date(now, hours=-10),
		                sla_due_on=frappe.utils.add_to_date(now, hours=-1))
		self.assertEqual(dashboard._flag(row, now), "red")


class TestCardsChartsWorkspaces(FrappeTestCase):
	def test_twenty_number_cards(self):
		self.assertEqual(len(dashboards.NUMBER_CARDS), 20)
		for label, *_rest in dashboards.NUMBER_CARDS:
			self.assertTrue(frappe.db.exists("Number Card", label), label)

	def test_fifteen_dashboard_charts(self):
		self.assertEqual(len(dashboards.DASHBOARD_CHARTS), 15)
		for name, *_rest in dashboards.DASHBOARD_CHARTS:
			self.assertTrue(frappe.db.exists("Dashboard Chart", name), name)

	def test_nine_workspaces(self):
		self.assertEqual(len(dashboards.WORKSPACES), 9)
		for label, *_rest in dashboards.WORKSPACES:
			self.assertTrue(frappe.db.exists("Workspace", label), label)

	def test_cards_and_charts_belong_to_the_dashboard_module(self):
		for doctype in ("Number Card", "Dashboard Chart"):
			rows = frappe.get_all(doctype, filters={"module": dashboards.MODULE}, pluck="name")
			self.assertGreaterEqual(len(rows), 15, doctype)

	def test_every_card_targets_an_installed_doctype(self):
		for name in frappe.get_all("Number Card", filters={"module": dashboards.MODULE},
		                           pluck="name"):
			doctype = frappe.db.get_value("Number Card", name, "document_type")
			self.assertTrue(frappe.db.exists("DocType", doctype), f"{name} -> {doctype}")

	def test_workspace_shortcuts_point_somewhere_real(self):
		for label, *_rest in dashboards.WORKSPACES:
			for shortcut in frappe.get_all("Workspace Shortcut", filters={"parent": label},
			                               fields=["type", "link_to"]):
				doctype = "Page" if shortcut.type == "Page" else "DocType"
				self.assertTrue(frappe.db.exists(doctype, shortcut.link_to),
				                f"{label}: {shortcut.link_to}")

	def test_the_control_tower_page_is_registered(self):
		self.assertTrue(frappe.db.exists("Page", "a3-control-tower"))


class TestReportRegister(FrappeTestCase):
	def test_forty_two_reports(self):
		names = reports.registered_reports()
		self.assertGreaterEqual(len(names), 42)

	def test_every_report_is_standard_and_scoped_to_a_module(self):
		for name in reports.registered_reports():
			row = frappe.db.get_value("Report", name, ["is_standard", "module", "ref_doctype",
			                                           "report_type"], as_dict=True)
			self.assertEqual(row.is_standard, "Yes", name)
			self.assertTrue(row.module.startswith("A3 Retail"), name)
			self.assertTrue(frappe.db.exists("DocType", row.ref_doctype), name)
			self.assertEqual(row.report_type, "Script Report", name)

	def test_every_report_grants_at_least_one_role(self):
		for name in reports.registered_reports():
			roles = frappe.get_all("Has Role", filters={"parent": name, "parenttype": "Report"},
			                       pluck="role")
			self.assertTrue(roles, name)

	def test_every_report_executes(self):
		result = reports.smoke_test(verbose=False)
		self.assertEqual(result["failed"], [])
		self.assertGreaterEqual(result["total"], 42)

	def test_no_report_is_slower_than_three_seconds(self):
		"""Scope 12.5 acceptance."""
		result = reports.smoke_test(verbose=False, slow_seconds=3.0)
		self.assertEqual(result["slow"], [])


class TestReportBranchScoping(FrappeTestCase):
	def test_the_branch_filter_narrows_the_result(self):
		from frappe.desk.query_report import run as run_report

		everything = run_report("Daily Service Register",
		                        filters={"from_date": "2026-01-01", "to_date": nowdate()},
		                        ignore_prepared_report=True)
		kochi = run_report("Daily Service Register",
		                   filters={"from_date": "2026-01-01", "to_date": nowdate(),
		                            "branch": "Kochi"},
		                   ignore_prepared_report=True)
		self.assertLessEqual(len(kochi["result"]), len(everything["result"]))
		for row in kochi["result"]:
			self.assertEqual(row.get("branch"), "Kochi")

	def test_permitted_branches_are_applied(self):
		from a3_retail.reporting import branch_conditions

		conditions, _values = branch_conditions(frappe._dict(branch="Kochi"), "jc")
		self.assertIn("jc.`branch` = %(branch)s", conditions)


class TestScheduledDelivery(FrappeTestCase):
	def test_ten_schedules_are_defined(self):
		self.assertEqual(len(reports.SCHEDULES), 10)

	def test_each_schedule_names_a_real_report(self):
		for report, *_rest in reports.SCHEDULES:
			self.assertTrue(frappe.db.exists("Report", report), report)

	def test_schedules_ship_disabled(self):
		enabled = frappe.get_all(
			"Auto Email Report",
			filters={"report": ["in", [row[0] for row in reports.SCHEDULES]], "enabled": 1},
			pluck="name",
		)
		self.assertFalse(enabled, f"scheduled reports enabled on install: {enabled}")

	def test_every_schedule_has_recipients(self):
		for name in frappe.get_all(
			"Auto Email Report",
			filters={"report": ["in", [row[0] for row in reports.SCHEDULES]]}, pluck="name"
		):
			self.assertTrue(frappe.db.get_value("Auto Email Report", name, "email_to"), name)


class TestIndexes(FrappeTestCase):
	"""Scope 12.1 — the counters assume these exist."""

	def _indexes(self, doctype: str) -> set:
		rows = frappe.db.sql(f"show index from `tab{doctype}`", as_dict=True)
		return {row["Key_name"] for row in rows}

	def test_job_card_branch_indexes(self):
		names = self._indexes("Service Job Card")
		self.assertTrue(any("branch" in name for name in names), names)

	def test_sales_invoice_branch_index(self):
		names = self._indexes("Sales Invoice")
		self.assertTrue(any("branch" in name for name in names), names)
