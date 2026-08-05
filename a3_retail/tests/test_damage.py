# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Damage reports, demurrage and dead stock (scope step 18, sections 6.3 – 6.5)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.a3_retail_operations.doctype.stock_damage_report.stock_damage_report import (
	APPROVED,
	DISPOSED,
	MOVED,
	PENDING,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_salary_structure, ensure_stock

ITEM = "ACC-TGL-A55"


def make_damage(**overrides):
	branch = ensure_branch("Kochi", "KCH")
	qty = overrides.pop("qty", 5)
	ensure_stock(ITEM, branch.default_warehouse, qty=qty + 20, rate=120)

	doc = frappe.new_doc("Stock Damage Report")
	doc.branch = branch.branch
	doc.report_date = nowdate()
	doc.damage_type = overrides.pop("damage_type", "Handling Damage")
	doc.discovered_during = "Routine Inspection"
	doc.source_warehouse = branch.default_warehouse
	doc.responsibility = overrides.pop("responsibility", "Company (No Recovery)")
	items = overrides.pop("items", [{"item_code": ITEM, "qty": qty, "valuation_rate": 120}])
	doc.update(overrides)
	for row in items:
		doc.append("items", row)
	doc.flags.ignore_permissions = True
	return doc


class TestDamageReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_naming_carries_the_branch(self):
		doc = make_damage()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("DMG-KCH-"), doc.name)

	def test_totals_are_summed_from_rows(self):
		doc = make_damage(qty=5)
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.total_qty), 5.0)
		self.assertEqual(flt(doc.total_value), 600.0)

	def test_valuation_defaults_from_the_bin(self):
		doc = make_damage(items=[{"item_code": ITEM, "qty": 2}])
		doc.insert(ignore_permissions=True)
		self.assertGreater(flt(doc.items[0].valuation_rate), 0)

	def test_small_loss_needs_only_a_branch_manager(self):
		doc = make_damage(qty=5)  # 600
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.required_approver(), "Branch Manager")
		self.assertFalse(doc.needs_ho_approval)

	def test_mid_value_loss_escalates_to_head_office(self):
		doc = make_damage(items=[{"item_code": ITEM, "qty": 50, "valuation_rate": 120}])
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.required_approver(), "A3 Retail Admin")
		self.assertTrue(doc.needs_ho_approval)

	def test_large_loss_needs_accounts(self):
		doc = make_damage(items=[{"item_code": ITEM, "qty": 300, "valuation_rate": 120}])
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.required_approver(), "Accounts Manager")

	def test_recovery_above_the_loss_is_rejected(self):
		doc = make_damage(qty=5, responsibility="Employee")
		doc.is_recoverable = 1
		doc.recovery_amount = 5000
		doc.responsible_employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_employee_recovery_needs_an_employee(self):
		doc = make_damage(qty=5, responsibility="Employee")
		doc.is_recoverable = 1
		doc.recovery_amount = 100
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_submit_moves_to_pending(self):
		doc = make_damage()
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, PENDING)

	def test_a_report_without_items_is_blocked(self):
		doc = make_damage(items=[])
		doc.items = []
		self.assertRaises(frappe.MandatoryError, doc.insert)


class TestDamageProcessing(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _pending(self, qty=3):
		doc = make_damage(qty=qty)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc

	def test_approval_moves_stock_to_the_damaged_warehouse(self):
		doc = self._pending()
		damaged = self.branch.damaged_warehouse
		before = _bin(ITEM, damaged)

		doc.approve()
		doc.reload()

		self.assertIn(doc.status, (MOVED, "Recovered"))
		self.assertTrue(doc.stock_entry_transfer)
		self.assertEqual(_bin(ITEM, damaged), before + 3)

	def test_approval_removes_stock_from_the_store(self):
		doc = self._pending()
		store = self.branch.default_warehouse
		before = _bin(ITEM, store)

		doc.approve()
		self.assertEqual(_bin(ITEM, store), before - 3)

	def test_approving_twice_is_a_noop(self):
		doc = self._pending()
		first = doc.approve().stock_entry_transfer
		doc.reload()
		self.assertEqual(doc.move_to_damaged(), first)

	def test_scrap_writes_the_goods_off(self):
		doc = self._pending()
		doc.approve()
		doc.reload()
		damaged = self.branch.damaged_warehouse
		before = _bin(ITEM, damaged)

		doc.scrap()
		doc.reload()

		self.assertEqual(doc.status, DISPOSED)
		self.assertTrue(doc.stock_entry_writeoff)
		self.assertEqual(_bin(ITEM, damaged), before - 3)

	def test_scrap_before_approval_is_blocked(self):
		doc = self._pending()
		self.assertRaises(frappe.ValidationError, doc.scrap)

	def test_employee_recovery_creates_a_salary_deduction(self):
		employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
		ensure_salary_structure(employee)
		doc = make_damage(qty=3, responsibility="Employee")
		doc.is_recoverable = 1
		doc.recovery_amount = 200
		doc.recovery_mode = "Salary Deduction"
		doc.responsible_employee = employee
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.approve()
		doc.reload()

		self.assertTrue(doc.additional_salary, "no Additional Salary was raised")
		deduction = frappe.get_doc("Additional Salary", doc.additional_salary)
		self.assertEqual(flt(deduction.amount), 200.0)
		self.assertEqual(deduction.employee, employee)


def _bin(item_code: str, warehouse: str) -> float:
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	)


class TestDemurrage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _charge(self, **overrides):
		doc = frappe.new_doc("Demurrage Charge")
		doc.charge_type = overrides.pop("charge_type", "Transporter Demurrage")
		doc.branch = "Kochi"
		doc.party_type = overrides.pop("party_type", "Supplier")
		doc.party = overrides.pop("party", frappe.db.get_value("Supplier", {}, "name"))
		doc.arrival_date = overrides.pop("arrival_date", add_days(nowdate(), -5))
		doc.free_days = overrides.pop("free_days", 2)
		doc.rate_per_day = overrides.pop("rate_per_day", 500)
		doc.payable_or_recoverable = "Payable by Company"
		doc.update(overrides)
		doc.flags.ignore_permissions = True
		return doc

	def test_chargeable_days_exclude_the_free_period(self):
		doc = self._charge(arrival_date=add_days(nowdate(), -5), free_days=2,
		                   actual_clearance_date=nowdate())
		doc.insert(ignore_permissions=True)
		# Free until day -3, cleared today => 3 chargeable days.
		self.assertEqual(doc.chargeable_days, 3)
		self.assertEqual(flt(doc.charge_amount), 1500.0)

	def test_clearance_within_free_period_costs_nothing(self):
		doc = self._charge(arrival_date=add_days(nowdate(), -1), free_days=5,
		                   actual_clearance_date=nowdate())
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.chargeable_days, 0)
		self.assertEqual(flt(doc.charge_amount), 0.0)

	def test_gst_is_added_when_applicable(self):
		doc = self._charge(actual_clearance_date=nowdate(), gst_applicable=1)
		doc.insert(ignore_permissions=True)
		self.assertEqual(flt(doc.tax_amount), round(flt(doc.charge_amount) * 0.18, 2))
		self.assertEqual(
			flt(doc.total_amount), flt(doc.charge_amount) + flt(doc.tax_amount)
		)

	def test_free_until_date_is_derived(self):
		doc = self._charge(arrival_date="2026-08-01", free_days=2)
		doc.insert(ignore_permissions=True)
		self.assertEqual(str(doc.free_until_date), "2026-08-03")

	def test_storage_charges_are_raised_for_uncollected_devices(self):
		from a3_retail.a3_retail_operations.doctype.demurrage_charge.demurrage_charge import (
			raise_storage_charges,
		)
		from a3_retail.a3_retail_service.doctype.service_job_card import state as st
		from a3_retail.tests.test_service_flow import ready_job_card

		job = ready_job_card()
		# Pretend it has been sitting on the shelf for three weeks.
		frappe.db.set_value("Service Job Card", job.name, "ready_on", add_days(nowdate(), -21),
		                    update_modified=False)

		raise_storage_charges()

		charge = frappe.db.get_value(
			"Demurrage Charge",
			{"reference_type": "Service Job Card", "reference_name": job.name},
			["name", "charge_type", "chargeable_days"],
			as_dict=True,
		)
		self.assertTrue(charge, "no storage charge was raised")
		self.assertEqual(charge.charge_type, "Customer Device Storage")
		self.assertGreater(charge.chargeable_days, 0)


class TestDeadStock(FrappeTestCase):
	def test_dead_stock_query_runs(self):
		from a3_retail.a3_retail_operations.doctype.demurrage_charge.demurrage_charge import dead_stock

		rows = dead_stock(days=1)
		self.assertIsInstance(rows, list)
		for row in rows:
			self.assertIn("item_code", row)
			self.assertIn("actual_qty", row)
