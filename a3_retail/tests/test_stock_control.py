# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Branch Stock Control (`/branch/stock`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import stock_control as stock
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestStockPage(FrappeTestCase):
	def test_the_page_is_one_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("stock.html", "stock.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "stock.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_stock.js", markup)
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_every_operation_is_on_the_one_screen(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "stock.html")
		).read()
		for piece in ("Request Stock", "Request Procurement", "Move Stock", "Receive Stock",
		              "Stock Adjustment", "Live Stock", "Stock Alerts", "Recent Activity"):
			self.assertIn(piece, markup, piece)
		for tab in ("overview", "purchases", "requests", "transfers", "receipts", "movements",
		            "adjustments", "reservations", "service", "devices"):
			self.assertIn(f'("{tab}"', markup, tab)

	def test_stock_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("stock", "Stock", "/branch/stock"', sidebar)

	def test_the_page_prints_through_the_application(self):
		"""No browser-only print layout for stock documents."""
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js")).read()
		self.assertIn("stock_control.print_url", body)
		self.assertNotIn("window.open(\"\", \"_blank\")", body)


class TestStockAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_shelf(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, stock.live_stock)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, stock.bootstrap)


class TestStockReads(FrappeTestCase):
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

	def test_the_page_starts_with_the_branch_and_what_it_may_do(self):
		boot = stock.bootstrap()
		self.assertEqual(boot["branch"], "Kochi")
		self.assertTrue(boot["warehouses"])
		for key in ("request", "approve", "transfer", "adjust", "procure"):
			self.assertIn(key, boot["can"], key)

	def test_live_stock_is_this_branch_s_own_shelves(self):
		mine = set(stock.bootstrap()["warehouses"])
		for row in stock.live_stock({}, page_size=50)["rows"]:
			self.assertIn(row["warehouse"], mine, row["item_code"])

	def test_a_row_carries_what_the_table_shows(self):
		rows = stock.live_stock({}, page_size=5)["rows"]
		if not rows:
			self.skipTest("no stock in this branch")
		for key in ("item_code", "item_name", "warehouse", "available", "reserved_qty",
		            "incoming", "reorder_level", "status", "branches", "has_serial"):
			self.assertIn(key, rows[0], key)

	def test_available_is_what_is_on_the_shelf_less_what_is_spoken_for(self):
		for row in stock.live_stock({}, page_size=20)["rows"]:
			self.assertAlmostEqual(
				row["available"], flt(row["actual_qty"]) - flt(row["reserved_qty"]), places=3
			)

	def test_status_follows_the_quantity(self):
		for row in stock.live_stock({}, page_size=50)["rows"]:
			if row["available"] <= 0:
				self.assertIn(row["status"], ("Out of Stock", "Incoming"), row["item_code"])
			elif row["available"] <= max(flt(row["reorder_level"]), stock.LOW_STOCK_FLOOR):
				self.assertEqual(row["status"], "Low Stock", row["item_code"])
			else:
				self.assertEqual(row["status"], "Healthy", row["item_code"])

	def test_the_cards_answer_to_the_same_filters_as_the_table(self):
		cards = stock.kpis({"item_group": "Spare Parts"})
		listed = stock.live_stock({"item_group": "Spare Parts"}, page_size=100)
		self.assertEqual(cards["items"]["value"],
		                 len({row["item_code"] for row in listed["rows"]}))

	def test_the_network_view_covers_every_branch_holding_it(self):
		rows = stock.live_stock({}, page_size=5)["rows"]
		if not rows:
			self.skipTest("no stock in this branch")

		data = stock.network(rows[0]["item_code"])
		self.assertEqual(data["branch"], "Kochi")
		self.assertTrue(data["branches"])
		self.assertTrue(any(branch["is_mine"] for branch in data["branches"]))
		self.assertTrue(data["recommendation"])

	def test_every_tab_answers_with_rows_the_page_can_render(self):
		for name in ("overview", "purchases", "requests", "transfers", "receipts", "movements",
		             "adjustments", "reservations", "service", "devices"):
			data = stock.tab(name)
			self.assertIsInstance(data, dict, name)
			self.assertTrue("rows" in data or "panels" in data, name)

	def test_alerts_and_activity_read_from_the_ledger(self):
		for alert in stock.alerts():
			self.assertTrue(alert["text"])
			self.assertTrue(alert.get("filter") or alert.get("tab"), alert["text"])
		for row in stock.activity(5):
			self.assertTrue(row["reference"])


class TestStockActions(FrappeTestCase):
	"""Every action writes an ERPNext document — that is what is asserted here."""

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
		self.branch = "Kochi"

	def tearDown(self):
		frappe.set_user("Administrator")

	def _other_branch(self) -> str | None:
		"""A branch that actually has a shelf to send from."""
		for branch in frappe.get_all("Branch", filters={"name": ["!=", self.branch]}, pluck="name"):
			if frappe.get_all("Warehouse", filters={"custom_branch": branch, "disabled": 0},
			                  limit=1):
				return branch
		return None

	def test_a_request_is_a_stock_request_document(self):
		other = self._other_branch()
		if not other:
			self.skipTest("only one branch")

		result = stock.create_request({
			"source_branch": other, "priority": "Normal", "purpose": "Stock Balancing",
			"items": [{"item_code": "ACC-TGL-A55", "qty": 2}],
		})
		doc = frappe.get_doc("Stock Request", result["request"])
		self.assertEqual(doc.requesting_branch, self.branch)
		self.assertEqual(doc.source_branch, other)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(flt(doc.items[0].qty), 2)

	def test_a_branch_with_no_shelf_is_named_rather_than_failing_blank(self):
		empty = next((branch for branch in frappe.get_all(
			"Branch", filters={"name": ["!=", self.branch]}, pluck="name")
			if not frappe.get_all("Warehouse", filters={"custom_branch": branch, "disabled": 0},
			                      limit=1)), None)
		if not empty:
			self.skipTest("every branch has a warehouse")

		with self.assertRaises(frappe.ValidationError) as caught:
			stock.create_request({"source_branch": empty,
			                      "items": [{"item_code": "ACC-TGL-A55", "qty": 1}]})
		self.assertIn(empty, str(caught.exception))

	def test_a_request_with_nothing_in_it_is_refused(self):
		other = self._other_branch()
		if not other:
			self.skipTest("only one branch")
		self.assertRaises(frappe.ValidationError, stock.create_request,
		                  {"source_branch": other, "items": []})

	def test_another_branch_s_request_is_not_this_branch_s_to_handle(self):
		foreign = frappe.db.get_value("Stock Request", {
			"source_branch": ["!=", self.branch], "requesting_branch": ["!=", self.branch],
			"docstatus": 1}, "name")
		if not foreign:
			self.skipTest("no request outside this branch")
		self.assertRaises(frappe.ValidationError, stock.approve_request, foreign)

	def test_a_rejection_needs_a_reason(self):
		pending = frappe.db.get_value("Stock Request", {
			"source_branch": self.branch, "status": "Pending Approval", "docstatus": 1}, "name")
		if not pending:
			self.skipTest("nothing pending on this branch")
		self.assertRaises(frappe.ValidationError, stock.reject_request, pending, "   ")

	def test_an_internal_move_is_a_submitted_stock_entry(self):
		warehouses = stock.bootstrap()["warehouses"]
		if len(warehouses) < 2:
			self.skipTest("this branch has one warehouse")

		source = next((w for w in warehouses if stock._available("ACC-TGL-A55", w) >= 2), None)
		if not source:
			self.skipTest("no warehouse holds enough to move")
		target = next(w for w in warehouses if w != source)

		before = stock._available("ACC-TGL-A55", target)
		result = stock.move_stock({
			"source": source, "target": target, "remarks": "test move",
			"items": [{"item_code": "ACC-TGL-A55", "qty": 1}],
		})

		entry = frappe.get_doc("Stock Entry", result["stock_entry"])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.purpose, "Material Transfer")
		self.assertEqual(entry.items[0].s_warehouse, source)
		self.assertEqual(entry.items[0].t_warehouse, target)
		self.assertAlmostEqual(stock._available("ACC-TGL-A55", target), before + 1, places=3)

	def test_moving_more_than_there_is_says_so_plainly(self):
		warehouses = stock.bootstrap()["warehouses"]
		if len(warehouses) < 2:
			self.skipTest("this branch has one warehouse")

		with self.assertRaises(frappe.ValidationError) as caught:
			stock.move_stock({
				"source": warehouses[0], "target": warehouses[1],
				"items": [{"item_code": "ACC-TGL-A55", "qty": 999999}],
			})
		self.assertIn("available", str(caught.exception).lower())

	def test_a_move_outside_this_branch_is_refused(self):
		foreign = frappe.db.get_value("Warehouse", {
			"custom_branch": ["not in", [self.branch, ""]], "disabled": 0}, "name")
		if not foreign:
			self.skipTest("no warehouse outside this branch")

		self.assertRaises(frappe.ValidationError, stock.move_stock, {
			"source": stock.bootstrap()["warehouses"][0], "target": foreign,
			"items": [{"item_code": "ACC-TGL-A55", "qty": 1}],
		})

	def test_an_adjustment_needs_a_reason(self):
		warehouse = stock.bootstrap()["warehouses"][0]
		self.assertRaises(frappe.ValidationError, stock.adjust_stock, {
			"warehouse": warehouse, "reason": "  ",
			"items": [{"item_code": "ACC-TGL-A55", "counted": 1}],
		})

	def test_an_adjustment_that_changes_nothing_says_so(self):
		warehouse = stock.bootstrap()["warehouses"][0]
		counted = stock._available("ACC-TGL-A55", warehouse)

		with self.assertRaises(frappe.ValidationError) as caught:
			stock.adjust_stock({
				"warehouse": warehouse, "reason": "Counted at close of day",
				"items": [{"item_code": "ACC-TGL-A55", "counted": counted}],
			})
		self.assertIn("nothing to adjust", str(caught.exception).lower())

	def test_an_adjustment_is_a_stock_reconciliation(self):
		warehouse = stock.bootstrap()["warehouses"][0]
		counted = stock._available("ACC-TGL-A55", warehouse)
		if counted <= 0:
			self.skipTest("nothing on this shelf to count")

		# Put the shelf back exactly as it was found, whatever this test does.
		self.addCleanup(lambda: stock.adjust_stock({
			"warehouse": warehouse, "reason": "Restoring after the test",
			"items": [{"item_code": "ACC-TGL-A55", "counted": counted}],
		}))

		result = stock.adjust_stock({
			"warehouse": warehouse, "reason": "Counted at close of day",
			"items": [{"item_code": "ACC-TGL-A55", "counted": counted + 1}],
		})
		doc = frappe.get_doc("Stock Reconciliation", result["adjustment"])
		self.assertEqual(doc.docstatus, 1)
		self.assertIn("Counted at close", doc.remarks)
		self.assertAlmostEqual(stock._available("ACC-TGL-A55", warehouse), counted + 1, places=3)

	def test_procurement_is_a_material_request(self):
		result = stock.request_procurement({
			"items": [{"item_code": "ACC-TGL-A55", "qty": 5}],
			"reason": "Nothing in the network",
		})
		doc = frappe.get_doc("Material Request", result["material_request"])
		self.assertEqual(doc.material_request_type, "Purchase")
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(flt(doc.items[0].qty), 5)

	def test_nothing_here_writes_a_quantity_by_hand(self):
		"""Stock moves through documents, never through a field update."""
		body = open(frappe.get_app_path("a3_retail", "api", "stock_control.py")).read()
		for forbidden in ("actual_qty\"", "set_value(\"Bin\"", "projected_qty\"", "stock_value\""):
			self.assertNotIn(f'db_set({forbidden}', body, forbidden)
		self.assertNotIn('frappe.db.set_value("Bin"', body)

	def test_the_print_route_is_the_application_s_own(self):
		url = stock.print_url("Stock Request", "SR-KCH-26-0001")
		self.assertIn("frappe.utils.print_format.download_pdf", url)
		self.assertIn("doctype=Stock+Request", url)


class TestTransferLifecycle(FrappeTestCase):
	"""Approve, dispatch, receive — the two legs ERPNext expects."""

	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _incoming_request(self) -> str | None:
		"""A request this branch made, that another branch has approved."""
		return frappe.db.get_value("Stock Request", {
			"requesting_branch": "Kochi", "status": "Approved", "docstatus": 1}, "name")

	def test_a_transfer_cannot_be_received_before_it_is_sent(self):
		waiting = self._incoming_request()
		if not waiting:
			self.skipTest("nothing approved and heading here")
		self.assertRaises(frappe.ValidationError, stock.receive_request, waiting, {})

	def test_receiving_more_than_was_sent_is_refused(self):
		in_transit = frappe.db.get_value("Stock Request", {
			"requesting_branch": "Kochi", "status": "In Transit", "docstatus": 1}, "name")
		if not in_transit:
			self.skipTest("nothing in transit to this branch")

		row = frappe.get_all("Stock Request Item", filters={"parent": in_transit},
		                     fields=["item_code", "qty"], limit=1)[0]
		self.assertRaises(
			frappe.ValidationError, stock.receive_request, in_transit,
			{row.item_code: flt(row.qty) + 5},
		)

	def test_a_short_receipt_has_to_be_explained(self):
		in_transit = frappe.db.get_value("Stock Request", {
			"requesting_branch": "Kochi", "status": "In Transit", "docstatus": 1}, "name")
		if not in_transit:
			self.skipTest("nothing in transit to this branch")

		row = frappe.get_all("Stock Request Item", filters={"parent": in_transit},
		                     fields=["item_code", "qty"], limit=1)[0]
		if flt(row.qty) <= 1:
			self.skipTest("cannot be short of one")

		with self.assertRaises(frappe.ValidationError) as caught:
			stock.receive_request(in_transit, {row.item_code: flt(row.qty) - 1})
		self.assertIn("differs", str(caught.exception).lower())
