# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The Stock Adjustment Register — what a count changed, and by how much."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

REPORT = "Stock Adjustment Register"
PERIOD = {"from_date": "2026-01-01", "to_date": "2026-12-31"}


def _execute(**filters):
	from a3_retail.a3_retail_operations.report.stock_adjustment_register import (
		stock_adjustment_register as report)

	return report.execute({**PERIOD, **filters})


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


class TestItIsOnTheReportsScreen(FrappeTestCase):
	def test_the_report_exists(self):
		self.assertTrue(frappe.db.exists("Report", REPORT))

	def test_it_is_filed_under_stock(self):
		from a3_retail.api.reports import catalogue

		frappe.set_user("Administrator")
		rows = [r for r in catalogue()["reports"] if r["name"] == REPORT]
		self.assertTrue(rows, "the report is not in the catalogue")
		self.assertEqual(rows[0]["category"], "inventory")

	def test_it_is_described_in_the_shop_s_words(self):
		from a3_retail.api.reports import DESCRIPTIONS

		self.assertIn(REPORT, DESCRIPTIONS)
		self.assertNotIn("Built from", DESCRIPTIONS[REPORT])

	def test_the_counter_roles_may_run_it(self):
		roles = set(frappe.get_all("Has Role", filters={"parent": REPORT}, pluck="role"))
		self.assertIn("Branch Manager", roles)
		self.assertIn("Store Keeper", roles)


class TestTheNumbers(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.columns, self.data, *_rest = _execute(only_differences=1)
		if not self.data:
			self.skipTest("no stock adjustments on this site")

	def test_it_reports_both_differences_the_shop_asked_for(self):
		names = {c["fieldname"] for c in self.columns}
		self.assertIn("qty_difference", names)
		self.assertIn("amount_difference", names)

	def test_the_quantity_difference_is_counted_minus_system(self):
		for row in self.data:
			self.assertAlmostEqual(
				flt(row["qty_difference"]),
				flt(row["counted_qty"]) - flt(row["system_qty"]), places=4,
				msg=f"{row['item_code']} does not add up")

	def test_the_amount_difference_is_counted_minus_system(self):
		for row in self.data:
			self.assertAlmostEqual(
				flt(row["amount_difference"]),
				flt(row["counted_value"]) - flt(row["system_value"]), places=2,
				msg=f"{row['item_code']} does not add up")

	def test_the_difference_is_a_number_and_not_the_stored_string(self):
		"""ERPNext stores `quantity_difference` as a read-only *string* —
		`'1.0'`, `'-4.0'`. Summed in SQL that concatenates, and every total
		comes out wrong, so the register does the subtraction itself."""
		for row in self.data:
			self.assertIsInstance(row["qty_difference"], (int, float),
			                      f"{row['item_code']} came back as text")

		body = _source("a3_retail_operations", "report", "stock_adjustment_register",
		               "stock_adjustment_register.py")
		self.assertNotIn("it.quantity_difference", body)
		self.assertIn("ifnull(it.qty, 0) - ifnull(it.current_qty, 0)", body)

	def test_the_total_matches_what_erpnext_recorded_on_the_document(self):
		"""The strongest check available: ERPNext stores its own
		`difference_amount` per reconciliation, worked out independently."""
		ours = sum(flt(r["amount_difference"]) for r in self.data)
		theirs = flt(frappe.db.sql("""
			select sum(difference_amount) from `tabStock Reconciliation`
			where docstatus = 1 and purpose = 'Stock Reconciliation'
			  and posting_date between %(from_date)s and %(to_date)s""",
			PERIOD)[0][0])
		self.assertAlmostEqual(ours, theirs, places=2)


class TestWhatItLeavesOut(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_the_migration_s_opening_balances_are_not_adjustments(self):
		"""49 opening documents worth about ₹2.47 crore against ₹34 lakh of real
		counting. Left in, this is a report about the migration."""
		_cols, data, *_rest = _execute()
		self.assertTrue(all(row["purpose"] == "Stock Reconciliation" for row in data))

	def test_but_they_can_be_asked_for(self):
		_cols, data, *_rest = _execute(purpose="Opening Stock")
		if not data:
			self.skipTest("no opening stock entries on this site")
		self.assertTrue(all(row["purpose"] == "Opening Stock" for row in data))

	def test_rows_that_did_not_change_can_be_hidden(self):
		_cols, changed, *_rest = _execute(only_differences=1)
		_cols, every, *_rest = _execute(only_differences=0)
		self.assertLessEqual(len(changed), len(every))
		for row in changed:
			self.assertNotEqual(flt(row["qty_difference"]), 0.0)

	def test_one_item_can_be_followed_on_its_own(self):
		_cols, data, *_rest = _execute(only_differences=1)
		if not data:
			self.skipTest("no stock adjustments on this site")
		item = data[0]["item_code"]
		_cols, just_it, *_rest = _execute(item_code=item, only_differences=1)
		self.assertTrue(just_it)
		self.assertTrue(all(row["item_code"] == item for row in just_it))


class TestTheCardsAboveTheTable(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.result = _execute(only_differences=1)
		if not self.result[1]:
			self.skipTest("no stock adjustments on this site")

	def test_the_report_supplies_its_own_cards(self):
		self.assertEqual(len(self.result), 5, "execute must return report_summary")
		cards = self.result[4]
		self.assertEqual([c["label"] for c in cards],
		                 ["Pieces found extra", "Pieces missing",
		                  "Net value change", "Value written off"])

	def test_the_cards_use_the_key_the_page_reads(self):
		"""`_report_kpis` reads `datatype`; a card keyed `fieldtype` shows as
		a bare Float."""
		for card in self.result[4]:
			self.assertIn("datatype", card)

	def test_gains_and_losses_are_kept_apart(self):
		"""50 extra of one thing and 50 missing of another nets to zero, which
		is exactly when a net figure misleads most."""
		data, cards = self.result[1], self.result[4]
		by_label = {c["label"]: flt(c["value"]) for c in cards}

		up = sum(flt(r["qty_difference"]) for r in data if flt(r["qty_difference"]) > 0)
		down = sum(flt(r["qty_difference"]) for r in data if flt(r["qty_difference"]) < 0)
		self.assertAlmostEqual(by_label["Pieces found extra"], up, places=4)
		self.assertAlmostEqual(by_label["Pieces missing"], abs(down), places=4)
		self.assertGreaterEqual(by_label["Pieces found extra"], 0)
		self.assertGreaterEqual(by_label["Pieces missing"], 0)


class TestTheTotalsAreNotDoubled(FrappeTestCase):
	def test_no_total_row_is_appended(self):
		"""The reports page sums every Currency column it is handed, so a
		"Total" row inside the data would be counted twice over."""
		frappe.set_user("Administrator")
		_cols, data, *_rest = _execute(only_differences=1)
		self.assertTrue(all(row.get("adjustment") != "Total" for row in data))

	def test_the_page_total_equals_the_sum_of_the_rows(self):
		from a3_retail.api.reports import run

		frappe.set_user("Administrator")
		out = run(REPORT, {**PERIOD, "only_differences": 1})
		if not out["rows"]:
			self.skipTest("no stock adjustments on this site")
		self.assertAlmostEqual(
			flt(out["totals"]["amount_difference"]),
			sum(flt(r["amount_difference"]) for r in out["rows"]), places=2)

	def test_a_rate_column_is_never_totalled(self):
		"""Rates added together are a number that means nothing."""
		from a3_retail.api.reports import run

		frappe.set_user("Administrator")
		out = run(REPORT, {**PERIOD, "only_differences": 1})
		self.assertNotIn("valuation_rate", out["totals"])


class TestTheFiltersOpenAsTheyShould(FrappeTestCase):
	def test_the_page_honours_a_select_and_a_check_default(self):
		"""These were dropped — only the two date defaults were recognised — so
		the page opened blank while the report quietly did something else."""
		from a3_retail.api.reports import definition

		frappe.set_user("Administrator")
		filters = {row["fieldname"]: row for row in definition(REPORT)["filters"]}
		self.assertEqual(filters["purpose"]["default"], "Stock Reconciliation")
		self.assertEqual(flt(filters["only_differences"]["default"]), 1.0)

	def test_the_select_offers_its_choices_as_separate_options(self):
		"""The choices are written in the report's JS as `"A\\nB"`, and that
		source is read as text — so what arrived was a backslash and an `n`.
		The page splits on newlines, saw a single choice called `A\\nB`, matched
		nothing, and showed "All" while the report filtered on something else."""
		from a3_retail.api.reports import definition

		frappe.set_user("Administrator")
		row = {f["fieldname"]: f for f in definition(REPORT)["filters"]}["purpose"]
		self.assertEqual((row["options"] or "").split("\n"),
		                 ["Stock Reconciliation", "Opening Stock"])
		self.assertNotIn("\\n", row["options"] or "")

	def test_the_chosen_default_is_one_of_the_options(self):
		"""Otherwise the dropdown cannot show it and silently reads "All"."""
		from a3_retail.api.reports import definition

		frappe.set_user("Administrator")
		row = {f["fieldname"]: f for f in definition(REPORT)["filters"]}["purpose"]
		self.assertIn(row["default"], (row["options"] or "").split("\n"))

	def test_the_dates_still_default_as_before(self):
		from a3_retail.api.reports import definition

		frappe.set_user("Administrator")
		filters = {row["fieldname"]: row for row in definition(REPORT)["filters"]}
		self.assertTrue(filters["from_date"]["default"])
		self.assertTrue(filters["to_date"]["default"])
		self.assertLess(filters["from_date"]["default"], filters["to_date"]["default"])
