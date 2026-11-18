# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Six things the shop asked for after the second round at the counters.

1. Reverse charge on a purchase, per bill, in every branch.
2. An item that is on the books but not on the shelf must still be findable,
   and the owner's own login must be able to correct a count.
3. An item whose name repeats its own code reads as a duplicate.
4. Six Apple accessories tracked by serial number.
5. Cancelling and amending a bill belong to the Administrator, at the button
   and at the document.
6. Switching between two counters at one shop must not mean signing out.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


def a_till_user() -> str:
	"""A real counter login to stand at.

	Administrator is the one account these tests must *not* use to stand at a
	till, because half of what they check is what it alone may do.
	"""
	user = frappe.db.get_value("Employee", {"status": "Active",
	                                        "user_id": ["is", "set"]}, "user_id")
	if not user:
		raise frappe.DoesNotExistError("no till login on this site")
	return user


def _a_supplier(with_gstin: bool) -> str | None:
	"""A supplier that does, or does not, have a GSTIN on file.

	Asked through `supplier_gstin` rather than off the Supplier row, because
	that is what decides the template and a GSTIN can sit on the address.
	"""
	from a3_retail.api.purchases import _company
	from a3_retail.utils.tax import supplier_gstin

	# Not one of the shop's own branches. Those carry the company's GSTIN, and
	# india_compliance rightly refuses to charge GST when the two sides are the
	# same registration — which has nothing to do with reverse charge.
	ours = {g for g in frappe.get_all(
		"Company", filters={"name": _company()}, pluck="gstin") if g}

	for row in frappe.get_all("Supplier", fields=["name"],
	                          filters={"disabled": 0}, limit=300):
		theirs = supplier_gstin(row.name)
		if theirs and theirs in ours:
			continue
		if bool(theirs) is with_gstin:
			return row.name
	return None


# ---------------------------------------------------------------------------
# 1. Reverse charge
# ---------------------------------------------------------------------------
class TestReverseChargeIsAskedPerBill(FrappeTestCase):
	def test_the_counter_is_given_the_question(self):
		page = _source("www", "retail", "purchase_entry.html")
		self.assertIn('id="p-rcm"', page)
		self.assertIn("Reverse charge", page)

		js = _source("public", "js", "a3_purchase_entry.js")
		self.assertIn("reverse_charge", js)

	def test_the_answer_survives_being_put_aside(self):
		"""A held bill is picked up as the kind of bill it was."""
		api = _source("api", "purchases.py")
		block = api[api.index("def load_draft("):]
		block = block[:block.index("\ndef ", 10)]
		self.assertIn("reverse_charge", block)


class TestWhichTaxTemplateReverseChargePicks(FrappeTestCase):
	"""`input_gst_template` is the one place in-state/out-of-state is decided."""

	def setUp(self):
		from a3_retail.api.purchases import _company

		# The company the code itself buys under. Picking any row instead finds
		# one of ERPNext's own `_Test` companies, which has no templates.
		self.company = _company()
		self.branch = frappe.db.get_value("Branch Profile",
		                                  {"is_active": 1, "company": self.company},
		                                  "branch")

	def _template(self, supplier, rcm):
		from a3_retail.utils import tax

		return tax.input_gst_template(self.company, self.branch, supplier, 18,
		                              reverse_charge=rcm)

	def test_a_normal_bill_is_unchanged(self):
		supplier = _a_supplier(with_gstin=True)
		if not supplier:
			self.skipTest("no supplier with a GSTIN on this site")
		name = self._template(supplier, False)
		self.assertTrue(name)
		self.assertIn("Input GST", name)
		self.assertNotIn("RCM", name)

	def test_reverse_charge_picks_the_rcm_template(self):
		supplier = _a_supplier(with_gstin=True)
		if not supplier:
			self.skipTest("no supplier with a GSTIN on this site")
		self.assertIn("Input GST RCM", self._template(supplier, True))

	def test_no_gstin_still_gets_a_template_under_reverse_charge(self):
		"""The whole point: an unregistered supplier charges no GST, and the
		shop owes it instead. Refusing for want of a GSTIN would refuse exactly
		the case reverse charge exists for."""
		supplier = _a_supplier(with_gstin=False)
		if not supplier:
			self.skipTest("every supplier on this site has a GSTIN")

		self.assertIsNone(self._template(supplier, False),
		                  "a plain bill from an unregistered supplier carries no GST")
		name = self._template(supplier, True)
		self.assertTrue(name, "a reverse-charge bill must still find a template")
		self.assertIn("RCM", name)

	def test_a_supplier_with_no_gstin_is_treated_as_local(self):
		"""There is no state code to read, and an unregistered dealer is
		almost always one."""
		supplier = _a_supplier(with_gstin=False)
		if not supplier:
			self.skipTest("every supplier on this site has a GSTIN")
		self.assertIn("In-state", self._template(supplier, True))


class TestTheShapeOfAReverseChargeTemplate(FrappeTestCase):
	"""Which account goes on which side is india_compliance's call, not ours.

	It sorts every GST account into a type in GST Settings and refuses a
	purchase invoice carrying one from the wrong type. The pattern ERPNext used
	before india_compliance existed — add `Input Tax CGST RCM`, deduct
	`Output Tax CGST RCM` — cannot be saved at all:

	    Row #3: Output Tax CGST RCM - PT is not a valid GST account for this
	    transaction
	"""

	def setUp(self):
		from a3_retail.api.purchases import _company

		self.company = _company()

	def _rows(self, title):
		name = frappe.db.get_value("Purchase Taxes and Charges Template",
		                           {"title": title, "company": self.company}, "name")
		if not name:
			self.skipTest(f"{title} is not on this site")
		return frappe.get_doc("Purchase Taxes and Charges Template", name).taxes

	def test_no_output_account_is_on_a_purchase_template(self):
		"""The one that bit. `Output Tax * RCM` is "Sales Reverse Charge" — the
		self-invoice's accounts, not a purchase's."""
		from india_compliance.gst_india.overrides.transaction import get_valid_accounts

		valid, _intra, _inter = get_valid_accounts(self.company, for_purchase=True,
		                                           throw=False)
		valid = {account for account in valid if account}

		for template in frappe.get_all("Purchase Taxes and Charges Template",
		                               filters={"company": self.company,
		                                        "title": ["like", "Input GST RCM %"]},
		                               fields=["name"]):
			doc = frappe.get_doc("Purchase Taxes and Charges Template", template.name)
			for row in doc.taxes:
				self.assertIn(row.account_head, valid,
				              f"{template.name} carries {row.account_head}, which "
				              "india_compliance will refuse on a purchase")

	def test_the_credit_lands_where_the_purchase_register_reads_it(self):
		"""`gst_itemised_purchase_register` and GSTR-2B matching read the
		ordinary input accounts. ITC booked anywhere else is invisible at
		return time."""
		added = [row for row in self._rows("Input GST RCM In-state 18%")
		         if row.add_deduct_tax == "Add"]
		self.assertTrue(added)
		for row in added:
			self.assertNotIn("RCM", row.account_head)

	def test_the_liability_lands_in_the_reverse_charge_account(self):
		deducted = [row for row in self._rows("Input GST RCM In-state 18%")
		            if row.add_deduct_tax == "Deduct"]
		self.assertTrue(deducted)
		for row in deducted:
			self.assertIn("RCM", row.account_head)

	def test_the_two_sides_net_to_the_base_amount(self):
		"""The supplier charged no GST, so the bill must come to the base
		amount or the shop pays tax it was never charged."""
		for title in ("Input GST RCM In-state 18%", "Input GST RCM Out-state 18%"):
			rows = self._rows(title)
			added = sum(row.rate for row in rows if row.add_deduct_tax == "Add")
			deducted = sum(row.rate for row in rows if row.add_deduct_tax == "Deduct")
			self.assertAlmostEqual(added, deducted, msg=f"{title} does not net out")

	def test_every_rate_the_shop_buys_at_has_one(self):
		"""A rate with no template of its own finds none, and the bill carries
		no tax at all rather than the wrong tax — silent, and wrong in the
		return."""
		from a3_retail.utils.tax import input_gst_template

		branch = frappe.db.get_value("Branch Profile",
		                             {"is_active": 1, "company": self.company},
		                             "branch")
		supplier = _a_supplier(with_gstin=True) or _a_supplier(with_gstin=False)
		if not supplier:
			self.skipTest("no supplier on this site")

		for rate in (5, 12, 18, 28):
			self.assertTrue(
				input_gst_template(self.company, branch, supplier, rate,
				                   reverse_charge=True),
				f"nothing to post a {rate}% reverse-charge bill with")

	def test_there_is_one_statement_of_the_pattern(self):
		"""The installer and the patch share it, or they drift."""
		self.assertIn("rcm_template_rows", _source("setup", "tax.py"))
		self.assertIn("from a3_retail.setup.tax import rcm_template_rows",
		              _source("patches",
		                      "rcm_templates_the_shape_india_compliance_reads.py"))

	def test_a_live_site_is_corrected(self):
		self.assertIn("a3_retail.patches.rcm_templates_the_shape_india_compliance_reads",
		              _source("patches.txt"))

	def test_the_patch_leaves_posted_bills_alone(self):
		"""A submitted bill is the shop's record and a return may be filed on
		it. The patch reports them for a person to look at."""
		body = _source("patches", "rcm_templates_the_shape_india_compliance_reads.py")
		self.assertIn("docstatus = 1", body)
		self.assertIn("left exactly as they are", body)
		for forbidden in ("doc.cancel()", "db_set", "update `tabGL Entry`"):
			self.assertNotIn(forbidden, body)


class TestWhatAReverseChargeBillPosts(FrappeTestCase):
	def setUp(self):
		self.user = a_till_user()
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")

		from a3_retail.api.staff import _me

		self.employee = _me()
		self.supplier = _a_supplier(with_gstin=True)
		self.item = frappe.db.sql("""select name from `tabItem`
		                             where is_stock_item = 1
		                               and ifnull(has_serial_no, 0) = 0
		                               and ifnull(disabled, 0) = 0
		                             limit 1""")
		if not (self.supplier and self.item):
			self.skipTest("no supplier with a GSTIN, or no plain stock item")
		self.item = self.item[0][0]

	def _build(self, **extra):
		from a3_retail.api.purchases import _build

		data = {"supplier": self.supplier, "bill_no": "RCM-TEST-1",
		        "items": [{"item_code": self.item, "qty": 1, "rate": 1000}]}
		data.update(extra)
		doc, _priced = _build(data, self.employee)
		return doc

	def test_the_flag_india_compliance_reads_is_the_one_set(self):
		"""The GST return is built from `is_reverse_charge`. `a3_is_rcm_applicable`
		is a Supplier field and setting it on the invoice would go nowhere."""
		self.assertTrue(frappe.get_meta("Purchase Invoice").has_field("is_reverse_charge"))
		self.assertFalse(frappe.get_meta("Purchase Invoice").has_field("a3_is_rcm_applicable"))
		self.assertEqual(self._build(reverse_charge=1).is_reverse_charge, 1)
		self.assertEqual(self._build(reverse_charge=0).is_reverse_charge, 0)

	def test_both_halves_of_the_tax_are_booked(self):
		"""Reverse charge is a liability and a credit at once: the shop owes the
		tax (Deduct) and may claim it back (Add). One row without the other
		would either overstate the bill or lose the ITC."""
		doc = self._build(reverse_charge=1)
		self.assertIn("RCM", doc.taxes_and_charges)

		sides = {row.add_deduct_tax for row in doc.get("taxes")}
		self.assertEqual(sides, {"Add", "Deduct"},
		                 f"expected both halves, got {sides}")
		added = sum(1 for row in doc.get("taxes") if row.add_deduct_tax == "Add")
		deducted = sum(1 for row in doc.get("taxes") if row.add_deduct_tax == "Deduct")
		self.assertEqual(added, deducted, "the two halves must balance")

	def test_a_normal_bill_only_adds(self):
		doc = self._build(reverse_charge=0)
		self.assertNotIn("RCM", doc.taxes_and_charges or "")
		self.assertEqual({row.add_deduct_tax for row in doc.get("taxes")}, {"Add"})

	def test_a_bill_that_says_nothing_takes_the_supplier_s_standing_answer(self):
		"""`a3_is_rcm_applicable` on the Supplier was put there to drive exactly
		this, so a supplier always bought from under reverse charge does not
		have to be remembered at every bill."""
		was = frappe.db.get_value("Supplier", self.supplier, "a3_is_rcm_applicable")
		self.addCleanup(frappe.db.set_value, "Supplier", self.supplier,
		                "a3_is_rcm_applicable", was, update_modified=False)

		frappe.db.set_value("Supplier", self.supplier, "a3_is_rcm_applicable", 1,
		                    update_modified=False)
		self.assertEqual(self._build().is_reverse_charge, 1)

		frappe.db.set_value("Supplier", self.supplier, "a3_is_rcm_applicable", 0,
		                    update_modified=False)
		self.assertEqual(self._build().is_reverse_charge, 0)

	def test_the_bill_overrides_the_supplier_either_way(self):
		"""A one-off goes both directions, or the standing answer becomes a
		trap rather than a convenience."""
		was = frappe.db.get_value("Supplier", self.supplier, "a3_is_rcm_applicable")
		self.addCleanup(frappe.db.set_value, "Supplier", self.supplier,
		                "a3_is_rcm_applicable", was, update_modified=False)

		frappe.db.set_value("Supplier", self.supplier, "a3_is_rcm_applicable", 1,
		                    update_modified=False)
		self.assertEqual(self._build(reverse_charge=0).is_reverse_charge, 0)

		frappe.db.set_value("Supplier", self.supplier, "a3_is_rcm_applicable", 0,
		                    update_modified=False)
		self.assertEqual(self._build(reverse_charge=1).is_reverse_charge, 1)

	def test_a_reverse_charge_bill_submits(self):
		"""india_compliance validates the flag against the template it finds, so
		building one proves less than posting one."""
		doc = self._build(reverse_charge=1)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.is_reverse_charge, 1)


# ---------------------------------------------------------------------------
# 2. An item on the books but not on the shelf
# ---------------------------------------------------------------------------
class TestSearchingForSomethingNotOnTheShelf(FrappeTestCase):
	def setUp(self):
		self.user = a_till_user()
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_a_named_search_answers_with_the_item(self):
		"""Reported as "T100 is missing from the POS". It was never missing — it
		had none on hand at that till, and the shelf filter swallowed it."""
		from a3_retail.api.pos import catalogue

		empty = frappe.db.sql("""select i.name from `tabItem` i
		                         where i.is_stock_item = 1
		                           and ifnull(i.disabled, 0) = 0
		                           and not exists (select 1 from `tabBin` b
		                                           where b.item_code = i.name
		                                             and b.actual_qty > 0)
		                         limit 1""")
		if not empty:
			self.skipTest("every stock item on this site has stock somewhere")
		code = empty[0][0]

		found = catalogue(query=code, only_in_stock=1)
		self.assertIn(code, [row["item_code"] for row in found],
		              "a code typed in full must be answered with the item")

	def test_browsing_still_hides_what_is_not_there(self):
		"""The filter is not gone — it applies to browsing, which is what it is
		for. Only a named search bypasses it."""
		api = _source("api", "pos.py")
		self.assertIn('if cint(only_in_stock) and not (query or "").strip():', api)

	def test_the_item_is_marked_rather_than_silently_offered(self):
		from a3_retail.api.pos import catalogue

		rows = catalogue(query="", only_in_stock=0)
		self.assertTrue(rows)
		self.assertIn("branch_qty", rows[0],
		              "the screen needs the count to be able to say 'not here'")


class TestTheOwnerStandingInAtACounter(FrappeTestCase):
	def test_an_ordinary_account_with_no_employee_is_still_refused(self):
		from a3_retail.api.staff import _standing_in_at_a_counter

		user = frappe.db.get_value("User", {"enabled": 1, "name": ["not in",
		                                                          ("Administrator", "Guest")]}, "name")
		if not user:
			self.skipTest("no other user on this site")
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertIsNone(_standing_in_at_a_counter())

	def test_the_administrator_is_given_a_branch_to_work(self):
		from a3_retail.api.staff import _standing_in_at_a_counter

		frappe.set_user("Administrator")
		standing = _standing_in_at_a_counter()
		self.assertTrue(standing, "the owner's login must be able to reach a counter")
		self.assertTrue(frappe.db.exists("Branch Profile",
		                                 {"branch": standing["branch"], "is_active": 1}))

	def test_it_does_not_pretend_to_be_an_employee(self):
		"""A sale credited to a stand-in would credit it to nobody, or worse to
		whichever Sales Person happens to have a blank employee link."""
		from a3_retail.api.pos import _sales_person
		from a3_retail.api.staff import _standing_in_at_a_counter

		frappe.set_user("Administrator")
		standing = _standing_in_at_a_counter()
		self.assertTrue(standing.get("is_stand_in"))
		self.assertIsNone(standing.get("name"))
		self.assertIsNone(_sales_person(standing.get("name")))
		self.assertIsNone(_sales_person(None))
		self.assertIsNone(_sales_person(""))

	def test_me_answers_for_the_administrator(self):
		from a3_retail.api.staff import _me

		frappe.set_user("Administrator")
		self.assertTrue(_me().get("branch"))

	def test_the_branch_picked_is_the_branch_honoured(self):
		from a3_retail.api.staff import ACTIVE_BRANCH_KEY, _standing_in_at_a_counter

		branches = [row.branch for row in frappe.get_all(
			"Branch Profile", filters={"is_active": 1}, fields=["branch"])]
		if len(branches) < 2:
			self.skipTest("only one active branch on this site")

		frappe.set_user("Administrator")
		self.addCleanup(frappe.cache().hdel, ACTIVE_BRANCH_KEY, "Administrator")
		frappe.cache().hset(ACTIVE_BRANCH_KEY, "Administrator", branches[1])
		self.assertEqual(_standing_in_at_a_counter()["branch"], branches[1])


# ---------------------------------------------------------------------------
# 3. An item whose name repeats its own code
# ---------------------------------------------------------------------------
class TestAnItemNameCarryingItsOwnCode(FrappeTestCase):
	def _trim(self, code, name):
		from a3_retail.patches.item_names_carrying_their_code import _without_the_code

		return _without_the_code(code, name)

	def test_the_reported_case(self):
		"""`T150` was reported as a duplicate item. There is one record; its
		name just said the same thing twice."""
		self.assertEqual(self._trim("T150", "TEMPERED - 150  T150"), "TEMPERED - 150")

	def test_a_name_that_genuinely_ends_in_those_words_is_left_alone(self):
		"""`CURVED GLASS` is an item code here, and trimming it off
		`PREMIUM FULL GLUE CURVED GLASS` would leave something that is not the
		thing on the shelf."""
		self.assertIsNone(
			self._trim("CURVED GLASS", "PREMIUM FULL GLUE CURVED GLASS"))

	def test_only_something_shaped_like_a_code_is_taken_off(self):
		self.assertIsNone(self._trim("GLASS", "TEMPERED GLASS"))
		self.assertEqual(self._trim("PT450", "POWER BANK PT450"), "POWER BANK")

	def test_an_item_is_never_left_nameless(self):
		self.assertIsNone(self._trim("T150", "T150"))
		self.assertIsNone(self._trim("T150", "  T150  "))

	def test_separators_go_with_it(self):
		for name in ("TEMPERED - 150 - T150", "TEMPERED - 150, T150",
		             "TEMPERED - 150 · T150"):
			self.assertEqual(self._trim("T150", name), "TEMPERED - 150")

	def test_the_case_of_the_code_does_not_matter(self):
		self.assertEqual(self._trim("T150", "Tempered 150 t150"), "Tempered 150")

	def test_the_patch_runs_on_a_live_site(self):
		self.assertIn("a3_retail.patches.item_names_carrying_their_code",
		              _source("patches.txt"))


# ---------------------------------------------------------------------------
# 4. Six Apple accessories tracked by serial
# ---------------------------------------------------------------------------
class TestSerialisingTheAppleAccessories(FrappeTestCase):
	def test_the_six_the_shop_named(self):
		from a3_retail.patches.apple_accessories_serialised import ITEMS

		self.assertEqual(len(ITEMS), 6)
		for wanted in ("APPLE ADAPTOR 30 W", "APPLE 15 128 GB TEAL",
		               "APPLE EARPODS WITH USB-C (MYQY3ZM/A)",
		               "APPLE 20W USB C ADAPTER MUVR3HN/A",
		               "APPLE 20W USB C POWER ADAPTER MUVR3HN/A",
		               "APPLE 30W USB C POWER ADAPTER (MW2G3HN/A)"):
			self.assertIn(wanted, ITEMS)

	def test_an_item_holding_stock_is_left_alone(self):
		"""Stock counted in without serials can never produce one, so flipping
		the flag underneath it leaves pieces nobody can sell."""
		from a3_retail.api.stock import can_serialise

		held = frappe.db.sql("""select item_code from `tabBin`
		                        where actual_qty > 0 limit 1""")
		if not held:
			self.skipTest("nothing in stock on this site")
		self.assertFalse(can_serialise(held[0][0]))

	def test_the_patch_asks_rather_than_deciding(self):
		body = _source("patches", "apple_accessories_serialised.py")
		self.assertIn("can_serialise(code)", body)
		self.assertIn("_set_serialisation(code, 1)", body)

	def test_it_says_what_it_left_and_why(self):
		"""It will do nothing on the first run — every one of the six holds
		stock — so it has to report that rather than look like success."""
		body = _source("patches", "apple_accessories_serialised.py")
		self.assertIn("still holding stock", body)
		self.assertIn("Count the shelf out", body)

	def test_nothing_in_it_moves_stock(self):
		body = _source("patches", "apple_accessories_serialised.py")
		for forbidden in ("Stock Entry", "Stock Reconciliation", "make_stock_entry"):
			self.assertNotIn(forbidden, body)

	def test_the_patch_runs_on_a_live_site(self):
		self.assertIn("a3_retail.patches.apple_accessories_serialised",
		              _source("patches.txt"))

	def test_it_can_be_run_again(self):
		"""The shop clears a shelf when it chooses, not when a patch does, so
		this has to be re-runnable rather than once-only."""
		body = _source("patches", "apple_accessories_serialised.py")
		self.assertIn("has_serial_no", body)   # already-done items are skipped


# ---------------------------------------------------------------------------
# 5. Cancelling and amending belong to the Administrator
# ---------------------------------------------------------------------------
class TestWhoMayUndoABill(FrappeTestCase):
	def setUp(self):
		self.user = a_till_user()

	def test_the_counter_is_refused_at_the_button(self):
		from a3_retail.api.bills import _only_the_administrator

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			_only_the_administrator()

	def test_the_administrator_is_not(self):
		from a3_retail.api.bills import _only_the_administrator

		frappe.set_user("Administrator")
		_only_the_administrator()          # must not throw

	def test_both_buttons_ask_before_doing_anything(self):
		api = _source("api", "bills.py")
		for name in ("cancel_bill", "amend_bill"):
			block = api[api.index(f"def {name}("):]
			block = block[:block.index("\n@frappe.whitelist()")] if "\n@frappe.whitelist()" in block else block
			self.assertIn("_only_the_administrator()", block,
			              f"{name} must refuse before it starts work")
			self.assertLess(block.index("_only_the_administrator()"),
			                block.index("_me()"),
			                f"{name} must refuse before anything else happens")

	def test_the_document_itself_refuses(self):
		"""The button is a courtesy; this is the rule. It holds for the desk,
		the API and a background job alike."""
		from a3_retail.overrides.sales_invoice import only_the_administrator_may_undo

		doc = frappe._dict({"name": "SI-TEST-0001"})
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			only_the_administrator_may_undo(doc)

		frappe.set_user("Administrator")
		only_the_administrator_may_undo(doc)          # must not throw

	def test_an_amendment_is_caught_as_it_is_written(self):
		"""An amendment arrives as an insert carrying `amended_from`, not as a
		cancel, so it would otherwise walk straight past the hook above."""
		from a3_retail.overrides.sales_invoice import only_the_administrator_may_amend

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")

		plain = frappe._dict({"name": "new", "amended_from": None})
		only_the_administrator_may_amend(plain)       # an ordinary bill is fine

		amendment = frappe._dict({"name": "new", "amended_from": "SI-TEST-0001"})
		with self.assertRaises(frappe.PermissionError):
			only_the_administrator_may_amend(amendment)

	def test_the_hooks_are_registered_for_both_kinds_of_bill(self):
		from a3_retail import hooks

		for doctype in ("Sales Invoice", "POS Invoice"):
			events = hooks.doc_events[doctype]
			self.assertIn("only_the_administrator_may_undo",
			              str(events.get("before_cancel")),
			              f"{doctype} may be cancelled unchecked")
			self.assertIn("only_the_administrator_may_amend",
			              str(events.get("before_insert")),
			              f"{doctype} may be amended unchecked")

	def test_ignoring_permissions_does_not_get_past_it(self):
		"""Our own code sets that flag when it builds documents for a counter.
		Cancelling is never that."""
		from a3_retail.overrides.sales_invoice import only_the_administrator_may_undo

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.flags.ignore_permissions = True
		self.addCleanup(setattr, frappe.flags, "ignore_permissions", False)
		with self.assertRaises(frappe.PermissionError):
			only_the_administrator_may_undo(frappe._dict({"name": "SI-TEST-0001"}))

	def test_a_real_submitted_bill_cannot_be_cancelled_from_a_till(self):
		"""The one that matters: the rule has to hold on a live document and not
		merely in a helper."""
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
		if not name:
			self.skipTest("no submitted bill on this site")

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		doc = frappe.get_doc("Sales Invoice", name)
		with self.assertRaises(frappe.PermissionError):
			doc.cancel()

	def test_the_counter_is_not_offered_a_button_that_cannot_work(self):
		js = _source("public", "js", "a3_bills.js")
		self.assertIn("mayUndo", js)
		block = js[js.index("if (state.mayUndo)"):]
		block = block[:block.index("paintOptions")]
		self.assertIn("Cancel this bill", block)
		self.assertIn("Amend", block)
		# And when we cannot tell, nothing is offered.
		self.assertIn("state.mayUndo = false;", js)


# ---------------------------------------------------------------------------
# 6. Two counters at one shop, without signing out
# ---------------------------------------------------------------------------
class TestSwitchingCounterWithoutSigningOut(FrappeTestCase):
	def test_a_user_at_two_counters_is_offered_both(self):
		"""Accessories and Sales at UK are two branches in one shop, and the
		same person works both."""
		from a3_retail.api.staff import permitted_branches

		frappe.set_user("Administrator")
		self.assertGreater(len(permitted_branches()), 1)

	def test_switching_is_remembered_without_a_new_session(self):
		from a3_retail.api.staff import (ACTIVE_BRANCH_KEY, permitted_branches,
		                                 session_context, switch_branch)

		frappe.set_user("Administrator")
		branches = permitted_branches()
		if len(branches) < 2:
			self.skipTest("only one branch permitted on this site")
		self.addCleanup(frappe.cache().hdel, ACTIVE_BRANCH_KEY, "Administrator")

		before = frappe.session.sid
		switch_branch(branches[1])
		self.assertEqual(session_context()["branch"], branches[1])
		switch_branch(branches[0])
		self.assertEqual(session_context()["branch"], branches[0])
		self.assertEqual(frappe.session.sid, before,
		                 "switching counters must not need a new session")

	def test_another_branch_cannot_be_switched_to(self):
		"""It is a picker, not a door."""
		from a3_retail.api.staff import permitted_branches, switch_branch

		self.user = a_till_user()
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")

		mine = set(permitted_branches())
		theirs = [row.branch for row in frappe.get_all(
			"Branch Profile", filters={"is_active": 1}, fields=["branch"])
			if row.branch not in mine]
		if not theirs:
			self.skipTest("this till is permitted every branch")
		with self.assertRaises(frappe.PermissionError):
			switch_branch(theirs[0])

	def test_the_picker_does_not_print_the_branch_name_twice(self):
		"""It did, and it read as a stuttering label rather than a control — so
		the counter reached for "Switch user", which signs them out. That is
		the whole of the reported fault."""
		js = _source("public", "js", "a3_branch.js")
		block = js[js.index("async function mountBranchPicker()"):]
		block = block[:block.index("\n\t}")]
		self.assertIn("heading.textContent", block)
		self.assertIn("String(ctx.branch", block)

	def test_the_heading_is_emptied_and_not_removed(self):
		"""Four screens write their own title into it once their data arrives."""
		js = _source("public", "js", "a3_branch.js")
		self.assertIn('heading.textContent = "";', js)
		self.assertNotIn("heading.remove()", js)
