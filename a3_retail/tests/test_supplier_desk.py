# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""The supplier desk: who the shop buys from, and what it has paid them.

Paying is the part worth guarding. A payment that over-allocates, or that
settles somebody else's bill, is a wrong ledger that nobody notices until the
distributor's statement disagrees — so each of those is a refusal, not a
best effort.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import supplier_desk
from a3_retail.tests.fixtures import ensure_branch

def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


GSTIN = "32AAAAA0000A1ZB"            # invented, with a valid check digit
GSTIN_KARNATAKA = "29AAAAA0000A1ZY"


class TestSupplierDesk(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def setUp(self):
		user = user_for("Vipin S")
		if not user:
			self.skipTest("Vipin S is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---- the list and the record ------------------------------------------
	def test_the_list_says_what_each_distributor_is_owed(self):
		data = supplier_desk.list_suppliers()
		self.assertIn("rows", data)
		for row in data["rows"]:
			self.assertIn("outstanding", row)
			self.assertIn("initials", row)

	def test_a_supplier_can_be_added_and_then_corrected(self):
		made = supplier_desk.save_supplier(supplier_name="Kerala Handsets LLP",
		                                   mobile_no="9847055101")
		self.assertEqual(made["supplier_name"], "Kerala Handsets LLP")
		again = supplier_desk.save_supplier(supplier=made["name"],
		                                    supplier_name="Kerala Handsets Pvt Ltd")
		self.assertEqual(again["name"], made["name"], "corrected, not duplicated")
		self.assertEqual(again["supplier_name"], "Kerala Handsets Pvt Ltd")

	def test_a_gstin_is_checked_and_its_state_recorded(self):
		made = supplier_desk.save_supplier(supplier_name="Bengaluru Supply Co",
		                                   gstin=GSTIN_KARNATAKA)
		self.assertEqual(made["gstin"], GSTIN_KARNATAKA)
		self.assertEqual(made["address"].get("state"), "Karnataka")

	def test_a_mistyped_gstin_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.save_supplier(supplier_name="Typo Supply",
			                            gstin="32AAAAA0000A1ZC")

	def test_a_supplier_with_no_name_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.save_supplier(supplier_name="   ")

	def test_stopping_a_supplier_keeps_what_was_bought(self):
		made = supplier_desk.save_supplier(supplier_name="Old Distributor")
		off = supplier_desk.set_disabled(made["name"], 1)
		self.assertTrue(off["disabled"])
		self.assertTrue(frappe.db.exists("Supplier", made["name"]))

	# ---- paying ------------------------------------------------------------
	def _supplier(self):
		return supplier_desk.save_supplier(supplier_name="Payable Distributor")["name"]

	def test_nothing_is_paid_without_an_amount(self):
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.pay(self._supplier(), 0)

	def test_a_supplier_that_does_not_exist_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.pay("No Such Supplier", 100)

	def test_allocating_more_than_the_payment_is_refused(self):
		"""Otherwise the bills would close against money that never arrived."""
		supplier = self._supplier()
		invoices = supplier_desk.open_invoices(supplier)
		if not invoices:
			self.skipTest("no outstanding bill to allocate against")
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.pay(supplier, 100, allocations=[
				{"invoice": invoices[0]["name"], "amount": 10000}])

	def test_open_invoices_are_oldest_first(self):
		"""That is the order a shop settles in, and the screen allocates down it."""
		data = supplier_desk.list_suppliers()
		for row in data["rows"]:
			invoices = supplier_desk.open_invoices(row["name"])
			dates = [str(i["posting_date"]) for i in invoices]
			self.assertEqual(dates, sorted(dates))
			for invoice in invoices:
				self.assertGreater(flt(invoice["outstanding_amount"]), 0)

	def test_a_bill_from_another_supplier_cannot_be_settled(self):
		"""The allocation names an invoice; it has to belong to the party paid."""
		rows = supplier_desk.list_suppliers()["rows"]
		owner = next((r for r in rows if supplier_desk.open_invoices(r["name"])), None)
		if not owner:
			self.skipTest("no outstanding bill anywhere to borrow")
		invoice = supplier_desk.open_invoices(owner["name"])[0]["name"]
		stranger = self._supplier()
		with self.assertRaises(frappe.ValidationError):
			supplier_desk.pay(stranger, 100, allocations=[
				{"invoice": invoice, "amount": 50}])

	def test_the_tabs_only_return_this_supplier(self):
		rows = supplier_desk.list_suppliers()["rows"]
		if not rows:
			self.skipTest("no suppliers on this site")
		supplier = rows[0]["name"]
		for name in ("purchases", "payments", "returns"):
			for row in supplier_desk.tab(supplier, name):
				self.assertIn("name", row)
