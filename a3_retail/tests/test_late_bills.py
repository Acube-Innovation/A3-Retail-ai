# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Bills keyed in behind a stock count, and the patch that lets them through.

The rule under test is not about stock running out. ERPNext refuses a
back-dated movement of a serialised item whenever a Stock Reconciliation for
that item and shelf is dated later, because the count states a quantity
outright. So the patch has to tell two counts apart: one that recorded a real
correction, which must stand and keep blocking, and one that declared the
figure the shelf already had, which is holding bills up for nothing.
"""

import itertools

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.patches import late_bills_the_count_locked_out as P
from a3_retail.tests.fixtures import ensure_customer

PREFIX = "A3-TEST-LATE-BILL"
_counter = itertools.count(1)


def _company() -> str:
	"""The company this site actually runs on, not the demo one.

	`fixtures.ensure_company` builds the demo company, which a site restored
	from the shop's own data does not have.
	"""
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _source() -> str:
	return open(frappe.get_app_path("a3_retail", "patches",
	                                "late_bills_the_count_locked_out.py"),
	            encoding="utf-8").read()


def _a_warehouse() -> str:
	company = _company()
	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def _an_item(tag: str) -> str:
	code = f"{PREFIX}-{tag}"
	if frappe.db.exists("Item", code):
		return code
	doc = frappe.new_doc("Item")
	doc.item_code = code
	doc.item_name = code
	doc.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	doc.stock_uom = "Nos"
	doc.is_stock_item = 1
	# India Compliance makes the HSN code mandatory on every item.
	doc.gst_hsn_code = frappe.db.get_value("GST HSN Code", {}, "name")
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return code


def _receive(item_code: str, warehouse: str, qty: float, on: str) -> str:
	entry = frappe.new_doc("Stock Entry")
	entry.company = _company()
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.set_posting_time = 1
	entry.posting_date = on
	entry.posting_time = "10:00:00"
	entry.append("items", {"item_code": item_code, "qty": qty,
	                       "t_warehouse": warehouse, "basic_rate": 100})
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name


def _count(item_code: str, warehouse: str, qty: float, on: str) -> str:
	reco = frappe.new_doc("Stock Reconciliation")
	reco.company = _company()
	reco.purpose = "Stock Reconciliation"
	reco.set_posting_time = 1
	reco.posting_date = on
	reco.posting_time = "18:00:00"
	reco.expense_account = frappe.get_cached_value(
		"Company", _company(), "stock_adjustment_account")
	reco.append("items", {"item_code": item_code, "warehouse": warehouse,
	                      "qty": qty, "valuation_rate": 100})
	reco.flags.ignore_permissions = True
	reco.insert(ignore_permissions=True)
	reco.submit()
	return reco.name


def _an_imei() -> str:
	"""An IMEI nothing on file has yet.

	The rollback only happens once the class is done, so two calls inside one
	class must not land on the same number.
	"""
	while True:
		imei = f"35999000{next(_counter):07d}"
		if not frappe.db.exists("Serial No", imei):
			return imei


def _a_serialised_item(tag: str) -> str:
	code = _an_item(tag)
	if not frappe.db.get_value("Item", code, "has_serial_no"):
		frappe.db.set_value("Item", code, "has_serial_no", 1, update_modified=False)
		frappe.clear_document_cache("Item", code)
	return code


def _receive_serialised(item_code: str, warehouse: str, imeis: list, on: str) -> str:
	entry = frappe.new_doc("Stock Entry")
	entry.company = _company()
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.set_posting_time = 1
	entry.posting_date = on
	entry.posting_time = "10:00:00"
	entry.append("items", {"item_code": item_code, "qty": len(imeis),
	                       "t_warehouse": warehouse, "basic_rate": 100,
	                       "use_serial_batch_fields": 1,
	                       "serial_no": "\n".join(imeis)})
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name


def _count_serialised(item_code: str, warehouse: str, imeis: list, on: str) -> str:
	"""A count that names the pieces it found, the way the shop's counts do."""
	reco = frappe.new_doc("Stock Reconciliation")
	reco.company = _company()
	reco.purpose = "Stock Reconciliation"
	reco.set_posting_time = 1
	reco.posting_date = on
	reco.posting_time = "18:00:00"
	reco.expense_account = frappe.get_cached_value(
		"Company", _company(), "stock_adjustment_account")
	reco.append("items", {"item_code": item_code, "warehouse": warehouse,
	                      "qty": len(imeis), "valuation_rate": 100,
	                      "use_serial_batch_fields": 1,
	                      "serial_no": "\n".join(imeis)})
	reco.flags.ignore_permissions = True
	reco.insert(ignore_permissions=True)
	reco.submit()
	return reco.name


def _a_draft_bill(item_code: str, warehouse: str, qty: float, on: str) -> str:
	doc = frappe.new_doc("Sales Invoice")
	doc.customer = ensure_customer()
	doc.company = _company()
	doc.set_posting_time = 1
	doc.posting_date = on
	doc.posting_time = "14:00:00"
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	doc.append("items", {"item_code": item_code, "qty": qty, "rate": 500,
	                     "warehouse": warehouse})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


class TestTellingTheTwoKindsOfCountApart(FrappeTestCase):
	"""`_what_the_count_changed` decides whether a count may be cancelled."""

	def test_a_count_restating_the_same_pieces_changed_nothing(self):
		"""The shape the shop's blocking count really had.

		ERPNext will not even save a count that changes a plain item's
		quantity by nothing. A serialised one gets in, because restating the
		IMEI list reads as a change to ERPNext while the quantity on the
		shelf never moves — and that is the count that sat in front of six
		bills recording nothing at all.
		"""
		item, wh = _a_serialised_item("NOOP"), _a_warehouse()
		imeis = [_an_imei(), _an_imei()]
		_receive_serialised(item, wh, imeis, add_days(nowdate(), -20))
		# ERPNext compares the IMEI list as one string, so a list restated in
		# another order reads as a change and the count saves — while the
		# quantity on the shelf never moves. That is the gap the shop's count
		# came through.
		reco = _count_serialised(item, wh, imeis[::-1], add_days(nowdate(), -10))

		self.assertEqual(P._what_the_count_changed(reco), [],
		                 "a count that found exactly the pieces already on the "
		                 "shelf should read as recording nothing")

	def test_a_count_declaring_a_different_figure_is_a_real_count(self):
		item, wh = _an_item("REAL"), _a_warehouse()
		_receive(item, wh, 5, add_days(nowdate(), -20))
		reco = _count(item, wh, 9, add_days(nowdate(), -10))

		changed = P._what_the_count_changed(reco)
		self.assertEqual(len(changed), 1)
		self.assertIn(item, changed[0])
		self.assertIn("9", changed[0])


class TestTheBalanceAtAMoment(FrappeTestCase):
	def test_it_reads_the_shelf_as_it_stood_then_not_today(self):
		item, wh = _an_item("BALANCE"), _a_warehouse()
		_receive(item, wh, 4, add_days(nowdate(), -20))
		_receive(item, wh, 6, add_days(nowdate(), -5))

		then = P._balance_at(item, wh, f"{add_days(nowdate(), -10)} 23:59:59")
		now = P._balance_at(item, wh, f"{nowdate()} 23:59:59")
		self.assertEqual(then, 4, "the second delivery had not arrived yet")
		self.assertEqual(now, 10)


class TestStockSuppliedTheDayBeforeTheBill(FrappeTestCase):
	def test_a_bill_the_books_cannot_cover_gets_a_receipt_dated_the_day_before(self):
		item, wh = _an_item("SHORT"), _a_warehouse()
		on = add_days(nowdate(), -8)
		bill = _a_draft_bill(item, wh, 2, on)

		P._supply_what_the_shelf_lacked([frappe.get_doc("Sales Invoice", bill)])

		entry = frappe.db.get_value(
			"Stock Entry", {"remarks": P.RECEIPT_NOTE.format(bill=bill)},
			["name", "posting_date", "docstatus"], as_dict=True)
		self.assertTrue(entry, "the shortfall should have been received in")
		self.assertEqual(str(entry.posting_date), add_days(on, -1),
		                 "the stock has to be on the shelf before the bill, "
		                 "not on the same day")
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(
			flt(frappe.db.get_value("Stock Entry Detail",
			                        {"parent": entry.name}, "qty")), 2)

	def test_the_bill_then_submits(self):
		item, wh = _an_item("SUBMITS"), _a_warehouse()
		bill = _a_draft_bill(item, wh, 3, add_days(nowdate(), -7))

		P._supply_what_the_shelf_lacked([frappe.get_doc("Sales Invoice", bill)])
		doc = frappe.get_doc("Sales Invoice", bill)
		doc.flags.ignore_permissions = True
		doc.submit()

		self.assertEqual(doc.docstatus, 1)

	def test_a_bill_the_shelf_already_covers_is_left_alone(self):
		item, wh = _an_item("COVERED"), _a_warehouse()
		_receive(item, wh, 10, add_days(nowdate(), -20))
		bill = _a_draft_bill(item, wh, 1, add_days(nowdate(), -6))

		before = frappe.db.count("Stock Entry")
		P._supply_what_the_shelf_lacked([frappe.get_doc("Sales Invoice", bill)])

		self.assertEqual(frappe.db.count("Stock Entry"), before,
		                 "nothing should be received in for a bill the shelf "
		                 "could already cover")


def _a_draft_serialised_bill(item_code: str, warehouse: str, imei: str,
                             on: str) -> str:
	doc = frappe.new_doc("Sales Invoice")
	doc.customer = ensure_customer()
	doc.company = _company()
	doc.set_posting_time = 1
	doc.posting_date = on
	doc.posting_time = "14:00:00"
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	doc.append("items", {"item_code": item_code, "qty": 1, "rate": 500,
	                     "warehouse": warehouse, "use_serial_batch_fields": 1,
	                     "serial_no": imei})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


class TestACountStandingInFrontOfABill(FrappeTestCase):
	"""The whole point: a bill dated before a count, and whether it gets through."""

	def test_a_count_that_recorded_nothing_is_cancelled_and_the_bill_submits(self):
		item, wh = _a_serialised_item("BLOCKED"), _a_warehouse()
		imeis = [_an_imei(), _an_imei()]
		_receive_serialised(item, wh, imeis, add_days(nowdate(), -20))
		bill = _a_draft_serialised_bill(item, wh, imeis[0], add_days(nowdate(), -15))
		reco = _count_serialised(item, wh, imeis[::-1], add_days(nowdate(), -10))

		blocked = P._drop_counts_that_counted_nothing(
			[frappe.get_doc("Sales Invoice", bill)])

		self.assertEqual(frappe.db.get_value("Stock Reconciliation", reco, "docstatus"), 2,
		                 "a count recording nothing should not be left blocking bills")
		self.assertEqual(blocked, {}, "nothing should still be reported as blocked")

		doc = frappe.get_doc("Sales Invoice", bill)
		doc.flags.ignore_permissions = True
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_a_real_count_stands_and_the_bill_is_named_instead(self):
		item, wh = _a_serialised_item("REALCOUNT"), _a_warehouse()
		imeis = [_an_imei(), _an_imei()]
		_receive_serialised(item, wh, imeis, add_days(nowdate(), -20))
		bill = _a_draft_serialised_bill(item, wh, imeis[0], add_days(nowdate(), -15))
		# One of the two pieces was not on the shelf: a genuine correction.
		reco = _count_serialised(item, wh, [imeis[1]], add_days(nowdate(), -10))

		blocked = P._drop_counts_that_counted_nothing(
			[frappe.get_doc("Sales Invoice", bill)])

		self.assertEqual(frappe.db.get_value("Stock Reconciliation", reco, "docstatus"), 1,
		                 "a count that corrected something must not be cancelled")
		self.assertIn(bill, blocked, "the bill behind it has to be named")
		self.assertEqual(blocked[bill][0][0], reco)


class TestTheBillsThemselvesAreNeverTouched(FrappeTestCase):
	"""The counter submits the bills; the patch only clears the way."""

	def test_the_patch_never_writes_to_a_sales_invoice(self):
		source = _source()
		self.assertNotIn('set_value("Sales Invoice"', source)
		self.assertNotIn(".save(", source)
		self.assertNotIn(".submit()", source.replace("entry.submit()", ""),
		                 "the only thing this patch submits is the receipt it "
		                 "creates — a bill's date, number, customer and amounts "
		                 "must survive untouched")

	def test_it_only_ever_cancels_a_count_that_recorded_nothing(self):
		source = _source()
		cancel = source.index("doc.cancel()")
		guard = source.index("if changed:")
		self.assertLess(guard, cancel,
		                "the real-count check has to come before the cancel")

	def test_it_is_registered_to_run_on_a_live_site(self):
		listed = open(frappe.get_app_path("a3_retail", "patches.txt"),
		              encoding="utf-8").read()
		self.assertIn("a3_retail.patches.late_bills_the_count_locked_out", listed)
