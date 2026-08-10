# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Counter billing in the branch app (`/retail/sales`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import pos
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestSalesPage(FrappeTestCase):
	def test_the_page_is_a_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("sales.html", "sales.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "sales.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_pos.js", markup)

	def test_the_counter_has_its_six_quick_actions(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "sales.html")
		).read()
		for action, label, shortcut in [
			("recent", "Recent Bills", "F3"), ("hold", "Hold Bill", "F4"),
			("clear", "Clear Cart", "F5"), ("drafts", "Drafts", "F6"),
			("loyalty", "Loyalty", "F7"), ("price", "Price Check", "F8"),
		]:
			self.assertIn(f'("{action}", "{label}", "{shortcut}"', markup, action)
		for key in ("F3", "F4", "F5", "F6", "F7", "F8", "F9"):
			self.assertIn(key, markup, key)

	def test_sales_is_in_the_sidebar_under_dashboard(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "retail"), "_sidebar.html")
		).read()
		self.assertLess(sidebar.index("/retail/dashboard"), sidebar.index("/retail/sales"))


class TestCounterAccess(FrappeTestCase):
	def test_a_guest_cannot_open_the_catalogue(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, pos.catalogue)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, pos.catalogue)


class TestCatalogue(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_items_carry_this_branch_quantity_and_a_price(self):
		rows = pos.catalogue(only_in_stock=1, limit=10)
		self.assertTrue(rows)
		for row in rows:
			self.assertIn("branch_qty", row)
			self.assertIn("rate", row)
			self.assertTrue(row["sellable"])

	def test_prices_come_from_a_real_price_list(self):
		rows = [row for row in pos.catalogue(query="iPhone") if row["item_code"].startswith("MOB")]
		self.assertTrue(rows)
		self.assertGreater(flt(rows[0]["rate"]), 0, "the catalogue must not price at zero")

	def test_fixed_assets_are_not_for_sale(self):
		codes = [row["item_code"] for row in pos.catalogue(limit=60)]
		self.assertFalse([code for code in codes if code.startswith("FA-")])

	def test_rows_carry_what_the_bill_needs_to_preview_tax(self):
		rows = pos.catalogue(only_in_stock=1, limit=5)
		for row in rows:
			self.assertIn("gst_rate", row)
			self.assertGreater(flt(row["gst_rate"]), 0)
			self.assertIn("low_stock", row)
			self.assertIn("is_new", row)

	def test_new_is_not_everything(self):
		"""A freshly seeded site would badge the whole catalogue on creation date."""
		rows = pos.catalogue(limit=60)
		flagged = [row for row in rows if row["is_new"]]
		self.assertLess(len(flagged), len(rows))

	def test_devices_are_flagged_so_the_counter_asks_for_an_imei(self):
		rows = pos.catalogue(query="iPhone")
		self.assertTrue(rows)
		self.assertTrue(rows[0]["is_device"])
		self.assertTrue(rows[0]["has_serial"])

	def test_search_narrows_the_list(self):
		everything = pos.catalogue(limit=60)
		narrowed = pos.catalogue(query="Redmi", limit=60)
		self.assertLess(len(narrowed), len(everything))

	def test_serials_are_from_this_branch_only(self):
		rows = pos.serials("MOB-APL-15-128-BLK")
		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(
				frappe.db.get_value("Warehouse", row["warehouse"], "custom_branch"), "Kochi"
			)

	def test_stock_elsewhere_marks_my_own_branch(self):
		rows = pos.stock_elsewhere("MOB-SAM-A55-8-128-BLU")
		self.assertTrue(rows)
		mine = [row for row in rows if row["is_mine"]]
		self.assertTrue(all(row["branch"] == "Kochi" for row in mine))


class TestScanning(FrappeTestCase):
	"""The search box doubles as the scanner."""

	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_an_imei_resolves_to_its_handset(self):
		serial = pos.serials("MOB-APL-15-128-BLK", limit=1)
		if not serial:
			self.skipTest("no serial in stock")

		imei = frappe.db.get_value("Serial No", serial[0]["serial_no"], "a3_imei_1")
		found = pos.scan(imei or serial[0]["serial_no"])

		self.assertEqual(found["kind"], "serial")
		self.assertEqual(found["serial_no"], serial[0]["serial_no"])
		self.assertEqual(found["item"]["item_code"], "MOB-APL-15-128-BLK")

	def test_an_item_code_resolves_to_the_item(self):
		found = pos.scan("ACC-TGL-A55")
		self.assertEqual(found["kind"], "item")
		self.assertEqual(found["item"]["item_code"], "ACC-TGL-A55")

	def test_nonsense_finds_nothing(self):
		self.assertIsNone(pos.scan("no-such-code-at-all"))

	def test_an_empty_scan_is_ignored(self):
		self.assertIsNone(pos.scan(""))


class TestPaymentTiles(FrappeTestCase):
	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_all_six_tiles_map_to_a_real_mode_of_payment(self):
		tiles = pos.payment_tiles()
		self.assertEqual(len(tiles), 6)
		for tile in tiles:
			self.assertTrue(tile["available"], tile["tile"])
			self.assertTrue(frappe.db.exists("Mode of Payment", tile["mode"]), tile)


class TestCustomerAtTheCounter(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_known_number_returns_the_customer_and_their_history(self):
		found = pos.find_customer("9847012345")
		self.assertIsNotNone(found)
		self.assertIn("history", found)
		self.assertIn("invoices", found["history"])

	def test_an_unknown_number_returns_nothing(self):
		self.assertIsNone(pos.find_customer("9000000001"))

	def test_a_short_number_is_not_a_lookup(self):
		self.assertIsNone(pos.find_customer("98470"))

	def test_saving_a_customer_stores_the_address(self):
		saved = pos.save_customer(
			mobile_no="9846500011", customer_name="Counter Test Customer",
			address_line1="Palarivattom", city="Kochi", pincode="682025",
		)
		self.assertTrue(saved["name"])
		self.assertEqual(saved["address"]["address_line1"], "Palarivattom")


class TestCheckout(FrappeTestCase):
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

	def _serial(self, item_code="MOB-APL-15-128-BLK") -> str:
		rows = pos.serials(item_code, limit=1)
		if not rows:
			self.skipTest(f"no serial in stock for {item_code}")
		return rows[0]["serial_no"]

	def test_an_empty_cart_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, pos.checkout, {"customer": "Rahul Krishnan", "items": []}
		)

	def test_a_bill_without_a_customer_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, pos.checkout,
			{"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299}]},
		)

	def test_a_device_without_its_imei_is_refused(self):
		"""Step 12 P1 — the guard is in the invoice, not the screen."""
		self.assertRaises(
			frappe.ValidationError, pos.checkout,
			{"customer": "Rahul Krishnan",
			 "items": [{"item_code": "MOB-APL-15-128-BLK", "qty": 1, "rate": 69900, "serials": []}]},
		)

	def test_a_sale_produces_a_submitted_invoice_with_gst(self):
		result = pos.checkout(
			{
				"customer": "Rahul Krishnan",
				"mode_of_payment": "Cash",
				"items": [
					{"item_code": "MOB-APL-15-128-BLK", "qty": 1, "rate": 69900,
					 "serials": [self._serial()]},
					{"item_code": "ACC-CHG-25W-TC", "qty": 1, "rate": 1499, "serials": []},
				],
			}
		)

		invoice = frappe.get_doc("Sales Invoice", result["invoice"])
		self.assertEqual(invoice.docstatus, 1)
		self.assertEqual(invoice.branch, "Kochi")
		self.assertEqual(invoice.owner, frappe.session.user)
		self.assertGreater(flt(invoice.total_taxes_and_charges), 0, "the bill carries no GST")
		self.assertTrue(invoice.taxes_and_charges)

	def test_the_bill_carries_the_imei_and_the_sales_person(self):
		result = pos.checkout(
			{
				"customer": "Rahul Krishnan",
				"items": [{"item_code": "MOB-APL-15-128-BLK", "qty": 1, "rate": 69900,
				           "serials": [self._serial()]}],
			}
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])

		self.assertTrue(invoice.items[0].serial_no, "no IMEI on the invoice line")
		self.assertTrue(invoice.sales_team, "no sales person — incentives could not be attributed")

	def test_the_sale_lands_in_the_branch_cost_center(self):
		result = pos.checkout(
			{"customer": "Rahul Krishnan",
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 2, "rate": 299, "serials": []}]}
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])
		self.assertIn("Kochi", invoice.cost_center or "")

	def test_a_discount_reaches_the_invoice(self):
		result = pos.checkout(
			{"customer": "Rahul Krishnan", "discount_percent": 10, "notes": "Counter discount",
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 10, "rate": 299, "serials": []}]}
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])
		self.assertEqual(flt(invoice.additional_discount_percentage), 10)
		self.assertLess(flt(invoice.base_net_total), 2990)
		self.assertIn("Counter discount", invoice.remarks or "")

	def test_cash_above_the_bill_is_recorded_as_change(self):
		result = pos.checkout(
			{"customer": "Rahul Krishnan", "mode_of_payment": "Cash", "received_amount": 5000,
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}]}
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])

		self.assertEqual(len(invoice.payments), 1, "the tender was counted twice")
		self.assertEqual(flt(invoice.paid_amount), 5000)
		# ERPNext rounds cash change to the rupee, which is what a drawer does.
		self.assertAlmostEqual(
			flt(invoice.change_amount), 5000 - flt(invoice.grand_total), delta=1
		)
		self.assertAlmostEqual(flt(result["change"]), flt(invoice.change_amount), places=2)

	def test_a_card_is_charged_the_bill_not_the_typed_amount(self):
		"""Only a drawer gives change. A card must not submit an over-paid invoice."""
		result = pos.checkout(
			{"customer": "Rahul Krishnan", "mode_of_payment": "Card", "received_amount": 5000,
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}]}
		)
		invoice = frappe.get_doc("Sales Invoice", result["invoice"])

		payable = flt(invoice.rounded_total) or flt(invoice.grand_total)
		self.assertEqual(flt(invoice.paid_amount), payable)
		self.assertEqual(flt(invoice.outstanding_amount), 0)
		self.assertEqual(flt(result["change"]), 0)

	def test_the_result_hands_back_a_print_link(self):
		result = pos.checkout(
			{"customer": "Rahul Krishnan",
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}]}
		)
		self.assertIn("download_pdf", result["print_url"])
		self.assertIn(result["invoice"], result["print_url"])

	def test_todays_bills_come_back_for_reprinting(self):
		pos.checkout(
			{"customer": "Rahul Krishnan",
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}]}
		)
		recent = pos.recent_invoices()
		self.assertTrue(recent)
		self.assertIn("print_url", recent[0])


class TestCounterPermissions(FrappeTestCase):
	"""The permissions the counter needs, and the ones it must still not have."""

	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_seller_may_read_serial_numbers(self):
		self.assertTrue(frappe.has_permission("Serial No", "read"))

	def test_a_seller_may_create_a_customer_and_an_address(self):
		self.assertTrue(frappe.has_permission("Customer", "create"))
		self.assertTrue(frappe.has_permission("Address", "create"))

	def test_the_chart_of_accounts_stays_closed(self):
		"""Scope 11.1 — select-only is what lets an invoice price itself."""
		self.assertFalse(frappe.has_permission("Account", "read"))
		self.assertTrue(frappe.only_has_select_perm("Account"))

	def test_the_ledger_stays_closed(self):
		self.assertFalse(frappe.has_permission("GL Entry", "read"))
		self.assertFalse(frappe.has_permission("Journal Entry", "read"))
