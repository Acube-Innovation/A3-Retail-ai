# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Branch purchase entry (`/retail/purchases`) — the supplier bill that brings
stock in."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import purchases
from a3_retail.tests.fixtures import ensure_branch, ensure_stock


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestPurchasesPage(FrappeTestCase):
	def test_the_page_is_a_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("purchases.html", "purchases.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "purchases.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_purchases.js", markup)

	def test_recording_one_is_a_screen_of_its_own(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("purchase_entry.html", "purchase_entry.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		entry = open(os.path.join(folder, "purchase_entry.html")).read()
		self.assertIn("/assets/a3_retail/js/a3_purchase_entry.js", entry)
		# the supplier and the item are both addable without leaving the page
		self.assertIn('id="supplier-new"', entry)
		self.assertIn('id="item-new"', entry)
		self.assertIn('id="s-gstin"', entry)

		# and the list hands off to it rather than opening a dialog
		listing = open(os.path.join(folder, "purchases.html")).read()
		self.assertIn("/retail/purchase_entry", listing)
		self.assertNotIn('id="purchase-modal"', listing)

	def test_the_menu_offers_it(self):
		sidebar = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "_sidebar.html")).read()
		self.assertIn("/retail/purchases", sidebar)


class TestBranchPurchases(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		profile = ensure_branch("Kochi", "KCH")
		cls.branch = "Kochi"
		cls.warehouse = profile.default_warehouse
		ensure_stock("ACC-TGL-A55", cls.warehouse, qty=5, rate=200)
		frappe.db.commit()

	def setUp(self):
		user = user_for("Kochi Manager")
		if not user:
			self.skipTest("Kochi Manager is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _supplier(self) -> str:
		return purchases.create_supplier("Kochi Distributors", "9400000001")["name"]

	def _qty(self) -> float:
		return flt(frappe.db.get_value(
			"Bin", {"item_code": "ACC-TGL-A55", "warehouse": self.warehouse}, "actual_qty"))

	def test_a_purchase_brings_the_goods_into_the_branch_store(self):
		before = self._qty()
		result = purchases.create({
			"supplier": self._supplier(),
			"bill_no": "KD/2026/41",
			"items": [{"item_code": "ACC-TGL-A55", "qty": 10, "rate": 150}],
		})

		invoice = frappe.get_doc("Purchase Invoice", result["purchase"])
		self.assertEqual(invoice.docstatus, 1)
		self.assertEqual(invoice.update_stock, 1)
		self.assertEqual(self._qty(), before + 10)

	def test_an_unpaid_bill_stays_on_the_suppliers_account(self):
		result = purchases.create({
			"supplier": self._supplier(),
			"items": [{"item_code": "ACC-TGL-A55", "qty": 2, "rate": 150}],
		})
		self.assertGreater(result["outstanding"], 0)

	def test_paying_the_rep_settles_the_bill(self):
		result = purchases.create({
			"supplier": self._supplier(),
			"items": [{"item_code": "ACC-TGL-A55", "qty": 2, "rate": 150}],
			"paid_amount": 300,
			"mode_of_payment": "Cash",
		})
		self.assertEqual(
			flt(frappe.db.get_value("Purchase Invoice", result["purchase"], "outstanding_amount")),
			0,
		)

	def test_paying_more_than_the_bill_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			purchases.create({
				"supplier": self._supplier(),
				"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 150}],
				"paid_amount": 5000,
				"mode_of_payment": "Cash",
			})

	def test_a_purchase_with_no_lines_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			purchases.create({"supplier": self._supplier(), "items": []})

	def test_a_purchase_without_a_supplier_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			purchases.create({"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 150}]})

	def test_a_future_dated_purchase_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			purchases.create({
				"supplier": self._supplier(),
				"date": frappe.utils.add_days(frappe.utils.nowdate(), 3),
				"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 150}],
			})

	def test_a_gstin_gives_up_its_state_without_the_api(self):
		"""The first two digits are the state code, so that much always works."""
		info = purchases.gstin_info("32BOTPV1014F1Z0")
		self.assertEqual(info["gstin"], "32BOTPV1014F1Z0")
		self.assertEqual(info["state"], "Kerala")

	def test_a_mistyped_gstin_is_refused(self):
		with self.assertRaises(Exception):
			purchases.gstin_info("NOTAGSTIN")

	def test_a_supplier_already_on_file_is_reused_not_duplicated(self):
		first = purchases.create_supplier("Kochi Distributors", "9400000001")
		again = purchases.create_supplier("Kochi Distributors", "9400000001")
		self.assertEqual(first["name"], again["name"])
		self.assertFalse(again["created"])

	def test_the_list_answers_for_this_branch(self):
		purchases.create({
			"supplier": self._supplier(),
			"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 150}],
		})
		data = purchases.recent()
		self.assertEqual(data["branch"], self.branch)
		self.assertTrue(data["rows"])
