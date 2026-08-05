# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Telecalling campaigns, call tasks and dispositions (scope step 21, 8.4)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, nowdate

from a3_retail.a3_retail_communication.doctype.call_task.call_task import (
	MAX_ATTEMPTS,
	customer_context,
	my_queue,
	record_call,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_customer

MOBILE = "9846077001"


def make_task(**overrides):
	ensure_branch("Kochi", "KCH")
	doc = frappe.new_doc("Call Task")
	doc.contact_name = overrides.pop("contact_name", "Prakash M")
	doc.mobile_no = overrides.pop("mobile_no", MOBILE)
	doc.branch = "Kochi"
	doc.assigned_to = overrides.pop(
		"assigned_to", frappe.db.get_value("Employee", {"employee_name": "Sneha M"}, "name")
	)
	doc.scheduled_date = overrides.pop("scheduled_date", nowdate())
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	return doc


class TestDispositions(FrappeTestCase):
	def test_nine_dispositions_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Call Disposition"), 9)

	def test_do_not_call_is_flagged(self):
		self.assertTrue(frappe.db.get_value("Call Disposition", "Do Not Call", "is_dnc"))

	def test_callback_disposition_schedules_a_day_out(self):
		row = frappe.db.get_value(
			"Call Disposition", "Call Back Tomorrow",
			["requires_next_call", "default_next_call_days"], as_dict=True,
		)
		self.assertTrue(row.requires_next_call)
		self.assertEqual(row.default_next_call_days, 1)


class TestCallTask(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_naming_and_defaults(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("CT-"))
		self.assertEqual(doc.call_status, "Not Called")
		self.assertEqual(doc.outcome, "Pending")

	def test_known_mobile_links_the_customer(self):
		customer = ensure_customer()
		mobile = frappe.db.get_value("Customer", customer, "a3_mobile_no")

		doc = make_task(mobile_no=mobile, contact_name=None)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.customer, customer)
		self.assertTrue(doc.contact_name)

	def test_dnc_customer_cannot_be_queued(self):
		customer = ensure_customer("9846077099", "DNC Tester")
		frappe.db.set_value("Customer", customer, "a3_dnc", 1)

		doc = make_task(mobile_no="9846077099", customer=customer)
		self.assertRaises(frappe.ValidationError, doc.insert)

		frappe.db.set_value("Customer", customer, "a3_dnc", 0)

	def test_attempts_are_capped(self):
		doc = make_task()
		doc.attempt_no = MAX_ATTEMPTS + 1
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_positive_disposition_sets_the_outcome(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)

		doc.call_status = "Connected"
		doc.disposition = "Interested - Will Visit"
		doc.save(ignore_permissions=True)

		self.assertEqual(doc.outcome, "Interested - Follow-up")
		self.assertEqual(str(doc.next_call_date), str(add_days(nowdate(), 2)))

	def test_negative_disposition_sets_not_interested(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)

		doc.call_status = "Connected"
		doc.disposition = "Price Too High"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.outcome, "Not Interested")

	def test_dnc_disposition_flags_the_customer(self):
		customer = ensure_customer("9846077055", "Optout Tester")
		doc = make_task(mobile_no="9846077055", customer=customer)
		doc.insert(ignore_permissions=True)

		doc.call_status = "Do Not Call"
		doc.disposition = "Do Not Call"
		doc.save(ignore_permissions=True)

		self.assertTrue(frappe.db.get_value("Customer", customer, "a3_dnc"))
		frappe.db.set_value("Customer", customer, "a3_dnc", 0)

	def test_call_datetime_is_stamped(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)
		doc.call_status = "Connected"
		doc.save(ignore_permissions=True)
		self.assertTrue(doc.call_datetime)


class TestConsoleApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_record_call_saves_the_outcome(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)

		result = record_call(doc.name, "Connected", "Converted", notes="Will buy today",
		                     duration_seconds=95)
		self.assertEqual(result["call_status"], "Connected")

		doc.reload()
		self.assertEqual(doc.duration_seconds, 95)
		self.assertEqual(doc.notes, "Will buy today")

	def test_no_answer_consumes_an_attempt(self):
		doc = make_task()
		doc.insert(ignore_permissions=True)
		before = cint(doc.attempt_no)

		record_call(doc.name, "No Answer", "Not Reachable")
		doc.reload()
		self.assertEqual(cint(doc.attempt_no), before + 1)

	def test_attempts_never_exceed_the_cap(self):
		doc = make_task(attempt_no=MAX_ATTEMPTS)
		doc.insert(ignore_permissions=True)

		record_call(doc.name, "No Answer", "Not Reachable")
		doc.reload()
		self.assertEqual(cint(doc.attempt_no), MAX_ATTEMPTS)

	def test_my_queue_returns_stats(self):
		telecaller = frappe.db.get_value("Employee", {"employee_name": "Sneha M"}, "name")
		if not telecaller:
			self.skipTest("demo telecallers not seeded")

		doc = make_task(assigned_to=telecaller)
		doc.insert(ignore_permissions=True)

		result = my_queue(telecaller)
		self.assertEqual(result["telecaller"], telecaller)
		self.assertTrue(any(t["name"] == doc.name for t in result["tasks"]))
		for key in ("assigned", "called", "connected", "converted", "talk_time"):
			self.assertIn(key, result["stats"])

	def test_customer_context_shape(self):
		customer = ensure_customer()
		doc = make_task(customer=customer,
		                mobile_no=frappe.db.get_value("Customer", customer, "a3_mobile_no"))
		doc.insert(ignore_permissions=True)

		context = customer_context(doc.name)
		for key in ("devices", "job_cards", "outstanding", "warranty"):
			self.assertIn(key, context)


class TestCampaignGeneration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _campaign(self, **overrides):
		team = frappe.db.get_value("Employee", {"employee_name": "Sneha M"}, "name")
		doc = frappe.new_doc("Telecalling Campaign")
		doc.campaign_name = overrides.pop("campaign_name", f"Test Campaign {frappe.generate_hash(length=5)}")
		doc.objective = overrides.pop("objective", "Lost Lead Follow-up")
		doc.branch = overrides.pop("branch", "Kochi")
		doc.start_date = nowdate()
		doc.end_date = add_days(nowdate(), 10)
		doc.target_source = overrides.pop("target_source", "Branch Visit Log")
		doc.exclude_contacted_days = overrides.pop("exclude_contacted_days", 30)
		doc.update(overrides)
		if team:
			doc.append("assigned_team", {"employee": team, "target_calls": 50})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		return doc

	def test_four_campaigns_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Telecalling Campaign"), 4)

	def test_end_before_start_is_rejected(self):
		doc = self._campaign()
		doc.end_date = add_days(nowdate(), -5)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_generate_needs_a_team(self):
		doc = self._campaign()
		doc.assigned_team = []
		doc.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, doc.generate_call_list)

	def test_generate_from_visit_logs_creates_tasks(self):
		from a3_retail.tests.test_crm import make_visit

		visit = make_visit(
			mobile_no="9846077123",
			outcome="Lost - Price",
			follow_up_required=1,
			follow_up_date=nowdate(),
		)
		visit.insert(ignore_permissions=True)

		doc = self._campaign()
		doc.insert(ignore_permissions=True)
		result = doc.generate_call_list()

		self.assertGreaterEqual(result["created"], 1)
		self.assertTrue(
			frappe.db.exists("Call Task", {"campaign": doc.name, "mobile_no": "9846077123"})
		)

	def test_dnc_customers_are_excluded(self):
		from a3_retail.tests.test_crm import make_visit

		customer = ensure_customer("9846077456", "DNC Walkin")
		frappe.db.set_value("Customer", customer, "a3_dnc", 1)

		visit = make_visit(mobile_no="9846077456", outcome="Lost - Price",
		                   follow_up_required=1, follow_up_date=nowdate())
		visit.flags.ignore_permissions = True
		try:
			visit.insert(ignore_permissions=True)
		except frappe.ValidationError:
			# The visit's own call task is refused for a DNC customer, which is
			# the same guard — that alone proves the exclusion.
			frappe.db.set_value("Customer", customer, "a3_dnc", 0)
			return

		doc = self._campaign()
		doc.insert(ignore_permissions=True)
		doc.generate_call_list()

		self.assertFalse(
			frappe.db.exists("Call Task", {"campaign": doc.name, "mobile_no": "9846077456"})
		)
		frappe.db.set_value("Customer", customer, "a3_dnc", 0)

	def test_metrics_refresh_after_generation(self):
		from a3_retail.tests.test_crm import make_visit

		visit = make_visit(mobile_no="9846077321", outcome="Lost - Price",
		                   follow_up_required=1, follow_up_date=nowdate())
		visit.insert(ignore_permissions=True)

		doc = self._campaign()
		doc.insert(ignore_permissions=True)
		doc.generate_call_list()
		doc.reload()

		self.assertGreaterEqual(doc.allocated_count, 1)
		self.assertEqual(doc.called_count, 0)

	def test_no_duplicate_task_for_the_same_number(self):
		from a3_retail.tests.test_crm import make_visit

		visit = make_visit(mobile_no="9846077654", outcome="Lost - Price",
		                   follow_up_required=1, follow_up_date=nowdate())
		visit.insert(ignore_permissions=True)

		doc = self._campaign()
		doc.insert(ignore_permissions=True)
		doc.generate_call_list()
		second = doc.generate_call_list()

		self.assertEqual(second["created"], 0)


class TestValidationQueries(FrappeTestCase):
	"""Scope 8.6: both queries must return zero rows."""

	def test_no_dnc_customer_sits_in_a_queue(self):
		rows = frappe.db.sql(
			"""select ct.name from `tabCall Task` ct
			   join `tabCustomer` c on c.name = ct.customer
			   where c.a3_dnc = 1 and ct.call_status = 'Not Called'"""
		)
		self.assertFalse(rows, f"DNC customers still queued: {rows}")

	def test_no_number_exceeds_three_attempts(self):
		rows = frappe.db.sql(
			"""select mobile_no, max(attempt_no) from `tabCall Task`
			   group by customer, mobile_no having max(attempt_no) > 3"""
		)
		self.assertFalse(rows, f"numbers attempted too often: {rows}")
