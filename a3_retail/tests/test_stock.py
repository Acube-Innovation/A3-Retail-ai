# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Stock explorer, stock requests and in-transit transfers (scope step 17, doc 06)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.a3_retail_sales.doctype.stock_request.stock_request import (
	APPROVED,
	IN_TRANSIT,
	PENDING,
	RECEIVED,
	REJECTED,
)
from a3_retail.api.stock import availability_matrix, search_items, serial_list
from a3_retail.tests.fixtures import ensure_branch, ensure_stock

PART = "SPR-BAT-N13"
ACCESSORY = "ACC-TGL-A55"


def make_request(**overrides):
	ensure_branch("Kochi", "KCH")
	ensure_branch("Thiruvananthapuram", "TVM")

	doc = frappe.new_doc("Stock Request")
	doc.requesting_branch = overrides.pop("requesting_branch", "Kochi")
	doc.source_branch = overrides.pop("source_branch", "Thiruvananthapuram")
	doc.purpose = overrides.pop("purpose", "Stock Balancing")
	items = overrides.pop("items", [{"item_code": PART, "qty": 2}])
	doc.update(overrides)
	for row in items:
		doc.append("items", row)
	doc.flags.ignore_permissions = True
	return doc


class TestStockExplorerApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_search_returns_branch_quantity(self):
		rows = search_items("Tempered", branch="Kochi")
		self.assertTrue(rows)
		self.assertEqual(rows[0]["item_code"], ACCESSORY)
		self.assertGreater(flt(rows[0]["branch_qty"]), 0)

	def test_only_in_stock_filter(self):
		rows = search_items("", filters={"only_in_stock": 1}, branch="Kochi")
		for row in rows:
			self.assertGreater(flt(row["branch_qty"]), 0)

	def test_availability_matrix_spans_branches(self):
		rows = availability_matrix(ACCESSORY)
		branches = {row["branch"] for row in rows}
		self.assertIn("Kochi", branches)
		self.assertIn("Thiruvananthapuram", branches)

	def test_matrix_reports_available_net_of_reserved(self):
		rows = availability_matrix(ACCESSORY)
		for row in rows:
			self.assertEqual(
				flt(row["available"]), flt(row["actual_qty"]) - flt(row["reserved_qty"])
			)

	def test_managers_see_valuation(self):
		# Administrator holds every role, so valuation must be present.
		rows = availability_matrix(ACCESSORY)
		self.assertTrue(all("stock_value" in row for row in rows))

	def test_serial_list_reports_age(self):
		serials = serial_list("MOB-SAM-A55-8-128-BLU", limit=5)
		self.assertTrue(serials)
		for serial in serials:
			self.assertIn("age_days", serial)
			self.assertGreaterEqual(serial["age_days"], 0)


class TestStockRequestValidation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		ensure_branch("Thiruvananthapuram", "TVM")
		frappe.db.commit()

	def test_naming_carries_the_requesting_branch(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("SR-KCH-"), doc.name)

	def test_same_branch_transfer_is_rejected(self):
		doc = make_request(source_branch="Kochi")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_warehouses_default_from_branch_profiles(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		self.assertIn("Kochi", doc.requesting_warehouse)
		self.assertIn("Thiruvananthapuram", doc.source_warehouse)
		self.assertTrue(doc.transit_warehouse)

	def test_service_purpose_targets_the_service_bay(self):
		doc = make_request(purpose="Service Job Card")
		doc.insert(ignore_permissions=True)
		self.assertIn("Service Bay", doc.requesting_warehouse)

	def test_available_quantity_is_pulled_from_the_source(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		self.assertGreater(flt(doc.items[0].available_at_source), 0)

	def test_total_value_is_computed(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		self.assertGreater(flt(doc.total_value), 0)

	def test_a_request_without_items_is_blocked(self):
		doc = make_request(items=[])
		doc.items = []
		# `items` is mandatory, so an empty request never reaches submit.
		self.assertRaises(frappe.MandatoryError, doc.insert)


class TestApprovalMatrix(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		ensure_branch("Thiruvananthapuram", "TVM")
		frappe.db.commit()

	def test_small_service_request_auto_approves(self):
		doc = make_request(purpose="Service Job Card", items=[{"item_code": PART, "qty": 1}])
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, APPROVED)

	def test_stock_balancing_needs_approval(self):
		doc = make_request(purpose="Stock Balancing")
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, PENDING)

	def test_high_value_flags_head_office(self):
		doc = make_request(items=[{"item_code": "SPR-DSP-A55", "qty": 10}])
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.needs_ho_approval, f"value was {doc.total_value}")

	def test_approve_records_the_approver(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.approve()

		doc.reload()
		self.assertEqual(doc.status, APPROVED)
		self.assertEqual(doc.approved_by, "Administrator")
		self.assertTrue(doc.approved_on)

	def test_reject_records_the_reason(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reject("No spare stock")

		doc.reload()
		self.assertEqual(doc.status, REJECTED)
		self.assertEqual(doc.rejection_reason, "No spare stock")

	def test_dispatch_before_approval_is_blocked(self):
		doc = make_request()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertRaises(frappe.ValidationError, doc.dispatch)


class TestInTransitTransfer(FrappeTestCase):
	"""Scope step 17 acceptance: in-transit balance returns to zero on receipt."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		ensure_branch("Thiruvananthapuram", "TVM")
		frappe.db.commit()

	def _approved(self, qty=2):
		# Provision the source: the suite really does consume stock.
		source = ensure_branch("Thiruvananthapuram", "TVM")
		ensure_stock(PART, source.service_warehouse, qty=qty + 10)
		doc = make_request(items=[{"item_code": PART, "qty": qty}])
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.approve()
		doc.reload()
		return doc

	def test_dispatch_moves_stock_into_transit(self):
		doc = self._approved()
		transit = doc.transit_warehouse
		before = _bin(PART, transit)

		doc.dispatch()
		doc.reload()

		self.assertEqual(doc.status, IN_TRANSIT)
		self.assertTrue(doc.outward_stock_entry)
		self.assertEqual(_bin(PART, transit), before + 2)

	def test_receive_empties_transit_and_lands_the_stock(self):
		doc = self._approved()
		transit = doc.transit_warehouse
		target = doc.requesting_warehouse

		transit_before = _bin(PART, transit)
		target_before = _bin(PART, target)

		doc.dispatch()
		doc.reload()
		doc.receive()
		doc.reload()

		self.assertEqual(doc.status, RECEIVED)
		self.assertTrue(doc.inward_stock_entry)
		# In-transit balance is back where it started; the stock arrived.
		self.assertEqual(_bin(PART, transit), transit_before)
		self.assertEqual(_bin(PART, target), target_before + 2)

	def test_stock_leaves_the_source_branch(self):
		doc = self._approved()
		source = doc.source_warehouse
		before = _bin(PART, source)

		doc.dispatch()
		self.assertEqual(_bin(PART, source), before - 2)

	def test_receiving_twice_is_a_noop(self):
		doc = self._approved()
		doc.dispatch()
		doc.reload()
		first = doc.receive()
		doc.reload()
		self.assertEqual(doc.receive(), first)

	def test_receive_before_dispatch_is_blocked(self):
		doc = self._approved()
		self.assertRaises(frappe.ValidationError, doc.receive)

	def test_transit_days_are_recorded(self):
		doc = self._approved()
		doc.dispatch()
		doc.reload()
		doc.receive()
		doc.reload()
		self.assertIsNotNone(doc.transit_days)


def _bin(item_code: str, warehouse: str) -> float:
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	)


class TestExplorerPage(FrappeTestCase):
	def test_page_is_registered_and_open_to_branch_staff(self):
		self.assertTrue(frappe.db.exists("Page", "a3-stock-explorer"))
		roles = set(
			frappe.get_all(
				"Has Role",
				filters={"parent": "a3-stock-explorer", "parenttype": "Page"},
				pluck="role",
			)
		)
		# Requirement 8: every branch user can check availability.
		self.assertIn("Sales Executive", roles)
		self.assertIn("Store Keeper", roles)
		self.assertNotIn("Guest", roles)
