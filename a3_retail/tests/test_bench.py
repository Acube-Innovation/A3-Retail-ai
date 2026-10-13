# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Working a repair from the branch app.

Everything between booking a device in and handing it back used to need the
desk, which the people doing the work are not meant to open. These are the
rules that keep the screen honest: it offers the steps the job card allows and
the person may take, and nothing else.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import bookings


class TestTheStepsOffered(FrappeTestCase):
	def test_only_the_state_machine_decides_what_comes_next(self):
		"""The screen never invents a path — it reads the one that exists."""
		for status, expected in (
			(st.OPEN, (st.UNDER_DIAGNOSIS, st.CANCELLED)),
			(st.IN_PROGRESS, (st.REPAIR_COMPLETED, st.ON_HOLD, st.AWAITING_PARTS,
			                  st.NOT_REPAIRABLE)),
			(st.REPAIR_COMPLETED, (st.QC_PASSED, st.QC_FAILED)),
			(st.QC_PASSED, (st.READY_FOR_DELIVERY,)),
		):
			self.assertEqual(st.next_statuses(status), expected, status)

	def test_delivery_is_never_just_a_status_button(self):
		"""Handing a device back needs the customer's code, the accessories and
		the balance — so it is its own action, not a step on the rail."""
		self.assertIn(st.DELIVERED, bookings.NOT_A_BUTTON)
		self.assertIn(st.DELIVERED, st.next_statuses(st.READY_FOR_DELIVERY))

	def test_the_steps_that_stall_a_repair_must_say_why(self):
		"""A card that stops with no reason is the one nobody can answer the
		customer about."""
		for status in (st.ON_HOLD, st.CANCELLED, st.NOT_REPAIRABLE, st.QC_FAILED):
			self.assertIn(status, bookings.NEEDS_REASON, status)

	def test_every_step_reads_as_something_a_person_would_say(self):
		"""“QC Passed” is not how anybody on the floor says it."""
		for status in st.STATUSES:
			if status in (st.DRAFT, st.OPEN):
				continue
			self.assertIn(status, bookings.STEP_WORDS, status)
			label, hint = bookings.STEP_WORDS[status]
			self.assertTrue(label and label != status, status)
			self.assertTrue(hint, status)


class TestWhoMayTakeAStep(FrappeTestCase):
	def test_a_technician_does_not_pass_qc_on_their_own_repair(self):
		for status in (st.QC_PASSED, st.QC_FAILED, st.NOT_REPAIRABLE):
			roles = st.TRANSITION_ROLES.get(status)
			self.assertTrue(roles, status)
			self.assertNotIn("Technician", roles, status)

	def test_a_technician_can_change_a_submitted_card(self):
		"""Sixty-six fields here are allow_on_submit — the status, the diagnosis,
		the bench it is on — so the whole repair happens after submit. Frappe
		calls changing a submitted document "submit", so without it a technician
		could not move their own job card one step."""
		from a3_retail.setup.permissions import PERMISSION_MATRIX

		flags = PERMISSION_MATRIX["Service Job Card"]["Technician"]
		self.assertIn("R", flags)
		self.assertIn("U", flags)
		self.assertIn("S", flags)
		# and still cannot open one: reception books, the bench works
		self.assertNotIn("C", flags)


class TestTheBookingPageLayout(FrappeTestCase):
	def test_the_bench_spans_the_page(self):
		"""The booking page is a two-column grid — the sheet, then a 340px rail.

		The bench is a third child of that grid, so without an explicit span it
		took the sheet's column and pushed the whole sheet into the rail, where
		the sticky totals then sat on top of the content behind them.
		"""
		css = open(frappe.get_app_path(
			"a3_retail", "public", "css", "a3_branch.css")).read()
		self.assertIn(".wb { grid-column: 1 / -1;", css,
		              "the bench has to span both columns of the booking page")

	def test_a_device_does_not_say_its_brand_twice(self):
		"""Some products carry the maker's name — Apple Watch, Galaxy Tab — so
		pasting the brand in front of every model read "Apple Apple Watch SE 3"
		on the face of the booking."""
		script = open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_booking.js")).read()
		self.assertIn("function deviceTitle", script)
		self.assertIn("startsWith(brand.toLowerCase())", script)

		repeats = frappe.db.sql("""
			select name from `tabDevice Model`
			where lower(model_name) like concat(lower(brand), ' %')""", pluck=True)
		self.assertEqual(repeats, [],
		                 "these models repeat their own brand: " + ", ".join(repeats))


class TestWhatTheCounterIsMadeToDo(FrappeTestCase):
	"""Checks a shop can switch off, because not every shop works the same way."""

	def _setting(self, field, value):
		before = frappe.db.get_single_value("A3 Retail Settings", field)
		frappe.db.set_single_value("A3 Retail Settings", field, value)
		self.addCleanup(frappe.db.set_single_value, "A3 Retail Settings", field, before)

	def test_the_collection_code_can_be_switched_off(self):
		"""A counter that knows its customers by face should not be made to type
		a code it never sent. With it off, the signature on the job card is what
		the hand-over rests on."""
		import inspect

		from a3_retail.api import service

		source = inspect.getsource(service.deliver_job_card)
		self.assertIn("require_delivery_otp", source,
		              "the OTP check has to be behind the setting")
		# and the screens have to know, or they ask for something nobody wants
		from a3_retail.api import bookings, service_pos

		self.assertIn("require_delivery_otp", inspect.getsource(service_pos.bootstrap))
		self.assertIn("require_otp", inspect.getsource(bookings.steps))

	def test_the_signature_is_already_a_setting(self):
		from a3_retail.a3_retail_service.doctype.service_job_card import service_job_card

		self.assertTrue(hasattr(service_job_card, "_require_signature"))
		self._setting("require_signature", 0)
		self.assertFalse(service_job_card._require_signature())


class TestWhoIsOnTheBench(FrappeTestCase):
	def test_the_list_is_never_silently_empty(self):
		"""A Technician Profile is the proper record, but a shop that has not
		filled them in still has technicians — and a dropdown with nothing in it
		is how a repair ends up assigned to nobody."""
		import inspect

		from a3_retail.api import service_pos

		source = inspect.getsource(service_pos.technicians)
		self.assertIn("Technician Profile", source)
		self.assertIn("tabHas Role", source, "it must fall back to the role")
		self.assertIn("a3_is_counter_terminal", source,
		              "a till is not a person who repairs things")


class TestWhoMaySeeACard(FrappeTestCase):
	def test_an_unassigned_card_is_not_hidden_from_the_bench(self):
		"""A job card carries three Employee links — who took it in, whose bench
		it is on, who handed it back. Two are blank for most of a repair's life,
		and with strict user permissions a blank link denied the whole document:
		no technician could open any job card at all, because `delivered_by` is
		empty until the moment it is delivered. Branch is what scopes this app;
		these three must not.
		"""
		meta = frappe.get_meta("Service Job Card")
		for fieldname in ("received_by", "assigned_technician", "delivered_by"):
			field = meta.get_field(fieldname)
			self.assertEqual(field.options, "Employee", fieldname)
			self.assertTrue(field.ignore_user_permissions,
			                f"{fieldname} must not gate access to the card")

	def test_no_employee_link_anywhere_can_lock_a_document(self):
		"""The same trap, across the whole app.

		Every Employee user permission turns every Employee link into a lock:
		strict mode denies the document when the link is blank or points at
		somebody else. It cost the bench its job cards, and then the counter its
		bookings — "not allowed to access this Job Card Labour record because it
		is linked to Employee HR-EMP-00022 in row 1, field Technician" — for the
		ordinary act of putting a colleague's name on a labour line.

		Branch is what scopes this app. Employee never should.
		"""
		import glob
		import json
		import os

		app = frappe.get_app_path("a3_retail")
		offenders = []
		for path in glob.glob(os.path.join(app, "a3_retail_*", "doctype", "*", "*.json")):
			stem = os.path.basename(path).replace(".json", "")
			if stem != os.path.basename(os.path.dirname(path)):
				continue
			with open(path) as handle:
				doc = json.load(handle)
			for field in doc.get("fields", []):
				if field.get("fieldtype") == "Link" \
						and field.get("options") == "Employee" \
						and not field.get("ignore_user_permissions"):
					offenders.append(f"{doc.get('name')}.{field['fieldname']}")

		self.assertEqual(
			offenders, [],
			"these Employee links will deny the whole document to anyone who is "
			"not that employee: " + ", ".join(sorted(offenders)))

	def test_branch_still_scopes_the_card(self):
		"""The fix must not open another shop's repairs."""
		meta = frappe.get_meta("Service Job Card")
		branch = meta.get_field("branch")
		self.assertEqual(branch.options, "Branch")
		self.assertFalse(branch.ignore_user_permissions,
		                 "branch is what keeps one shop out of another's repairs")
