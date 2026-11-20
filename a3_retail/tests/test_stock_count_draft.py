# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Putting a stock count aside and picking it up again.

A count of four thousand accessories is not finished in one sitting. It is held
in a `Stock Count Draft` rather than in a draft Stock Reconciliation, because
ERPNext validates a reconciliation on every save: a row whose counted quantity
already matches the system is *removed*, and if every row matches it refuses to
save at all. Both are right for a finished count and would silently lose part
of a half-finished one.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

BRANCH = "PhoneXpert Sales PSLA"
WAREHOUSE = "PhoneXpert Sales PSLA - PT"


def _js() -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", "a3_stock.js"),
	            encoding="utf-8").read()


def _stand_at(branch=BRANCH):
	from a3_retail.api.staff import ACTIVE_BRANCH_KEY

	frappe.set_user("Administrator")
	frappe.cache().hset(ACTIVE_BRANCH_KEY, "Administrator", branch)


def _a_serial():
	rows = frappe.db.sql("""select name, item_code from `tabSerial No`
	                        where status = 'Active' and warehouse = %s limit 1""",
	                     WAREHOUSE, as_dict=True)
	return rows[0] if rows else None


class TestTheHolder(FrappeTestCase):
	def test_the_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Stock Count Draft"))

	def test_it_holds_the_lines_as_text_rather_than_as_stock(self):
		"""It is a scratchpad, not a second stock system: no quantity anywhere
		until a real Stock Reconciliation is posted."""
		meta = frappe.get_meta("Stock Count Draft")
		self.assertEqual(meta.get_field("lines").fieldtype, "Long Text")
		self.assertTrue(meta.has_field("posted_as"))
		self.assertEqual(meta.get_field("posted_as").options, "Stock Reconciliation")

	def test_unreadable_lines_are_refused_early(self):
		doc = frappe.new_doc("Stock Count Draft")
		doc.branch = BRANCH
		doc.warehouse = WAREHOUSE
		doc.counted_on = frappe.utils.nowdate()
		doc.lines = "{not json"
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class TestHoldingACount(FrappeTestCase):
	def setUp(self):
		_stand_at()
		self.serial = _a_serial()
		if not self.serial:
			self.skipTest(f"no active serial at {WAREHOUSE}")
		self.addCleanup(self._forget_branch)

	@staticmethod
	def _forget_branch():
		from a3_retail.api.staff import ACTIVE_BRANCH_KEY

		frappe.cache().hdel(ACTIVE_BRANCH_KEY, "Administrator")
		frappe.set_user("Administrator")

	def _hold(self, **over):
		from a3_retail.api.stock_control import adjust_stock

		payload = {"warehouse": WAREHOUSE, "date": frappe.utils.nowdate(),
		           "reason": "Shelf count", "draft": 1, "kind": "scan",
		           "items": [{"item_code": self.serial.item_code, "counted": 1,
		                      "serials": [self.serial.name]}]}
		payload.update(over)
		return adjust_stock(payload)

	def test_a_count_that_matches_the_system_is_still_held(self):
		"""The case that made a draft Stock Reconciliation unusable: ERPNext
		refuses to save one when nothing differs, and drops the rows that
		match. Scan five of something the system also thinks there are five of
		and the line must still be there when you come back."""
		out = self._hold()
		self.assertTrue(out["draft"])
		self.assertTrue(out["adjustment"].startswith("COUNT-"))

		doc = frappe.get_doc("Stock Count Draft", out["adjustment"])
		rows = json.loads(doc.lines)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["item_code"], self.serial.item_code)
		self.assertEqual(rows[0]["serials"], [self.serial.name])

	def test_nothing_is_posted_by_holding_it(self):
		out = self._hold()
		doc = frappe.get_doc("Stock Count Draft", out["adjustment"])
		self.assertEqual(doc.status, "Open")
		self.assertFalse(doc.posted_as)

	def test_holding_it_twice_updates_the_same_count(self):
		"""Otherwise every press of the button leaves another half-count behind
		and the list fills with them."""
		first = self._hold()
		again = self._hold(name=first["adjustment"], reason="Shelf count, more")
		self.assertEqual(again["adjustment"], first["adjustment"])
		self.assertEqual(
			frappe.db.get_value("Stock Count Draft", first["adjustment"], "reason"),
			"Shelf count, more")

	def test_the_kind_of_count_is_remembered(self):
		out = self._hold(kind="scan")
		self.assertEqual(
			frappe.db.get_value("Stock Count Draft", out["adjustment"], "kind"),
			"Reconciliation")

	def test_it_comes_back_in_the_shape_the_dialog_fills_from(self):
		from a3_retail.api.stock_control import load_adjustment

		out = self._hold()
		back = load_adjustment(out["adjustment"])
		self.assertEqual(back["name"], out["adjustment"])
		self.assertEqual(back["warehouse"], WAREHOUSE)
		self.assertEqual(back["kind"], "scan")
		self.assertEqual(len(back["items"]), 1)
		self.assertEqual(back["items"][0]["serials"], [self.serial.name])
		self.assertTrue(back["items"][0]["item_name"])

	def test_carrying_on_posts_it_and_closes_the_holder(self):
		from a3_retail.api.stock_control import adjust_stock

		held = self._hold()
		other = frappe.db.sql("""select b.item_code, b.actual_qty from `tabBin` b
		                         join `tabItem` i on i.name = b.item_code
		                         where b.warehouse = %s and b.actual_qty > 2
		                           and ifnull(i.has_serial_no, 0) = 0 limit 1""",
		                      WAREHOUSE, as_dict=True)
		if not other:
			self.skipTest("nothing countable to differ on")

		done = adjust_stock({
			"name": held["adjustment"], "warehouse": WAREHOUSE,
			"date": frappe.utils.nowdate(), "reason": "finished",
			"items": [{"item_code": self.serial.item_code, "counted": 1,
			           "serials": [self.serial.name]},
			          {"item_code": other[0].item_code,
			           "counted": float(other[0].actual_qty) - 1}],
		})
		doc = frappe.get_doc("Stock Count Draft", held["adjustment"])
		self.assertEqual(doc.status, "Posted")
		self.assertEqual(doc.posted_as, done["adjustment"])
		self.assertEqual(
			frappe.db.get_value("Stock Reconciliation", done["adjustment"], "docstatus"), 1)

	def test_a_posted_count_cannot_be_posted_again(self):
		from a3_retail.api.stock_control import adjust_stock

		held = self._hold()
		frappe.db.set_value("Stock Count Draft", held["adjustment"], "status", "Posted")
		with self.assertRaises(frappe.ValidationError):
			adjust_stock({"name": held["adjustment"], "warehouse": WAREHOUSE,
			              "date": frappe.utils.nowdate(), "reason": "again",
			              "items": [{"item_code": self.serial.item_code, "counted": 1}]})

	def test_another_branch_cannot_pick_it_up(self):
		from a3_retail.api.staff import ACTIVE_BRANCH_KEY
		from a3_retail.api.stock_control import load_adjustment

		held = self._hold()
		elsewhere = frappe.db.get_value(
			"Branch Profile", {"is_active": 1, "branch": ["!=", BRANCH]}, "branch")
		if not elsewhere:
			self.skipTest("only one branch on this site")
		frappe.cache().hset(ACTIVE_BRANCH_KEY, "Administrator", elsewhere)
		with self.assertRaises(frappe.ValidationError):
			load_adjustment(held["adjustment"])

	def test_held_counts_head_the_adjustments_list(self):
		"""They are the only rows on it somebody still has to finish."""
		from a3_retail.api.stock_control import _adjustments

		held = self._hold()
		rows = _adjustments(BRANCH, 50)
		self.assertTrue(rows)
		self.assertEqual(rows[0]["name"], held["adjustment"])
		self.assertEqual(rows[0]["status"], "Held")
		self.assertEqual(rows[0]["held"], held["adjustment"])
		# A posted one carries no "held" marker, so it offers no Continue.
		posted = [r for r in rows if r["status"] != "Held"]
		self.assertTrue(all(not r.get("held") for r in posted))


class TestTheDialogOffersIt(FrappeTestCase):
	def test_there_is_a_save_as_draft_button(self):
		page = open(frappe.get_app_path("a3_retail", "www", "retail", "stock.html"),
		            encoding="utf-8").read()
		self.assertIn('id="work-hold"', page)
		self.assertIn("Save as draft", page)

	def test_only_the_count_offers_it(self):
		"""Every other dialog posts or does nothing."""
		js = _js()
		block = js[js.index("function openWork("):]
		block = block[:block.index("\n\tfunction say(")]
		self.assertIn('hold.hidden = true', block)

	def test_submit_and_hold_describe_the_count_the_same_way(self):
		"""Two builders would eventually disagree, and the held count would not
		be what got posted."""
		js = _js()
		self.assertIn("const countedLines = () =>", js)
		self.assertEqual(js.count("const counted = countedLines();"), 2)

	def test_a_held_row_offers_continue(self):
		js = _js()
		self.assertIn('["held", "", "continue"]', js)
		self.assertIn("data-continue", js)
		self.assertIn("continueCount(node.dataset.continue)", js)

	def test_continue_loads_it_back_into_the_dialog(self):
		js = _js()
		block = js[js.index("async function continueCount("):]
		block = block[:block.index("\n\tfunction paintCards(")]
		self.assertIn("a3_retail.api.stock_control.load_adjustment", block)
		self.assertIn("openAdjust(held)", block)

	def test_a_resumed_count_is_restored_rather_than_wiped(self):
		"""Switching kind clears the lines on purpose; opening a held count
		must not go through that."""
		js = _js()
		self.assertIn("if (restoring && held)", js)
		self.assertIn("restoring = false;", js)
