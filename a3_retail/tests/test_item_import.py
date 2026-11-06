# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Bringing a catalogue in from a spreadsheet.

The point of the screen is that nothing is written until the person has seen
what would happen, so most of what is worth testing is the checking — which
costs nothing to run because it writes nothing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.api import item_import


class TestHeadings(FrappeTestCase):
	"""Nobody relabels their columns to suit us."""

	def test_a_heading_is_matched_however_it_is_written(self):
		for heading in ("Item Name", "item name", "ITEM  NAME", "Item Name.", "Product"):
			mapping, _ignored = item_import._map_columns([heading])
			self.assertEqual(mapping.get("item_name"), 0, heading)

	def test_the_usual_other_names_for_a_price(self):
		for heading in ("Sales Price", "MRP", "Selling Price", "Retail Price", "Price"):
			mapping, _ignored = item_import._map_columns([heading])
			self.assertEqual(mapping.get("selling_rate"), 0, heading)
		for heading in ("Purchase Price", "Cost", "Buying Price", "Purchase Rate"):
			mapping, _ignored = item_import._map_columns([heading])
			self.assertEqual(mapping.get("purchase_rate"), 0, heading)

	def test_a_column_nobody_asked_for_is_reported_not_guessed(self):
		mapping, ignored = item_import._map_columns(["Item Name", "Supplier Notes"])
		self.assertEqual(mapping.get("item_name"), 0)
		self.assertEqual(ignored, ["Supplier Notes"])

	def test_one_heading_claims_one_field(self):
		"""Two columns both called Price must not both become the sales price."""
		mapping, ignored = item_import._map_columns(["Price", "Price"])
		self.assertEqual(mapping.get("selling_rate"), 0)
		self.assertEqual(ignored, ["Price"])


class TestFigures(FrappeTestCase):
	def test_a_figure_is_read_the_way_a_sheet_writes_it(self):
		self.assertEqual(item_import._number("1,299.00"), 1299.0)
		self.assertEqual(item_import._number("₹ 9,200"), 9200.0)
		self.assertEqual(item_import._number("450"), 450.0)

	def test_an_empty_cell_is_nothing_and_that_is_allowed(self):
		self.assertEqual(item_import._number(""), 0.0)
		self.assertEqual(item_import._number("   "), 0.0)

	def test_words_in_a_price_column_are_a_mistake_not_a_zero(self):
		"""Importing "call us" as a price of zero is how an item ends up free."""
		self.assertIsNone(item_import._number("call us"))
		self.assertIsNone(item_import._number("-"))
		self.assertIsNone(item_import._number("n/a"))

	def test_yes_and_no_in_the_words_people_use(self):
		for word in ("Yes", "y", "TRUE", "1", "IMEI", "serialised"):
			self.assertEqual(item_import._truthy(word), 1, word)
		for word in ("No", "n", "false", "0", "", "-"):
			self.assertEqual(item_import._truthy(word), 0, word)

	def test_anything_else_is_asked_about_rather_than_assumed(self):
		self.assertIsNone(item_import._truthy("maybe"))
		self.assertIsNone(item_import._truthy("sometimes"))


class TestPreview(FrappeTestCase):
	"""The whole screen in one call: read it, check it, write nothing."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		# india_compliance can be set to insist on an HSN, and on this client's
		# site it is. A row that is meant to be the good one has to carry a real
		# code, or the test is only asserting that the site refuses it.
		cls.hsn = frappe.db.get_value("GST HSN Code", {}, "name") or ""

	def _sheet(self, rows):
		from frappe.utils.xlsxutils import make_xlsx

		saved = frappe.get_doc({
			"doctype": "File",
			"file_name": "_t_item_import.xlsx",
			"is_private": 1,
			"content": make_xlsx(rows, "Items").getvalue(),
		})
		saved.flags.ignore_permissions = True
		saved.save()
		self.addCleanup(frappe.delete_doc, "File", saved.name, force=True)
		return saved.file_url

	def test_a_sheet_without_a_name_column_is_refused_up_front(self):
		"""Not row by row — the sheet is simply not the right shape."""
		url = self._sheet([["Category", "Price"], [self.group, "100"]])
		with self.assertRaises(frappe.ValidationError):
			item_import.preview(file_url=url)

	def test_every_kind_of_bad_row_is_named_and_nothing_is_written(self):
		before = frappe.db.count("Item")
		url = self._sheet([
			["Item Name", "Item Code", "Category", "HSN Code", "Unit", "Purchase Price",
			 "Sales Price", "Opening Stock", "Has IMEI", "Notes"],
			["_T Import Good", "_TIMP1", self.group, self.hsn, "Nos", "100", "200", "", "No", "x"],
			["", "_TIMP2", self.group, self.hsn, "Nos", "1", "2", "", "No", ""],
			["_T Import Bad Group", "_TIMP3", "NOT A CATEGORY", self.hsn, "Nos",
			 "1", "2", "", "No", ""],
			["_T Import Good", "_TIMP1", self.group, self.hsn, "Nos", "1", "2", "", "No", ""],
			["_T Import Bad Price", "_TIMP5", self.group, self.hsn, "Nos",
			 "call us", "2", "", "No", ""],
			["_T Import Bad Imei", "_TIMP6", self.group, self.hsn, "Nos",
			 "1", "2", "", "maybe", ""],
		])
		got = item_import.preview(file_url=url)

		self.assertEqual(frappe.db.count("Item"), before,
		                 "a preview must not create anything")
		self.assertEqual(got["ready"], 1)
		self.assertEqual(got["blocked"], 5)
		self.assertEqual(got["ignored"], ["Notes"])

		by_row = {row["row"]: row for row in got["rows"]}
		self.assertTrue(by_row[2]["ok"])
		self.assertIn("No item name", by_row[3]["problems"])
		self.assertIn("category", " ".join(by_row[4]["problems"]))
		# the row number quoted is the one the person sees in their own sheet
		self.assertIn("row 2", " ".join(by_row[5]["problems"]))
		self.assertIn("not a number", " ".join(by_row[6]["problems"]))
		self.assertIn("Yes or a No", " ".join(by_row[7]["problems"]))

	def test_a_service_is_brought_in_as_a_service(self):
		"""A labour charge is bought and sold but never counted."""
		url = self._sheet([
			["Item Type", "Item Name", "Category", "HSN Code", "Unit", "Sales Price"],
			["Service", "_T Import Fitting", self.group, self.hsn, "Nos", "250"],
			["Product", "_T Import Charger", self.group, self.hsn, "Nos", "250"],
		])
		got = item_import.preview(file_url=url)
		by_row = {row["row"]: row for row in got["rows"]}
		self.assertTrue(by_row[2]["ok"])
		self.assertEqual(by_row[2]["is_service"], 1)
		self.assertEqual(by_row[3]["is_service"], 0)

	def test_a_service_cannot_be_counted(self):
		"""Nothing stops somebody putting a quantity against a labour charge in
		a spreadsheet, so the preview does."""
		url = self._sheet([
			["Item Type", "Item Name", "Category", "HSN Code", "Unit", "Opening Stock"],
			["Service", "_T Import Counted Service", self.group, self.hsn, "Nos", "5"],
		])
		got = item_import.preview(file_url=url)
		self.assertEqual(got["ready"], 0)
		self.assertIn("not counted", " ".join(got["rows"][0]["problems"]))

	def test_anything_else_in_the_type_column_is_queried(self):
		url = self._sheet([
			["Item Type", "Item Name", "Category", "HSN Code", "Unit"],
			["Widget", "_T Import Odd Type", self.group, self.hsn, "Nos"],
		])
		got = item_import.preview(file_url=url)
		self.assertEqual(got["ready"], 0)
		self.assertIn("Product or Service", " ".join(got["rows"][0]["problems"]))

	def test_an_imei_item_cannot_be_given_opening_stock_here(self):
		"""Six handsets need six IMEIs, and a spreadsheet column has nowhere to
		put them — those come in on a purchase."""
		url = self._sheet([
			["Item Name", "Category", "HSN Code", "Unit", "Opening Stock", "Has IMEI"],
			["_T Import Handset", self.group, self.hsn, "Nos", "6", "Yes"],
		])
		got = item_import.preview(file_url=url)
		self.assertEqual(got["ready"], 0)
		self.assertIn("purchase", " ".join(got["rows"][0]["problems"]).lower())

	def test_an_empty_sheet_says_so(self):
		url = self._sheet([["Item Name", "Category"]])
		got = item_import.preview(file_url=url)
		self.assertEqual(got["rows"], [])
		self.assertEqual(got["ready"], 0)


class TestGoogleSheet(FrappeTestCase):
	def test_only_google_is_ever_fetched(self):
		"""This runs on the server, so an address typed into the box must not be
		able to make it open something inside the network."""
		for address in ("http://169.254.169.254/latest/meta-data/",
		                "https://example.com/spreadsheets/d/abc",
		                "file:///etc/passwd",
		                "http://localhost:8000/api/method/frappe.ping"):
			with self.assertRaises(frappe.ValidationError, msg=address):
				item_import._rows_from_sheet(address)

	def test_a_google_address_with_no_sheet_in_it_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			item_import._rows_from_sheet("https://docs.google.com/document/d/abc/edit")


class TestTheScreen(FrappeTestCase):
	"""The checking above is worth nothing if the button never opens the dialog.

	It did not: a refactor of the stock-adjustment lines deleted `openImport`,
	`readSheet` and the state they share, leaving the `paintPreview` that draws
	the result behind and the Import Items button wired to a function that was
	no longer there. Every test in this file still passed, because none of them
	looked at the screen.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.js = open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_stock.js"), encoding="utf-8").read()

	def test_the_button_exists_and_is_offered_to_whoever_may_make_an_item(self):
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "stock.html"), encoding="utf-8").read()
		self.assertIn('data-do="import"', markup)
		self.assertIn('"import": "create_item"', self.js,
		              "the catalogue is shared, so making an item is the permission")

	def test_pressing_it_opens_the_dialog(self):
		self.assertIn('if (what === "import") return openImport();', self.js)
		self.assertIn("async function openImport()", self.js)

	def test_the_three_halves_of_the_screen_are_all_present(self):
		"""Reading the sheet, drawing the result and sending it are separate
		functions that call each other; any one of them missing is a dead end."""
		for part in ("async function openImport()", "async function readSheet(",
		             "function paintPreview()"):
			self.assertIn(part, self.js, part)
		self.assertIn("paintPreview();", self.js, "reading the sheet draws the result")
		self.assertIn("await readSheet(file, \"\")", self.js, "choosing a file reads it")

	def test_the_screen_calls_every_endpoint_the_importer_offers(self):
		for method in ("spec", "preview", "commit", "template", "problem_sheet"):
			self.assertIn(f"a3_retail.api.item_import.{method}", self.js, method)

	def test_nothing_can_be_imported_before_the_sheet_has_been_read(self):
		"""The dialog opens with no sheet in it, so the button that writes to the
		catalogue starts dead and only the preview may wake it."""
		opener = self.js[self.js.index("async function openImport()"):
		                 self.js.index("async function readSheet(")]
		self.assertIn('$("work-go").disabled = true;', opener)
		self.assertIn("Nothing is ready to import yet.", opener)
		self.assertIn('$("work-go").disabled = !got.ready;', self.js,
		              "the preview decides whether there is anything to send")

	def test_a_dialog_opened_after_the_importer_is_not_left_dead(self):
		"""`openImport` switches the submit button off. Every other dialog shares
		that button, so opening one has to switch it back on — otherwise closing
		the importer and reaching for Move Stock finds a button that does
		nothing, which is the bug this screen already had once."""
		work = self.js[self.js.index("function openWork("):self.js.index("function say(")]
		self.assertIn('$("work-go").disabled = false;', work)
