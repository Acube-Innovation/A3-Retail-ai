# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase


class TestDemurrageCharge(FrappeTestCase):
	def test_doctype_exists(self):
		import frappe

		self.assertTrue(frappe.db.exists("DocType", "Demurrage Charge"))
