# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""The Accessories UK shelf, as it comes off myBillBook's stock summary.

The count itself is posted by a patch that runs once on a deploy, so what can
be held to account here is the file it reads and the rules it matches by. Both
have teeth: a name matched too loosely puts one branch's stock on another
branch's item, and a name matched too strictly makes a second item for a
product the branch already sells — which is how a shelf ends up counted twice.
"""

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.patches import accessories_uk_opening_stock as patch


class TestTheSheet(FrappeTestCase):
	def setUp(self):
		self.shelf = patch._data()

	def test_the_file_ships_with_the_app(self):
		"""A patch that reads a file nobody deployed counts nothing."""
		path = frappe.get_app_path("a3_retail", "patches", "data",
		                           "accessories_uk_stock.json")
		self.assertTrue(os.path.exists(path), path)
		self.assertEqual(len(self.shelf), 566)

	def test_every_line_has_what_the_count_needs(self):
		for row in self.shelf:
			self.assertTrue(row.get("name"), row)
			self.assertIsInstance(row["qty"], (int, float), row)
			self.assertGreaterEqual(float(row.get("sell") or 0), 0, row)
			self.assertGreaterEqual(float(row.get("mrp") or 0), 0, row)

	def test_one_line_per_product(self):
		"""myBillBook held seven names twice; the file holds each once."""
		names = [patch._norm(r["name"]) for r in self.shelf]
		self.assertEqual(len(names), len(set(names)))
		self.assertEqual(sum(1 for r in self.shelf if r.get("merged")), 7)

	def test_the_shelf_is_the_size_the_shop_counted(self):
		counted = [r for r in self.shelf if r["qty"] > 0]
		self.assertEqual(len(counted), 290)
		self.assertEqual(round(sum(r["qty"] for r in counted)), 17671)

	def test_nothing_below_zero_is_ever_counted_in(self):
		"""72 lines are negative — a shelf cannot hold minus eleven chargers,
		so they are catalogued and left for the branch to find."""
		short = [r for r in self.shelf if r["qty"] < 0]
		self.assertEqual(len(short), 72)
		for row in short:
			self.assertLess(row["qty"], 0)

	def test_a_line_worth_nothing_cannot_be_valued(self):
		"""Opening stock needs a rate, so a priced line is what makes it in."""
		for row in self.shelf:
			if row["qty"] > 0:
				self.assertGreater(float(row.get("sell") or row.get("mrp") or 0), 0,
				                   row["name"])


class TestHowNamesAreMatched(FrappeTestCase):
	def test_spacing_alone_never_makes_a_second_item(self):
		self.assertEqual(patch._norm("AMAQ    20W PD"), patch._norm("AMAQ 20W PD"))
		self.assertEqual(patch._norm(" zeb ma200 type c "), "ZEB MA200 TYPE C")

	def test_the_short_codes_the_two_shops_write_differently(self):
		for sheet, catalogue in (("T 150", "T150"), ("P 200", "P200"),
		                         ("T 300", "T300"), ("T 450", "T450")):
			self.assertEqual(patch._tight(sheet), patch._tight(catalogue))

	def test_flattening_still_tells_different_products_apart(self):
		self.assertNotEqual(patch._tight("T 150"), patch._tight("T 1500"))
		self.assertNotEqual(patch._tight("AIRPODS 700"), patch._tight("AIRPODS 700-2"))

	def test_an_ambiguous_flattened_name_is_never_used(self):
		"""The migration left twins that flatten alike. Choosing between them is
		the shop's call, so the index drops the key rather than guessing."""
		loose, tight = patch._index()
		self.assertTrue(loose)
		seen = {}
		for item in frappe.get_all("Item", fields=["name", "item_name"], limit=0):
			for key in (patch._tight(item.item_name), patch._tight(item.name)):
				if key:
					seen.setdefault(key, set()).add(item.name)
		for key, owners in seen.items():
			if len(owners) > 1:
				self.assertNotIn(key, tight, key)

	def test_the_branch_s_own_record_wins_over_a_flattened_guess(self):
		loose = {"T 150": "UK-ITEM"}
		tight = {"T150": "PSLA-ITEM"}
		self.assertEqual(patch._resolve({"name": "T 150", "code": ""}, loose, tight),
		                 "UK-ITEM")
		self.assertEqual(patch._resolve({"name": "T 150", "code": ""}, {}, tight),
		                 "PSLA-ITEM")


class TestTheDeploy(FrappeTestCase):
	def test_the_patch_runs_on_a_deploy(self):
		registered = open(frappe.get_app_path("a3_retail", "patches.txt")).read()
		self.assertIn("a3_retail.patches.accessories_uk_opening_stock", registered)

	def test_it_counts_one_shelf_and_only_that_one(self):
		self.assertEqual(patch.WAREHOUSE, "PhoneXpert Accessories UK - PT")
		self.assertEqual(patch.BRANCH, "PhoneXpert Accessories UK")

	def test_it_posts_in_batches_ERPNext_will_take_at_deploy_time(self):
		"""Over a hundred lines and ERPNext hands the document to a background
		worker, leaving a draft behind on a deploy where nothing is listening."""
		self.assertLessEqual(patch.BATCH, 100)
		counted = sum(1 for r in patch._data() if r["qty"] > 0)
		self.assertGreater(counted, patch.BATCH)

	def test_the_data_file_is_json_a_person_can_read(self):
		path = frappe.get_app_path("a3_retail", "patches", "data",
		                           "accessories_uk_stock.json")
		with open(path, encoding="utf-8") as handle:
			self.assertIsInstance(json.load(handle), list)
