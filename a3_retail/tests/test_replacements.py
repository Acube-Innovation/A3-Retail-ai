# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Replace on a bill — and the accessory road, to our own godown."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from a3_retail.api import replacements
from a3_retail.tests.fixtures import ensure_branch, ensure_customer, ensure_stock

ACCESSORY = "ACC-TGL-A55"


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestTheAccessoryRoad(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		self.branch = ensure_branch("Kochi", "KCH")
		self.shelf = self.branch.default_warehouse
		ensure_stock(ACCESSORY, self.shelf, qty=5)
		self.bill = self._accessory_bill()
		others = [g["warehouse"] for g in replacements._godowns() if g["warehouse"] != self.shelf]
		if not others:
			self.skipTest("no other warehouse to act as the godown")
		self.godown = others[0]
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _accessory_bill(self) -> str:
		doc = frappe.new_doc("Sales Invoice")
		doc.customer = ensure_customer()
		doc.company = self.branch.company
		doc.branch = self.branch.branch
		doc.set_warehouse = self.shelf
		doc.update_stock = 1
		doc.append("items", {"item_code": ACCESSORY, "qty": 1, "rate": 299,
		                     "warehouse": self.shelf})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def _swap(self, **changes) -> dict:
		return replacements.replace({
			"invoice": self.bill, "item_code": ACCESSORY, "qty": 1, "route": "godown",
			"godown": self.godown, "reason": "Cracked out of the box", "date": nowdate(),
			**changes,
		})

	def test_an_accessory_starts_on_the_godown_road(self):
		options = replacements.options(self.bill)
		line = next(row for row in options["lines"] if row["item_code"] == ACCESSORY)
		self.assertEqual(line["route"], "godown")
		self.assertTrue(options["godowns"])

	def test_the_godowns_are_our_own_working_shelves(self):
		for row in replacements._godowns():
			warehouse = frappe.db.get_value("Warehouse", row["warehouse"],
			                                ["is_group", "disabled", "warehouse_type"],
			                                as_dict=True)
			self.assertFalse(warehouse.is_group, row["warehouse"])
			self.assertFalse(warehouse.disabled, row["warehouse"])
			self.assertNotEqual(warehouse.warehouse_type, "Transit", row["warehouse"])

	def test_the_faulty_one_goes_into_the_godown_and_the_good_one_off_the_shelf(self):
		out = self._swap()
		self.assertEqual(out["route"], "godown")
		self.assertIsNone(out["debit_note"])
		self.assertIsNone(out["purchase"])

		credit = frappe.get_doc("Sales Invoice", out["credit_note"])
		self.assertTrue(credit.is_return)
		self.assertEqual(credit.items[0].warehouse, self.godown)
		came_back = frappe.get_all("Stock Ledger Entry", fields=["warehouse", "actual_qty"],
		                           filters={"voucher_no": credit.name, "is_cancelled": 0})
		self.assertEqual([(row.warehouse, flt(row.actual_qty)) for row in came_back],
		                 [(self.godown, 1.0)])

		went_out = frappe.get_all("Stock Ledger Entry", fields=["warehouse", "actual_qty"],
		                          filters={"voucher_no": out["sale"], "is_cancelled": 0})
		self.assertEqual([(row.warehouse, flt(row.actual_qty)) for row in went_out],
		                 [(self.shelf, -1.0)])

		# Nobody owes anybody anything for a swap.
		for invoice in (out["credit_note"], out["sale"]):
			self.assertAlmostEqual(
				flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), 0, 2)

	def test_a_swap_with_no_godown_is_refused(self):
		self.assertRaises(frappe.ValidationError, self._swap, godown="")

	def test_a_warehouse_that_is_not_ours_is_refused(self):
		self.assertRaises(frappe.ValidationError, self._swap, godown="Nowhere - XX")

	def test_an_unknown_road_is_refused(self):
		self.assertRaises(frappe.ValidationError, self._swap, route="sideways")


class TestTheReplaceWindow(FrappeTestCase):
	def test_the_window_offers_both_roads(self):
		markup = open(os.path.join(frappe.get_app_path("a3_retail", "www", "retail"),
		                           "invoice.html")).read()
		self.assertIn('data-route="supplier"', markup)
		self.assertIn('data-route="godown"', markup)
		self.assertIn('id="rp-godown"', markup)

	def test_the_window_sends_the_road_and_the_godown(self):
		script = open(frappe.get_app_path("a3_retail", "public", "js", "a3_invoice.js")).read()
		self.assertIn("route: route", script)
		self.assertIn('godown: route === "godown" ? $("rp-godown").value : ""', script)

	def test_the_godown_it_starts_on_is_a_setting(self):
		meta = frappe.get_meta("A3 Retail Settings")
		self.assertEqual(meta.get_field("faulty_accessory_warehouse").options, "Warehouse")
		patches = open(frappe.get_app_path("a3_retail", "patches.txt")).read()
		self.assertIn("a3_retail.patches.warranty_returns_shelf", patches)
