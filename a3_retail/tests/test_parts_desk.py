# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Spare parts and accessories (`/branch/parts`)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import parts_desk as parts
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestPartsPage(FrappeTestCase):
	def test_the_page_is_one_standalone_document(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("parts.html", "parts.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		markup = open(os.path.join(folder, "parts.html")).read()
		self.assertIn("<!doctype html>", markup.lower())
		self.assertNotIn("{% extends", markup)
		self.assertIn("/assets/a3_retail/js/a3_parts.js", markup)
		self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_both_shelves_share_the_one_page(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "parts.html")
		).read()
		self.assertIn('data-kind="parts"', markup)
		self.assertIn('data-kind="accessories"', markup)
		for tab in ("waiting", "issued", "movements", "replacements", "returns"):
			self.assertIn(f'("{tab}"', markup, tab)

	def test_both_sidebar_entries_land_here(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("spares", "Spare Parts", "/branch/parts"', sidebar)
		self.assertIn('("accessories", "Accessories", "/branch/parts?kind=accessories"', sidebar)


class TestPartsAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_shelf(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, parts.catalogue)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, parts.bootstrap)


class TestPartsShelf(FrappeTestCase):
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

	def test_the_page_starts_with_the_store_and_the_bench(self):
		boot = parts.bootstrap()
		self.assertEqual(boot["branch"], "Kochi")
		self.assertTrue(boot["store"])
		self.assertTrue(boot["bench"])
		self.assertEqual([kind["key"] for kind in boot["kinds"]], ["parts", "accessories"])

	def test_each_shelf_holds_only_its_own_group(self):
		for kind, group in (("parts", "Spare Parts"), ("accessories", "Accessories")):
			for row in parts.catalogue(kind=kind):
				self.assertEqual(row["item_group"], group, row["item_code"])

	def test_a_row_carries_what_the_table_shows(self):
		rows = parts.catalogue("parts")
		if not rows:
			self.skipTest("no spare parts seeded")
		for key in ("item_code", "item_name", "store_qty", "bench_qty", "reserved",
		            "reorder_level", "rate", "fits", "status", "waiting"):
			self.assertIn(key, rows[0], key)

	def test_what_a_part_fits_comes_from_the_device_models(self):
		rows = [row for row in parts.catalogue("parts") if row["fits"]]
		if not rows:
			self.skipTest("no part is named on a device model")

		row = rows[0]
		for model in row["fits"]:
			standard = frappe.db.get_value(
				"Device Model", model, ["standard_display_part", "standard_battery_part"]
			)
			self.assertIn(row["item_code"], standard, model)

	def test_the_cards_count_the_shelf_that_is_open(self):
		for kind in ("parts", "accessories"):
			cards = parts.kpis(kind)
			self.assertEqual(cards["lines"]["value"], len(parts.catalogue(kind=kind, limit=200)))

	def test_every_tab_answers_with_rows(self):
		for name in ("waiting", "issued", "movements", "replacements", "returns"):
			self.assertIsInstance(parts.tab(name, "parts")["rows"], list, name)

	def test_the_waiting_tab_and_the_card_agree(self):
		"""Both count the repairs a part is holding up."""
		rows = parts.catalogue("parts", limit=200)
		waiting_on_shelf = {row["item_code"] for row in rows if row["waiting"]}
		waiting_on_tab = {row["item_code"] for row in parts.tab("waiting", "parts")["rows"]}
		self.assertTrue(waiting_on_shelf <= waiting_on_tab or not waiting_on_shelf)

	def test_a_part_s_own_history_is_this_branch_s_ledger(self):
		rows = parts.catalogue("parts")
		if not rows:
			self.skipTest("no spare parts seeded")

		warehouses = set(frappe.get_all(
			"Warehouse", filters={"custom_branch": "Kochi"}, pluck="name"))
		for entry in parts.movements_for(rows[0]["item_code"]):
			self.assertIn(entry["warehouse"], warehouses)

	def test_the_open_jobs_list_is_this_branch_s_bench(self):
		for job in parts.open_jobs():
			self.assertEqual(frappe.db.get_value("Service Job Card", job["name"], "branch"),
			                 "Kochi")


class TestPartsActions(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

		jobs = parts.open_jobs()
		if not jobs:
			self.skipTest("no open repairs on this bench")
		self.job = jobs[0]["name"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_assigning_a_part_puts_it_on_the_repair(self):
		before = frappe.db.count("Job Card Part", {"parent": self.job})
		result = parts.assign_to_service(self.job, "SPR-BAT-N13", 1)

		self.assertEqual(frappe.db.count("Job Card Part", {"parent": self.job}), before + 1)
		self.assertIn(result["status"], ("Issued", "On the bench", "Requested"))
		row = frappe.db.get_value("Job Card Part", result["row"],
		                          ["item_code", "qty", "part_status"], as_dict=True)
		self.assertEqual(row.item_code, "SPR-BAT-N13")
		self.assertEqual(flt(row.qty), 1)

	def test_a_closed_repair_takes_no_more_parts(self):
		closed = frappe.db.get_value("Service Job Card", {
			"branch": "Kochi", "docstatus": 1, "status": ["in", ("Delivered", "Closed")]}, "name")
		if not closed:
			self.skipTest("no closed repair to try")
		self.assertRaises(frappe.ValidationError, parts.assign_to_service,
		                  closed, "SPR-BAT-N13", 1)

	def test_another_branch_s_repair_is_refused(self):
		foreign = frappe.db.get_value("Service Job Card", {
			"branch": ["!=", "Kochi"], "docstatus": 1}, "name")
		if not foreign:
			self.skipTest("no repair outside this branch")
		self.assertRaises(frappe.ValidationError, parts.assign_to_service,
		                  foreign, "SPR-BAT-N13", 1)

	def test_a_replacement_needs_the_defect_written_down(self):
		self.assertRaises(frappe.ValidationError, parts.replace_part,
		                  self.job, "SPR-BAT-N13", "   ")

	def test_a_replacement_goes_out_free_and_the_old_one_is_logged(self):
		result = parts.replace_part(self.job, "SPR-BAT-N13", "Swelled after three weeks")

		row = frappe.db.get_value("Job Card Part", result["row"],
		                          ["is_warranty_covered", "item_code"], as_dict=True)
		self.assertTrue(row.is_warranty_covered, "a replacement is not charged again")

		if not result["oem_return"]:
			self.skipTest("this person cannot log an OEM return")

		claim = frappe.get_doc("OEM Warranty Return", result["oem_return"])
		logged = [item for item in claim.items if item.job_card == self.job]
		self.assertTrue(logged)
		self.assertIn("Swelled", logged[-1].defect_description)
		self.assertGreater(flt(logged[-1].claim_value), 0, "a claim worth nothing is not a claim")

	def test_selling_one_hands_it_to_the_counter(self):
		url = parts.sell_url("ACC-TGL-A55")
		self.assertTrue(url.startswith("/branch/sales?item="))

	def test_the_counter_picks_an_item_up_from_that_link(self):
		body = open(frappe.get_app_path("a3_retail", "public", "js", "a3_pos.js")).read()
		self.assertIn('params.get("item")', body)

	def test_the_parts_lifecycle_is_the_service_module_s_own(self):
		"""No second implementation of issuing, chasing or returning a part."""
		body = open(frappe.get_app_path("a3_retail", "api", "parts_desk.py")).read()
		for helper in ("issue_parts", "request_part", "return_unused_parts"):
			self.assertIn(f"import {helper}", body, helper)
		self.assertNotIn("stock_entry_type", body, "this module does not write Stock Entries")
