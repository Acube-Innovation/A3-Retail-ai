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

	def test_branch_still_scopes_the_card(self):
		"""The fix must not open another shop's repairs."""
		meta = frappe.get_meta("Service Job Card")
		branch = meta.get_field("branch")
		self.assertEqual(branch.options, "Branch")
		self.assertFalse(branch.ignore_user_permissions,
		                 "branch is what keeps one shop out of another's repairs")
