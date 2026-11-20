# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Second-hand devices: the margin scheme, the counters, and the bill.

GST on a used device is charged on the margin — selling price less purchase
price — under Rule 32(5). The bill carries that as two lines, because ERPNext's
arithmetic is total = taxable + tax and the margin scheme breaks it: the
customer pays 25,000 while the value of supply is 5,000.
"""

import itertools
import re

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.overrides.transactions import MARGIN_ITEM

BRANCH = "PhoneXpert Used PSLA"
WAREHOUSE = "PhoneXpert Used PSLA - PT"


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


def _margin_invoice(sold_at=25000.0, bought_at=20000.0, serial="USED-TEST-0001"):
	"""A used phone bought and sold, billed the way the counter bills it."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	code = "USED-TEST-PHONE"
	if not frappe.db.exists("Item", code):
		src = frappe.db.get_value("Item", {"gst_hsn_code": "85171300"},
		                          ["item_group", "stock_uom"], as_dict=True)
		doc = frappe.new_doc("Item")
		doc.item_code = code
		doc.item_name = "Used phone (test)"
		doc.item_group = src.item_group
		doc.stock_uom = src.stock_uom
		doc.gst_hsn_code = "85171300"
		doc.is_stock_item = 0
		doc.a3_is_margin_scheme = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	template = frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"company": company, "title": "Output GST In-state 18%"}, "name")

	si = frappe.new_doc("Sales Invoice")
	si.company = company
	si.branch = BRANCH
	si.customer = frappe.db.get_value("Customer", {}, "name")
	si.taxes_and_charges = template
	for row in get_taxes_and_charges("Sales Taxes and Charges Template", template):
		si.append("taxes", row)
	si.append("items", {"item_code": code, "qty": 1, "rate": sold_at,
	                    "a3_purchase_cost": bought_at})
	si.flags.ignore_permissions = True
	si.insert(ignore_permissions=True)
	return si


class TestTheCounters(FrappeTestCase):
	def test_both_second_hand_branches_exist(self):
		for branch in ("PhoneXpert Used PSLA", "PhoneXpert Used UK"):
			self.assertTrue(frappe.db.exists("Branch", branch), branch)
			self.assertTrue(frappe.db.exists("Branch Profile", {"branch": branch}))

	def test_each_sits_at_the_shop_it_belongs_to(self):
		"""So a till that may work both counters at one address is offered this
		one too."""
		for branch, site in (("PhoneXpert Used PSLA", "PSLA"),
		                     ("PhoneXpert Used UK", "UK")):
			self.assertEqual(
				frappe.db.get_value("Branch Profile", {"branch": branch}, "site"), site)

	def test_each_has_a_shelf_of_its_own(self):
		"""Used stock cannot sit with new: every handset was bought at a
		different price, and the margin is measured against that price."""
		for branch in ("PhoneXpert Used PSLA", "PhoneXpert Used UK"):
			warehouse = frappe.db.get_value("Branch Profile", {"branch": branch},
			                                "default_warehouse")
			self.assertTrue(warehouse)
			self.assertIn("Used", warehouse)

	def test_each_has_its_own_cost_centre(self):
		"""So the used trade's profit reads on its own."""
		for branch in ("PhoneXpert Used PSLA", "PhoneXpert Used UK"):
			centre = frappe.db.get_value("Branch Profile", {"branch": branch},
			                             "cost_center")
			self.assertTrue(centre)
			self.assertIn("Used", centre)

	def test_each_points_at_its_shop_s_own_review_link(self):
		psla = frappe.db.get_value("Branch Profile",
		                           {"branch": "PhoneXpert Used PSLA"}, "google_review_code")
		uk = frappe.db.get_value("Branch Profile",
		                         {"branch": "PhoneXpert Used UK"}, "google_review_code")
		if psla and uk:
			self.assertNotEqual(psla, uk)

	def test_the_margin_line_item_exists_and_is_not_stock(self):
		"""It is the value of supply, not a thing on a shelf."""
		self.assertTrue(frappe.db.exists("Item", MARGIN_ITEM))
		self.assertFalse(frappe.db.get_value("Item", MARGIN_ITEM, "is_stock_item"))
		self.assertTrue(frappe.db.get_value("Item", MARGIN_ITEM, "gst_hsn_code"))

	def test_the_patch_runs_on_a_live_site(self):
		self.assertIn("a3_retail.patches.second_hand_branches", _source("patches.txt"))


class TestWhatTheBillIsMadeOf(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.si = _margin_invoice()

	def test_the_customer_pays_the_price_that_was_agreed(self):
		"""The whole point: the split is for the return, not for the customer."""
		self.assertAlmostEqual(flt(self.si.grand_total), 25000.0, places=2)

	def test_the_tax_is_on_the_margin_and_not_on_the_price(self):
		expected = round(5000 * 18 / 118, 2)
		self.assertAlmostEqual(flt(self.si.total_taxes_and_charges), expected, places=1)
		# What it would have been on the full price, which is what used to happen.
		self.assertNotAlmostEqual(flt(self.si.total_taxes_and_charges),
		                          round(25000 * 18 / 118, 2), places=0)

	def test_the_bill_carries_the_two_parts(self):
		codes = [row.item_code for row in self.si.items]
		self.assertEqual(len(codes), 2)
		self.assertIn(MARGIN_ITEM, codes)

	def test_the_handset_is_billed_at_what_the_shop_paid_and_not_taxed(self):
		handset = next(r for r in self.si.items if r.item_code != MARGIN_ITEM)
		self.assertAlmostEqual(flt(handset.rate), 20000.0, places=2)
		self.assertTrue(handset.item_tax_template)
		rates = frappe.get_all("Item Tax Template Detail",
		                       filters={"parent": handset.item_tax_template},
		                       pluck="tax_rate")
		self.assertEqual(sum(rates or [0]), 0, "the handset half must not be taxed")

	def test_the_margin_line_carries_the_margin(self):
		margin = next(r for r in self.si.items if r.item_code == MARGIN_ITEM)
		self.assertAlmostEqual(flt(margin.rate), 5000.0, places=2)

	def test_the_price_the_customer_agreed_is_kept(self):
		"""The row's own rate is no longer it, so the bill needs it recorded."""
		handset = next(r for r in self.si.items if r.item_code != MARGIN_ITEM)
		self.assertAlmostEqual(flt(handset.a3_gross_rate), 25000.0, places=2)
		self.assertAlmostEqual(flt(handset.a3_margin_value), 5000.0, places=2)

	def test_saving_it_again_does_not_shrink_the_margin(self):
		"""The row's rate is the untaxed part after the first pass. Measuring
		the margin from that a second time would eat it away."""
		before = flt(self.si.grand_total)
		self.si.flags.ignore_permissions = True
		self.si.save(ignore_permissions=True)
		handset = next(r for r in self.si.items if r.item_code != MARGIN_ITEM)
		self.assertAlmostEqual(flt(handset.a3_margin_value), 5000.0, places=2)
		self.assertAlmostEqual(flt(self.si.grand_total), before, places=2)
		self.assertEqual(len([r for r in self.si.items if r.item_code == MARGIN_ITEM]), 1,
		                 "a second save added a second margin line")

	def test_a_loss_is_not_taxed_and_not_carried_forward(self):
		"""Rule 32(5): a negative margin is ignored."""
		si = _margin_invoice(sold_at=18000.0, bought_at=20000.0)
		handset = next(r for r in si.items if r.item_code != MARGIN_ITEM)
		self.assertEqual(flt(handset.a3_margin_value), 0.0)
		self.assertEqual(flt(si.total_taxes_and_charges), 0.0)
		self.assertAlmostEqual(flt(si.grand_total), 18000.0, places=2)

	def test_the_margin_is_earned_in_its_own_account(self):
		margin = next(r for r in self.si.items if r.item_code == MARGIN_ITEM)
		self.assertIn("Used Devices", margin.income_account or "")


class TestItRefusesWhatItCannotTax(FrappeTestCase):
	def test_a_used_device_cannot_share_a_bill_with_new_stock(self):
		"""One tax block cannot be both a percentage of everything and nothing
		at all on one line."""
		frappe.set_user("Administrator")
		si = _margin_invoice()
		new_stock = frappe.db.get_value(
			"Item", {"is_stock_item": 0, "disabled": 0, "a3_is_margin_scheme": 0,
			         "name": ["not in", (MARGIN_ITEM,)]}, "name")
		if not new_stock:
			self.skipTest("no ordinary item to mix in")
		si.append("items", {"item_code": new_stock, "qty": 1, "rate": 500})
		si.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			si.save(ignore_permissions=True)

	def test_an_ordinary_bill_is_left_completely_alone(self):
		"""The hook runs on every sale; it must do nothing to the other ones."""
		from a3_retail.overrides.transactions import apply_margin_scheme

		frappe.set_user("Administrator")
		ordinary = frappe.db.get_value(
			"Item", {"is_stock_item": 0, "disabled": 0, "a3_is_margin_scheme": 0,
			         "name": ["not in", (MARGIN_ITEM,)]}, "name")
		if not ordinary:
			self.skipTest("no ordinary item on this site")

		si = frappe.new_doc("Sales Invoice")
		si.company = frappe.db.get_single_value("Global Defaults", "default_company")
		si.customer = frappe.db.get_value("Customer", {}, "name")
		si.append("items", {"item_code": ordinary, "qty": 1, "rate": 500})
		apply_margin_scheme(si)
		self.assertEqual(len(si.items), 1)
		self.assertEqual(si.items[0].item_code, ordinary)

	def test_a_bill_of_only_the_margin_line_is_not_emptied(self):
		"""It strips its own line to rebuild it; with nothing to rebuild from
		that used to leave an invoice with no items at all."""
		from a3_retail.overrides.transactions import apply_margin_scheme

		frappe.set_user("Administrator")
		si = frappe.new_doc("Sales Invoice")
		si.company = frappe.db.get_single_value("Global Defaults", "default_company")
		si.customer = frappe.db.get_value("Customer", {}, "name")
		si.append("items", {"item_code": MARGIN_ITEM, "qty": 1, "rate": 500})
		apply_margin_scheme(si)
		self.assertEqual(len(si.items), 1)


class TestTheCustomerCopy(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.si = _margin_invoice()
		self.si.submit()
		self.html = frappe.get_print("Sales Invoice", self.si.name,
		                             print_format="Used Device Bill")
		body = re.sub(r"<style.*?</style>", " ", self.html, flags=re.S)
		self.text = re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", body))

	def test_the_format_is_registered(self):
		self.assertTrue(frappe.db.exists("Print Format", "Used Device Bill"))

	def test_it_shows_the_price_the_customer_paid(self):
		self.assertIn("25,000", self.text)

	def test_it_does_not_show_what_the_shop_paid(self):
		"""The split would hand the customer the shop's buying price."""
		self.assertNotIn("20,000", self.text)

	def test_it_does_not_show_the_margin_line(self):
		self.assertNotIn(MARGIN_ITEM, self.text)
		self.assertNotIn("4,237", self.text)

	def test_it_shows_no_tax_figures(self):
		self.assertNotIn("762", self.text)
		self.assertNotIn("381", self.text)

	def test_it_says_why_there_is_no_tax_on_it(self):
		"""A bill with no GST on it needs to explain itself, or it reads like
		one that forgot."""
		self.assertIn("Rule 32(5)", self.text)
		self.assertIn("margin scheme", self.text)


class TestTakingAUsedHandsetIn(FrappeTestCase):
	"""The counter buys a phone from whoever walks in: no bill, no supplier,
	and a price that is the whole basis of the GST on the eventual resale."""

	BRANCH = "PhoneXpert Used PSLA"

	def setUp(self):
		from a3_retail.api.staff import ACTIVE_BRANCH_KEY

		frappe.set_user("Administrator")
		frappe.cache().hset(ACTIVE_BRANCH_KEY, "Administrator", self.BRANCH)
		self.addCleanup(frappe.cache().hdel, ACTIVE_BRANCH_KEY, "Administrator")
		self._a_used_model()

	@staticmethod
	def _a_used_model():
		code = "USED-TEST-INTAKE"
		if not frappe.db.exists("Item", code):
			src = frappe.db.get_value("Item", {"gst_hsn_code": "85171300"},
			                          ["item_group", "stock_uom"], as_dict=True)
			doc = frappe.new_doc("Item")
			doc.item_code = code
			doc.item_name = "Used phone, intake test"
			doc.item_group = src.item_group
			doc.stock_uom = src.stock_uom
			doc.gst_hsn_code = "85171300"
			doc.is_stock_item = 1
			doc.has_serial_no = 1
			doc.serial_no_series = "UINT-.####"
			doc.a3_is_margin_scheme = 1
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		return code

	_next = itertools.count(1)

	@classmethod
	def _an_unused_imei(cls):
		"""A handset already on file is refused, and the rollback only happens
		once the class is done — so no two calls may share a number."""
		while True:
			imei = f"91111111111{next(cls._next):04d}"
			if not frappe.db.exists("Serial No", imei):
				return imei

	def _buy(self, **over):
		from a3_retail.api.stock_control import buy_used_device

		imei = self._an_unused_imei()
		payload = {"item_code": "USED-TEST-INTAKE", "serial_no": imei,
		           "imei": imei, "paid": 18500,
		           "seller": "Rahul Krishnan", "mobile": "9847012345",
		           "id_shown": "Aadhaar xxxx 4412",
		           "condition": "Scratch on back glass",
		           "date": frappe.utils.nowdate()}
		payload.update(over)
		return buy_used_device(payload)

	def test_it_lands_on_this_counter_s_second_hand_shelf(self):
		out = self._buy()
		self.assertIn("Used", out["warehouse"])
		self.assertEqual(
			frappe.db.get_value("Serial No", out["serial_no"], "warehouse"),
			out["warehouse"])

	def test_what_was_paid_is_kept_against_the_handset(self):
		"""Every used phone is priced on its own, and the margin on the resale
		is measured against this one's own cost."""
		out = self._buy(paid=18500)
		self.assertEqual(
			flt(frappe.db.get_value("Serial No", out["serial_no"], "a3_purchase_cost")),
			18500.0)

	def test_the_seller_is_recorded_on_the_piece(self):
		"""The scheme assumes the shop can show who it bought from."""
		out = self._buy()
		row = frappe.db.get_value(
			"Serial No", out["serial_no"],
			["a3_bought_from", "a3_bought_from_mobile", "a3_bought_from_id",
			 "a3_bought_on", "a3_device_condition"], as_dict=True)
		self.assertEqual(row.a3_bought_from, "Rahul Krishnan")
		self.assertEqual(row.a3_bought_from_mobile, "9847012345")
		self.assertTrue(row.a3_bought_from_id)
		self.assertTrue(row.a3_bought_on)
		self.assertTrue(row.a3_device_condition)

	def test_the_stock_really_moved(self):
		out = self._buy()
		entry = frappe.get_doc("Stock Entry", out["entry"])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.stock_entry_type, "Material Receipt")
		self.assertAlmostEqual(flt(entry.items[0].basic_rate), 18500.0, places=2)

	def test_it_refuses_an_item_not_set_up_for_the_scheme(self):
		"""Buying in against an ordinary item would have the resale taxed on
		the whole price, and nothing downstream would notice."""
		ordinary = frappe.db.get_value(
			"Item", {"is_stock_item": 1, "disabled": 0, "a3_is_margin_scheme": 0},
			"name")
		if not ordinary:
			self.skipTest("no ordinary stock item on this site")
		with self.assertRaises(frappe.ValidationError):
			self._buy(item_code=ordinary, serial_no="911111111111009")

	def test_it_refuses_without_an_imei(self):
		with self.assertRaises(frappe.ValidationError):
			self._buy(serial_no="")

	def test_it_refuses_without_a_price(self):
		with self.assertRaises(frappe.ValidationError):
			self._buy(serial_no="911111111111002", paid=0)

	def test_it_refuses_without_a_seller(self):
		with self.assertRaises(frappe.ValidationError):
			self._buy(serial_no="911111111111003", seller="")

	def test_the_same_handset_cannot_be_taken_in_twice(self):
		out = self._buy()
		with self.assertRaises(frappe.ValidationError):
			self._buy(serial_no=out["serial_no"])

	def test_it_refuses_a_day_that_has_not_happened(self):
		with self.assertRaises(frappe.ValidationError):
			self._buy(serial_no="911111111111004",
			          date=frappe.utils.add_days(frappe.utils.nowdate(), 3))


class TestOnlySecondHandModelsAreOffered(FrappeTestCase):
	def test_the_search_offers_only_margin_scheme_items(self):
		from a3_retail.api.stock_control import search_used_models

		frappe.set_user("Administrator")
		rows = search_used_models(query="us", limit=20)
		for row in rows:
			self.assertTrue(
				frappe.db.get_value("Item", row["item_code"], "a3_is_margin_scheme"),
				f"{row['item_code']} is not a second-hand model")

	def test_a_short_query_asks_for_more(self):
		from a3_retail.api.stock_control import search_used_models

		frappe.set_user("Administrator")
		self.assertEqual(search_used_models(query="u"), [])


class TestTheButtonReachesIt(FrappeTestCase):
	def test_the_stock_screen_offers_it(self):
		page = open(frappe.get_app_path("a3_retail", "www", "retail", "stock.html"),
		            encoding="utf-8").read()
		self.assertIn('data-do="buy-used"', page)
		self.assertIn("Buy Used Device", page)

	def test_the_press_reaches_a_handler(self):
		js = open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js"),
		          encoding="utf-8").read()
		self.assertIn('if (what === "buy-used") return openBuyUsed();', js)
		self.assertIn("function openBuyUsed()", js)

	def test_it_is_shown_only_to_who_may_receive_stock(self):
		js = open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js"),
		          encoding="utf-8").read()
		self.assertIn('"buy-used": "receive"', js)

	def test_the_dialog_asks_for_everything_the_scheme_needs(self):
		js = open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js"),
		          encoding="utf-8").read()
		block = js[js.index("function openBuyUsed()"):]
		block = block[:block.index("\n\tfunction openGoodsIn()")]
		for field in ("w-used-item", "w-used-imei", "w-used-paid", "w-used-seller"):
			self.assertIn(field, block)
		self.assertIn("a3_retail.api.stock_control.buy_used_device", block)
		# Only second-hand models, or the resale is taxed on the whole price.
		self.assertIn("search_used_models", block)
