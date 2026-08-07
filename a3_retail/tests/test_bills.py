# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Bills, the invoice view, and editing a draft at the counter."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import bills, pos
from a3_retail.tests.fixtures import ensure_branch


def user_for(employee_name: str) -> str | None:
	return frappe.db.get_value("Employee", {"employee_name": employee_name}, "user_id")


class TestBillsPages(FrappeTestCase):
	def test_both_pages_are_standalone_documents(self):
		folder = frappe.get_app_path("a3_retail", "www", "branch")
		for name in ("bills.html", "bills.py", "invoice.html", "invoice.py"):
			self.assertTrue(os.path.exists(os.path.join(folder, name)), name)

		for page, script in (("bills.html", "a3_bills.js"), ("invoice.html", "a3_invoice.js")):
			markup = open(os.path.join(folder, page)).read()
			self.assertIn("<!doctype html>", markup.lower())
			self.assertNotIn("{% extends", markup)
			self.assertIn(f"/assets/a3_retail/js/{script}", markup)
			self.assertIn("a3_branch.css?v={{ asset_v }}", markup)

	def test_the_list_has_the_filter_bar_the_shop_asked_for(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "bills.html")
		).read()
		for piece in ("Manage invoices, payments and customer billing", "New Sale", "Export",
		              "Refresh", "Search invoice no, customer, phone", "Clear filters",
		              "Partially Paid", "Payment mode", "All branches"):
			self.assertIn(piece, markup, piece)

	def test_new_sale_goes_to_the_counter_that_already_exists(self):
		markup = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "bills.html")
		).read()
		self.assertIn('href="/branch/sales"', markup)

	def test_bills_is_a_live_entry_in_the_sidebar(self):
		sidebar = open(
			os.path.join(frappe.get_app_path("a3_retail", "www", "branch"), "_sidebar.html")
		).read()
		self.assertIn('("bills", "Bills", "/branch/bills"', sidebar)

	def test_there_is_one_print_implementation(self):
		"""Bills, the invoice page and the counter all print the same document."""
		folder = frappe.get_app_path("a3_retail", "public", "js")
		for script in ("a3_bills.js", "a3_invoice.js"):
			body = open(os.path.join(folder, script)).read()
			self.assertIn("Retail%20Tax%20Invoice", body) if script == "a3_bills.js" \
				else self.assertIn("print_url", body)
			self.assertNotIn("<table class=\"print", body, "no second print template")

		api = open(frappe.get_app_path("a3_retail", "api", "bills.py")).read()
		self.assertIn("from a3_retail.api.pos import print_url", api)


class TestBillsAccess(FrappeTestCase):
	def test_a_guest_cannot_read_the_bills(self):
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, bills.list_bills)
		finally:
			frappe.set_user("Administrator")

	def test_a_user_without_an_employee_record_is_refused(self):
		self.assertRaises(frappe.PermissionError, bills.summary)


class TestBillsList(FrappeTestCase):
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

	def test_a_row_carries_every_column_the_table_shows(self):
		page = bills.list_bills(page_size=20)
		if not page["rows"]:
			self.skipTest("no invoices in this branch")

		row = page["rows"][0]
		for key in ("name", "posting_date", "customer_name", "mobile_no", "items", "net_total",
		            "discount_amount", "total_taxes_and_charges", "payable", "paid", "balance",
		            "payment_status", "status", "sales_person", "editable"):
			self.assertIn(key, row, key)

	def test_paid_and_balance_add_up_to_the_bill(self):
		for row in bills.list_bills(page_size=20)["rows"]:
			if row["status"] == "Cancelled":
				continue
			self.assertAlmostEqual(row["paid"] + row["balance"], row["payable"], places=2)

	def test_only_a_draft_is_editable(self):
		for row in bills.list_bills(page_size=50)["rows"]:
			self.assertEqual(row["editable"], row["status"] == "Draft", row["name"])

	def test_the_page_size_is_one_of_the_three_offered(self):
		self.assertEqual(bills.list_bills(page_size=999)["page_size"], 20)
		self.assertEqual(bills.list_bills(page_size=50)["page_size"], 50)

	def test_the_status_filter_returns_only_that_status(self):
		for status in ("Paid", "Unpaid", "Draft", "Cancelled"):
			for row in bills.list_bills({"status": status}, page_size=20)["rows"]:
				if status in ("Draft", "Cancelled"):
					self.assertEqual(row["status"], status)
				else:
					self.assertEqual(row["payment_status"], status)

	def test_search_finds_a_bill_by_its_number(self):
		page = bills.list_bills(page_size=1)
		if not page["rows"]:
			self.skipTest("no invoices in this branch")
		name = page["rows"][0]["name"]
		self.assertIn(name, [row["name"] for row in bills.list_bills({"query": name})["rows"]])

	def test_the_cards_and_the_list_answer_to_the_same_filters(self):
		filters = {"status": "Paid"}
		cards = bills.summary(filters)
		listed = bills.list_bills(filters, page_size=100)
		self.assertEqual(cards["paid"]["count"], min(listed["total"], cards["paid"]["count"]))
		for key in ("total", "paid", "partly", "unpaid", "cancelled", "today"):
			self.assertIn(key, cards, key)


class TestInvoiceView(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)
		row = frappe.db.get_value(
			"Sales Invoice", {"branch": "Kochi", "docstatus": 1}, "name", order_by="creation desc"
		)
		if not row:
			self.skipTest("no submitted invoice in Kochi")
		self.invoice = row

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_view_answers_with_everything_the_page_draws(self):
		data = bills.invoice(self.invoice)
		for key in ("status", "payment_status", "editable", "customer", "items", "totals",
		            "payments", "timeline", "print_url"):
			self.assertIn(key, data, key)
		self.assertTrue(data["items"])

	def test_a_submitted_bill_is_not_editable(self):
		self.assertFalse(bills.invoice(self.invoice)["editable"])

	def test_the_totals_are_the_invoice_s_own(self):
		data = bills.invoice(self.invoice)
		doc = frappe.get_doc("Sales Invoice", self.invoice)
		self.assertAlmostEqual(data["totals"]["taxable"], flt(doc.net_total), places=2)
		self.assertAlmostEqual(data["totals"]["balance"], flt(doc.outstanding_amount), places=2)
		self.assertAlmostEqual(
			data["totals"]["paid"] + data["totals"]["balance"], data["totals"]["payable"], places=2
		)

	def test_the_print_link_is_the_counter_s_own(self):
		self.assertEqual(bills.invoice(self.invoice)["print_url"], pos.print_url(self.invoice))

	def test_a_bill_from_another_branch_is_refused(self):
		other = frappe.db.get_value(
			"Sales Invoice", {"branch": ["not in", ["Kochi", ""]], "docstatus": 1}, "name"
		)
		if not other:
			self.skipTest("no invoice outside Kochi")
		self.assertRaises(frappe.ValidationError, bills.invoice, other)


class TestDraftEditing(FrappeTestCase):
	"""A draft goes back to the counter; a submitted bill does not."""

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

	def _draft(self, **overrides) -> dict:
		payload = {
			"customer": "Rahul Krishnan",
			"notes": "Held at the counter",
			"items": [{"item_code": "ACC-TGL-A55", "qty": 2, "rate": 299, "serials": []}],
		}
		payload.update(overrides)
		return pos.save_draft(payload)

	def test_a_draft_is_a_real_invoice_that_has_not_been_submitted(self):
		draft = self._draft()
		doc = frappe.get_doc("Sales Invoice", draft["invoice"])
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(bills.invoice(doc.name)["status"], "Draft")
		self.assertTrue(bills.invoice(doc.name)["editable"])

	def test_a_draft_loads_back_into_the_counter_s_own_cart(self):
		draft = self._draft(discount_percent=10)
		loaded = pos.load_invoice(draft["invoice"])

		self.assertEqual(loaded["invoice"], draft["invoice"])
		self.assertEqual(loaded["customer"], "Rahul Krishnan")
		self.assertEqual(len(loaded["items"]), 1)
		self.assertEqual(loaded["items"][0]["item_code"], "ACC-TGL-A55")
		self.assertEqual(loaded["items"][0]["qty"], 2)
		self.assertEqual(flt(loaded["discount_percent"]), 10)
		self.assertIn("Held at the counter", loaded["notes"])

	def test_saving_an_edited_draft_updates_that_bill_rather_than_writing_another(self):
		draft = self._draft()
		before = frappe.db.count("Sales Invoice")

		loaded = pos.load_invoice(draft["invoice"])
		loaded["items"][0]["qty"] = 5
		result = pos.checkout({
			"invoice": draft["invoice"], "customer": loaded["customer"],
			"mode_of_payment": "Cash", "items": loaded["items"],
		})

		self.assertEqual(result["invoice"], draft["invoice"])
		self.assertEqual(frappe.db.count("Sales Invoice"), before)

		doc = frappe.get_doc("Sales Invoice", draft["invoice"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(flt(doc.items[0].qty), 5)

	def test_a_submitted_bill_cannot_be_loaded_for_editing(self):
		submitted = frappe.db.get_value(
			"Sales Invoice", {"branch": "Kochi", "docstatus": 1}, "name"
		)
		if not submitted:
			self.skipTest("no submitted invoice")
		self.assertRaises(frappe.ValidationError, pos.load_invoice, submitted)

	def test_a_submitted_bill_cannot_be_overwritten_through_checkout(self):
		submitted = frappe.db.get_value(
			"Sales Invoice", {"branch": "Kochi", "docstatus": 1}, "name"
		)
		if not submitted:
			self.skipTest("no submitted invoice")
		self.assertRaises(
			frappe.ValidationError, pos.checkout,
			{"invoice": submitted, "customer": "Rahul Krishnan",
			 "items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}]},
		)

	def test_the_price_the_counter_typed_is_the_price_on_the_bill(self):
		"""`set_missing_values` re-prices from the price list and used to throw
		away a rate the counter had just agreed with the customer."""
		draft = self._draft(items=[{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 275,
		                            "serials": []}])
		doc = frappe.get_doc("Sales Invoice", draft["invoice"])
		self.assertEqual(flt(doc.items[0].rate), 275)


class TestCollectingPayment(FrappeTestCase):
	def setUp(self):
		user = user_for("Arun Menon")
		if not user:
			self.skipTest("Arun Menon is not provisioned")
		frappe.set_user(user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_draft_cannot_take_a_payment(self):
		draft = pos.save_draft({
			"customer": "Rahul Krishnan",
			"items": [{"item_code": "ACC-TGL-A55", "qty": 1, "rate": 299, "serials": []}],
		})
		self.assertRaises(frappe.ValidationError, bills.collect_payment, draft["invoice"], 100)

	def test_more_than_the_balance_is_refused(self):
		row = frappe.db.get_value(
			"Sales Invoice", {"branch": "Kochi", "docstatus": 1, "outstanding_amount": [">", 0]},
			["name", "outstanding_amount"], as_dict=True,
		)
		if not row:
			self.skipTest("nothing outstanding in this branch")
		self.assertRaises(
			frappe.ValidationError, bills.collect_payment, row.name,
			flt(row.outstanding_amount) + 1000
		)

	def test_a_payment_clears_the_balance_it_was_taken_for(self):
		row = frappe.db.get_value(
			"Sales Invoice", {"branch": "Kochi", "docstatus": 1, "outstanding_amount": [">", 0]},
			["name", "outstanding_amount"], as_dict=True,
		)
		if not row:
			self.skipTest("nothing outstanding in this branch")

		result = bills.collect_payment(row.name, flt(row.outstanding_amount), "Cash")
		self.assertTrue(result["payment_entry"])
		self.assertAlmostEqual(result["balance"], 0, places=2)
		self.assertEqual(result["payment_status"], "Paid")
		self.assertIn(result["payment_entry"],
		              [p["name"] for p in bills.invoice(row.name)["payments"]])
