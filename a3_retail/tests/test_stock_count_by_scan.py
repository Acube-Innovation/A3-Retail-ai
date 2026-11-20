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
