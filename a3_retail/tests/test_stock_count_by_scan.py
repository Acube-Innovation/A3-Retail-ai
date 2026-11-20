# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Counting a shelf by scanning every piece.

The Stock Adjustment button now asks which kind of count this is. An
**Adjustment** starts from what the system believes and the counter corrects
it. A **Reconciliation** starts from nothing and every piece is scanned, the
way ERPNext counts — which is the only way to find stock the system has never
heard of, or stock it has filed on another shelf.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt


def _js() -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js"),
	            encoding="utf-8").read()


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


def _a_serial_on_a_branch_shelf():
	from a3_retail.api.stock_control import _network_warehouses

	net = [row["warehouse"] for row in _network_warehouses()]
	if not net:
		return None, None
	rows = frappe.db.sql("""select sn.name, sn.item_code, sn.warehouse
	                        from `tabSerial No` sn
	                        where sn.status = 'Active' and sn.warehouse in %s
	                        limit 1""", (net,), as_dict=True)
	return (rows[0] if rows else None), net


class TestScanningFindsTheItem(FrappeTestCase):
	"""`search_countable` promised IMEI matching in its docstring and did not
	do it, so scanning the number off a handset found nothing at all."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.serial, self.net = _a_serial_on_a_branch_shelf()
		if not self.serial:
			self.skipTest("no active serial on a branch shelf")

	def test_an_imei_finds_its_item(self):
		from a3_retail.api.stock_control import search_countable

		hits = search_countable(query=self.serial.name,
		                        warehouse=self.serial.warehouse, limit=5)
		self.assertIn(self.serial.item_code, [h["item_code"] for h in hits])

	def test_a_name_still_finds_it(self):
		"""The serial join must not have cost the ordinary search."""
		from a3_retail.api.stock_control import search_countable

		name = frappe.db.get_value("Item", self.serial.item_code, "item_name") or ""
		if len(name) < 3:
			self.skipTest("item name too short to search on")
		hits = search_countable(query=name[:6], warehouse=self.serial.warehouse, limit=10)
		self.assertTrue(hits)

	def test_the_docstring_no_longer_promises_what_it_skips(self):
		body = _source("api", "stock_control.py")
		block = body[body.index("def search_countable("):]
		block = block[:block.index("\n@frappe.whitelist()")] if "\n@frappe.whitelist()" in block else block[:4000]
		self.assertIn("tabSerial No", block, "the IMEI match is not in the query")


class TestTheScanResolver(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.serial, self.net = _a_serial_on_a_branch_shelf()
		if not self.serial:
			self.skipTest("no active serial on a branch shelf")

	def test_a_serial_on_this_shelf(self):
		from a3_retail.api.stock_control import scan_for_count

		hit = scan_for_count(self.serial.name, self.serial.warehouse)
		self.assertEqual(hit["found"], "serial")
		self.assertEqual(hit["item_code"], self.serial.item_code)
		self.assertEqual(hit["serial_no"], self.serial.name)
		self.assertTrue(hit["here"])

	def test_a_serial_filed_on_another_shelf_is_reported_not_refused(self):
		"""A handset found here that the system files elsewhere is half of what
		a count is for. The till refuses it; a count must not."""
		from a3_retail.api.stock_control import scan_for_count

		other = next((w for w in self.net if w != self.serial.warehouse), None)
		if not other:
			self.skipTest("only one warehouse in the network")

		hit = scan_for_count(self.serial.name, other)
		self.assertEqual(hit["found"], "serial")
		self.assertFalse(hit["here"])
		self.assertEqual(hit["where"], self.serial.warehouse)

	def test_an_item_code_resolves(self):
		from a3_retail.api.stock_control import scan_for_count

		code = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0}, "name")
		hit = scan_for_count(code, self.serial.warehouse)
		self.assertEqual(hit["found"], "item")
		self.assertEqual(hit["item_code"], code)

	def test_a_barcode_resolves_to_its_item(self):
		from a3_retail.api.stock_control import scan_for_count

		row = frappe.db.get_value("Item Barcode", {}, ["barcode", "parent"], as_dict=True)
		if not row:
			self.skipTest("no barcodes on this site")
		hit = scan_for_count(row.barcode, self.serial.warehouse)
		self.assertEqual(hit["found"], "item")
		self.assertEqual(hit["item_code"], row.parent)

	def test_nonsense_is_answered_rather_than_thrown(self):
		"""The counter scans a crumpled label; that is not an error, it is a
		"no". A throw here would close the dialog and lose the count."""
		from a3_retail.api.stock_control import scan_for_count

		hit = scan_for_count("ZZZ-NOT-A-THING-AT-ALL", self.serial.warehouse)
		self.assertIsNone(hit["found"])

	def test_a_warehouse_outside_the_network_is_refused(self):
		from a3_retail.api.stock_control import scan_for_count

		outside = frappe.db.sql("""select name from `tabWarehouse`
		                           where ifnull(is_group,0)=0 and name not in %s
		                           limit 1""", (self.net,))
		if not outside:
			self.skipTest("every warehouse is in the network")
		with self.assertRaises(frappe.ValidationError):
			scan_for_count(self.serial.name, outside[0][0])

	def test_it_is_guarded_like_every_other_endpoint(self):
		body = _source("api", "stock_control.py")
		block = body[body.index("def scan_for_count("):]
		block = block[:block.index("\n@frappe.whitelist()")]
		self.assertIn("_me()", block)
		self.assertIn("require_permission(", block)


class TestTheCounterIsAskedWhichKind(FrappeTestCase):
	def test_the_dialog_offers_both_kinds(self):
		js = _js()
		self.assertIn('id="w-kind"', js)
		self.assertIn('value="count"', js)
		self.assertIn('value="scan"', js)

	def test_scanning_mode_has_a_box_of_its_own(self):
		"""Above the lines, not inside one: the person holding the gun does not
		yet know which line the next piece belongs to."""
		js = _js()
		self.assertIn('id="w-countscan"', js)
		self.assertIn('id="w-scan-row"', js)

	def test_the_gun_is_read_on_enter(self):
		js = _js()
		block = js[js.index('if (box) {'):]
		block = block[:block.index("}, 0);")]
		self.assertIn('event.key !== "Enter"', block)
		self.assertIn("scanIntoCount(code)", block)

	def test_the_two_kinds_start_from_opposite_ends(self):
		"""An adjustment starts from everything ticked; a scan starts from
		nothing. Carrying one into the other would count handsets nobody
		looked at."""
		js = _js()
		self.assertIn('workLines = [{ item_code: "", qty: scanning ? 0 : 1', js)
		# Only the ticking kind pre-fills from what the system believes.
		block = js[js.index("async function loadSerials("):]
		block = block[:block.index("\n\tfunction startLines(")]
		self.assertIn('if (workSerialMode === "count")', block)
		self.assertNotIn('"scan"', block)

	def test_a_piece_is_never_counted_twice(self):
		js = _js()
		block = js[js.index("async function scanIntoCount("):]
		block = block[:block.index("\n\tasync function loadSerials(")]
		self.assertIn("line.picked.includes(hit.serial_no)", block)
		self.assertIn("already counted", block)

	def test_a_stray_handset_is_counted_and_said_out_loud(self):
		js = _js()
		block = js[js.index("async function scanIntoCount("):]
		block = block[:block.index("\n\tasync function loadSerials(")]
		self.assertIn("if (!hit.here)", block)
		self.assertIn("is filed at", block)

	def test_an_accessory_counts_one_per_scan(self):
		"""No number of its own, so each scan is one more rather than a list."""
		js = _js()
		block = js[js.index("async function scanIntoCount("):]
		block = block[:block.index("\n\tasync function loadSerials(")]
		self.assertIn("line.qty = (Number(line.qty) || 0) + 1", block)

	def test_the_adjustment_path_is_unchanged(self):
		"""The existing kind must still post the way it always did."""
		js = _js()
		self.assertIn("a3_retail.api.stock_control.adjust_stock", js)
		self.assertIn('serials: line.serials ? line.picked : null', js)


class TestAnItemJustSwitchedToImeis(FrappeTestCase):
	"""A handset switched to IMEI tracking has no numbers on file yet.

	The count read "no IMEIs on this shelf" as "this item is not counted by
	IMEI", offered a plain quantity box, and left the numbers nowhere to go —
	which is exactly the state of every item the moment it is switched over,
	and of the first one of a model to reach a branch.
	"""

	ITEM = "A3-TEST-JUST-SERIALISED"

	def setUp(self):
		frappe.set_user("Administrator")
		self.warehouse = self._a_branch_shelf()
		self._an_item_with_no_serials_yet()

	@staticmethod
	def _a_branch_shelf():
		"""A shelf this counter may actually adjust — `adjust_stock` refuses
		another branch's, so the network list is the wrong one to pick from."""
		from a3_retail.api.staff import _me
		from a3_retail.api.stock_control import _warehouses

		mine = _warehouses(_me().branch)
		if not mine:
			raise AssertionError("this user's branch has no warehouse")
		return mine[0]

	@classmethod
	def _an_item_with_no_serials_yet(cls):
		if frappe.db.exists("Item", cls.ITEM):
			return
		src = frappe.db.get_value("Item", {"gst_hsn_code": "85171300"},
		                          ["item_group", "stock_uom"], as_dict=True)
		doc = frappe.new_doc("Item")
		doc.item_code = cls.ITEM
		doc.item_name = "Handset switched to IMEI tracking today"
		doc.item_group = src.item_group
		doc.stock_uom = src.stock_uom
		doc.gst_hsn_code = "85171300"
		doc.is_stock_item = 1
		doc.has_serial_no = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	def test_the_item_is_asked_about_itself_not_the_shelf(self):
		from a3_retail.api.stock_control import countable_serials

		out = countable_serials(self.ITEM, self.warehouse)
		self.assertTrue(out["has_serial"],
		                "an empty shelf must not read as 'not serialised'")
		self.assertEqual(out["serials"], [])

	def test_an_ordinary_item_still_says_no(self):
		from a3_retail.api.stock_control import countable_serials

		plain = frappe.db.get_value(
			"Item", {"is_stock_item": 1, "has_serial_no": 0, "disabled": 0}, "name")
		if not plain:
			self.skipTest("no unserialised stock item on this site")
		self.assertFalse(countable_serials(plain, self.warehouse)["has_serial"])

	def test_it_refuses_an_item_that_is_not_there(self):
		from a3_retail.api.stock_control import countable_serials

		with self.assertRaises(frappe.ValidationError):
			countable_serials("A3-NO-SUCH-ITEM-AT-ALL", self.warehouse)

	def test_the_screen_asks_the_item_rather_than_the_shelf(self):
		js = _js()
		self.assertIn("a3_retail.api.stock_control.countable_serials", js)
		# The old inference is what put the IMEIs nowhere.
		self.assertNotIn("line.serials = rows.length ?", js)

	def test_an_empty_list_is_not_a_dead_end_while_counting(self):
		js = _js()
		block = js[js.index("function imeiMarkup("):]
		block = block[:block.index("\n\t/** One scan,")]
		self.assertIn("nothingYet && !counting", block)

	def test_counting_a_serialised_item_without_its_numbers_is_refused(self):
		"""Posted with a bare quantity, ERPNext either refuses in its own words
		or invents numbers for handsets nobody read."""
		from a3_retail.api.stock_control import adjust_stock

		with self.assertRaises(frappe.ValidationError) as caught:
			adjust_stock({
				"warehouse": self.warehouse,
				"reason": "counted without reading the boxes",
				"items": [{"item_code": self.ITEM, "counted": 3, "rate": 12000}],
			})
		self.assertIn("IMEI", str(caught.exception))

	def test_the_same_count_goes_through_once_the_numbers_are_there(self):
		from a3_retail.api.stock_control import adjust_stock

		out = adjust_stock({
			"warehouse": self.warehouse,
			"reason": "counted by reading every box",
			"items": [{"item_code": self.ITEM, "counted": 2, "rate": 12000,
			           "serials": ["A3TESTIMEI000001", "A3TESTIMEI000002"]}],
		})
		doc = frappe.get_doc("Stock Reconciliation", out["adjustment"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(flt(doc.items[0].qty), 2.0)


class TestScanningTheBoxOfAHandset(FrappeTestCase):
	def test_a_barcode_scan_does_not_count_a_handset_as_a_quantity(self):
		"""The box barcode says which model is in hand and nothing about which
		piece, so counting it as one more leaves a quantity with no IMEI."""
		js = _js()
		block = js[js.index("async function scanIntoCount("):]
		block = block[:block.index("\n\tasync function loadSerials(")]
		self.assertIn("} else if (hit.has_serial) {", block)
		self.assertIn("scan the number on", block)

	def test_the_resolver_says_whether_a_piece_needs_a_number(self):
		from a3_retail.api.stock_control import scan_for_count
		from a3_retail.api.stock_control import _network_warehouses

		serialised = frappe.db.get_value(
			"Item", {"has_serial_no": 1, "is_stock_item": 1, "disabled": 0}, "name")
		if not serialised:
			self.skipTest("no serialised item on this site")
		hit = scan_for_count(serialised, _network_warehouses()[0]["warehouse"])
		self.assertEqual(hit["found"], "item")
		self.assertTrue(hit["has_serial"])


class TestAnImeiNobodyHasOnFile(FrappeTestCase):
	"""A handset on the shelf the system has never heard of is the find a
	count exists to make, not an error to argue with."""

	def test_the_line_gun_writes_it_down_while_counting(self):
		js = _js()
		block = js[js.index("function scanSerial("):]
		block = block[:block.index("\n\tasync function scanIntoCount(")]
		self.assertIn("not on file before", block)
		# Stock leaving is the opposite case and must still refuse.
		self.assertIn("is not on this shelf", block)

	def test_stock_leaving_still_refuses_one_that_is_not_there(self):
		js = _js()
		block = js[js.index("function scanSerial("):]
		block = block[:block.index("\n\tasync function scanIntoCount(")]
		self.assertIn("if (!counting) {", block)
