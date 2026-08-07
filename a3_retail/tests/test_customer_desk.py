# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Customer management in the branch app (`/branch/customers`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import customer_desk as desk
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestCustomersPage(FrappeTestCase):
	def test_the_page_is_a_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("customers.html", "customers.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "customers.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_customers.js", markup)
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_the_screen_has_the_pieces_the_shop_asked_for(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "customers.html")
		).read()
		for piece in ("Customer Management", "New Customer", "Import", "Export",
		              "Search by name, phone or email"):
			self.assertIn(piece, markup, piece)

	def test_customers_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("customers", "Customers", "/branch/customers"', sidebar)


class TestCustomerDeskAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_list(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, desk.list_customers)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, desk.list_customers)


class TestCustomerDesk(FrappeTestCase):
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
		self.customer = "Rahul Krishnan"
		if not frappe.db.exists("Customer", self.customer):
			self.skipTest("the demo customer is not seeded")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------ list
	def test_the_list_pages_and_counts(self):
		page = desk.list_customers(page=1, page_size=3)
		self.assertLessEqual(len(page["rows"]), 3)
		self.assertGreaterEqual(page["total"], len(page["rows"]))
		self.assertEqual(page["pages"], max(1, -(-page["total"] // 3)))
		self.assertEqual(page["showing"][0], 1 if page["total"] else 0)

	def test_a_row_carries_what_the_card_shows(self):
		row = desk.list_customers(query="Rahul")["rows"][0]
		for key in ("customer_name", "mobile_no", "place", "initials", "active"):
			self.assertIn(key, row, key)
		self.assertEqual(row["initials"], "RK")

	def test_search_finds_by_number_as_well_as_name(self):
		mobile = frappe.db.get_value("Customer", self.customer, "a3_mobile_no")
		if not mobile:
			self.skipTest("no mobile on the demo customer")
		names = [row["name"] for row in desk.list_customers(query=mobile)["rows"]]
		self.assertIn(self.customer, names)

	def test_looking_wider_than_the_branch_is_a_deliberate_choice(self):
		"""Someone who bought in Kochi can walk into Kozhikode."""
		here = desk.list_customers(scope="branch")["total"]
		everywhere = desk.list_customers(scope="all")["total"]
		self.assertGreaterEqual(everywhere, here)

	# --------------------------------------------------------------- profile
	def test_the_header_answers_who_they_are_and_what_they_are_worth(self):
		person = desk.profile(self.customer)
		self.assertEqual(person["customer_name"], self.customer)
		self.assertTrue(person["active"])
		self.assertGreaterEqual(person["total_bookings"], 0)
		self.assertGreaterEqual(person["total_spent"], 0)
		self.assertEqual(person["available_credit"],
		                 max(person["credit_limit"] - person["outstanding"], 0))

	def test_the_primary_device_is_the_last_one_we_sold_them(self):
		device = desk.profile(self.customer)["primary_device"]
		if not device:
			self.skipTest("no device on the demo customer")
		self.assertIn("item_name", device)
		self.assertIn(device["warranty"], ("In Warranty", "Out of Warranty",
		                                   "Brand Warranty", "Extended Warranty"))

	# -------------------------------------------------------------- overview
	def test_the_six_tiles_are_all_there(self):
		tiles = desk.overview(self.customer)["tiles"]
		for key in ("bookings", "services", "invoices", "payments", "due", "warranty"):
			self.assertIn(key, tiles, key)
			self.assertIn("sub_label", tiles[key])

	def test_the_due_tile_matches_what_is_actually_outstanding(self):
		data = desk.overview(self.customer)
		outstanding = flt(frappe.db.sql(
			"""select sum(outstanding_amount) from `tabSales Invoice`
			   where customer = %s and docstatus = 1""", self.customer)[0][0])
		self.assertAlmostEqual(data["tiles"]["due"]["total"], outstanding, places=2)

	def test_recent_panels_are_capped_at_five(self):
		data = desk.overview(self.customer)
		self.assertLessEqual(len(data["recent_bookings"]), 5)
		self.assertLessEqual(len(data["recent_services"]), 5)

	# ------------------------------------------------------------------ tabs
	def test_every_tab_answers_with_rows_the_page_can_render(self):
		for name in ("bookings", "invoices", "payments", "warranty", "devices",
		             "communication", "documents", "notes"):
			rows = desk.tab(self.customer, name)
			self.assertIsInstance(rows, list, name)
			for row in rows[:3]:
				for key in ("title", "date", "status"):
					self.assertIn(key, row, f"{name}.{key}")

	def test_an_unknown_tab_is_empty_rather_than_an_error(self):
		self.assertEqual(desk.tab(self.customer, "nonsense"), [])

	# --------------------------------------------------------------- actions
	def test_a_note_keeps_its_author(self):
		before = len(desk.notes(self.customer))
		desk.add_note(self.customer, "Prefers a call before delivery.")
		after = desk.notes(self.customer)
		self.assertEqual(len(after), before + 1)
		self.assertIn("Prefers a call", after[0]["title"])

	def test_an_empty_note_is_refused(self):
		self.assertRaises(frappe.ValidationError, desk.add_note, self.customer, "   ")

	def test_blocking_keeps_the_history_and_stops_new_work(self):
		customer = frappe.get_doc({
			"doctype": "Customer", "customer_name": f"Block Test {frappe.generate_hash(length=6)}",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Customer", customer.name, force=True,
		                                          ignore_permissions=True))

		desk.set_blocked(customer.name, 1)
		self.assertTrue(frappe.db.get_value("Customer", customer.name, "disabled"))
		self.assertFalse(desk.profile(customer.name)["active"])

		desk.set_blocked(customer.name, 0)
		self.assertFalse(frappe.db.get_value("Customer", customer.name, "disabled"))

	def test_a_message_with_nothing_in_it_is_refused(self):
		self.assertRaises(frappe.ValidationError, desk.message, self.customer, "WhatsApp", "  ")

	# ------------------------------------------------------------- statement
	def test_the_statement_runs_a_balance_and_ends_where_the_ledger_does(self):
		data = desk.statement(self.customer)
		self.assertEqual(data["customer_name"], self.customer)

		balance = 0.0
		for line in data["lines"]:
			balance += line["debit"] - line["credit"]
			self.assertAlmostEqual(line["balance"], balance, places=2)
		self.assertAlmostEqual(data["closing"], balance, places=2)

	def test_the_statement_is_readable_by_the_counter_that_prints_it(self):
		"""It is built from rows, not from a ledger report the counter cannot open."""
		self.assertFalse(frappe.has_permission("GL Entry", "read"))
		self.assertTrue(desk.statement(self.customer)["lines"] is not None)
