# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Cash and bank for one branch (`/retail/cashbank`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import cashbank
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestCashBankPage(FrappeTestCase):
	def test_the_page_is_a_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "retail")
		for name in ("cashbank.html", "cashbank.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "cashbank.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_cashbank.js", markup)

	def test_the_menu_offers_it(self):
		sidebar = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "_sidebar.html")).read()
		self.assertIn("/retail/cashbank", sidebar)


class TestBranchCashAndBank(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		cls.branch = "Kochi"
		frappe.db.commit()

	def setUp(self):
		user = user_for("Kochi Manager")
		if not user:
			self.skipTest("Kochi Manager is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_summary_answers_for_this_branch_only(self):
		sums = cashbank.summary()
		self.assertEqual(sums["branch"], self.branch)
		self.assertEqual(
			flt(sums["total"]), flt(sums["cash_total"]) + flt(sums["bank_total"]))

	def test_every_account_is_cash_or_bank(self):
		sums = cashbank.summary()
		for row in sums["cash"] + sums["banks"]:
			self.assertIn(
				frappe.db.get_value("Account", row["account"], "account_type"),
				("Cash", "Bank"),
			)

	def test_transactions_carry_a_direction(self):
		rows = cashbank.transactions(limit=10)["rows"]
		for row in rows:
			self.assertIn(row["direction"], ("in", "out"))

	def test_banking_more_than_the_branch_holds_is_refused(self):
		sums = cashbank.summary()
		if not sums["cash"] or not sums["banks"]:
			self.skipTest("this company has no cash and bank pair to move between")
		with self.assertRaises(frappe.ValidationError):
			cashbank.deposit({
				"amount": flt(sums["cash_total"]) + 100000,
				"from_account": sums["cash"][0]["account"],
				"to_account": sums["banks"][0]["account"],
			})

	def test_money_cannot_move_to_where_it_came_from(self):
		sums = cashbank.summary()
		if not sums["cash"]:
			self.skipTest("this company has no cash account")
		account = sums["cash"][0]["account"]
		with self.assertRaises(frappe.ValidationError):
			cashbank.deposit({"amount": 1, "from_account": account, "to_account": account})

	def test_a_future_dated_deposit_is_refused(self):
		sums = cashbank.summary()
		if not sums["cash"] or not sums["banks"]:
			self.skipTest("this company has no cash and bank pair to move between")
		with self.assertRaises(frappe.ValidationError):
			cashbank.deposit({
				"amount": 1,
				"from_account": sums["cash"][0]["account"],
				"to_account": sums["banks"][0]["account"],
				"date": frappe.utils.add_days(frappe.utils.nowdate(), 2),
			})

	def test_a_deposit_moves_the_money_and_leaves_the_total_alone(self):
		sums = cashbank.summary()
		if not sums["cash"] or not sums["banks"] or flt(sums["cash_total"]) < 10:
			self.skipTest("no cash in this branch's drawer to bank")

		before_total = flt(sums["total"])
		result = cashbank.deposit({
			"amount": 10,
			"from_account": sums["cash"][0]["account"],
			"to_account": sums["banks"][0]["account"],
		})
		self.assertTrue(frappe.db.exists("Journal Entry", result["entry"]))

		after = cashbank.summary()
		self.assertAlmostEqual(flt(after["cash_total"]), flt(sums["cash_total"]) - 10, places=2)
		self.assertAlmostEqual(flt(after["bank_total"]), flt(sums["bank_total"]) + 10, places=2)
		# money moved, it did not appear or vanish
		self.assertAlmostEqual(flt(after["total"]), before_total, places=2)
