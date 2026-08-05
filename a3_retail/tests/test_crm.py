# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Footfall, CRM and helpdesk (scope step 20, doc 08)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime, nowdate

from a3_retail.a3_retail_operations.doctype.customer_feedback.customer_feedback import (
	_stars,
	nps_summary,
)
from a3_retail.a3_retail_sales.doctype.branch_visit_log.branch_visit_log import (
	conversion_summary,
	link_conversion,
	log_visit,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_customer, ensure_sales_invoice


def make_visit(**overrides):
	ensure_branch("Kochi", "KCH")
	employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")

	doc = frappe.new_doc("Branch Visit Log")
	doc.branch = "Kochi"
	doc.visit_datetime = overrides.pop("visit_datetime", now_datetime())
	doc.visitor_name = overrides.pop("visitor_name", "Prakash M")
	doc.mobile_no = overrides.pop("mobile_no", "9846011223")
	doc.purpose = overrides.pop("purpose", "New Device Enquiry")
	doc.budget_range = overrides.pop("budget_range", "10K - 20K")
	doc.attended_by = overrides.pop("attended_by", employee)
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	return doc


class TestVisitLog(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_naming_carries_the_branch(self):
		doc = make_visit()
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("FL-KCH-"), doc.name)

	def test_known_mobile_is_recognised(self):
		customer = ensure_customer()
		mobile = frappe.db.get_value("Customer", customer, "a3_mobile_no")

		doc = make_visit(mobile_no=mobile)
		doc.insert(ignore_permissions=True)

		self.assertTrue(doc.is_existing_customer)
		self.assertEqual(doc.customer, customer)
		self.assertEqual(doc.visitor_type, "Repeat Customer")

	def test_unknown_mobile_stays_a_new_walkin(self):
		doc = make_visit(mobile_no="9000012345")
		doc.insert(ignore_permissions=True)
		self.assertFalse(doc.is_existing_customer)
		self.assertEqual(doc.visitor_type, "New Walk-in")

	def test_mobile_is_normalised(self):
		doc = make_visit(mobile_no="+91 98460 11223")
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.mobile_no, "9846011223")

	def test_converted_visit_carries_the_sale_value(self):
		invoice = ensure_sales_invoice()
		doc = make_visit(outcome="Converted - Sale", reference_type="Sales Invoice",
		                 reference_name=invoice)
		doc.insert(ignore_permissions=True)
		self.assertGreater(flt(doc.sale_value), 0)

	def test_lost_visit_raises_a_call_task(self):
		if not frappe.db.exists("DocType", "Call Task"):
			self.skipTest("Call Task arrives in step 21")
		doc = make_visit(
			outcome="Lost - Stock Unavailable",
			follow_up_required=1,
			follow_up_date=nowdate(),
		)
		doc.insert(ignore_permissions=True)
		doc.reload()

		self.assertTrue(doc.call_task, "no call task was created for the lost visit")
		task = frappe.get_doc("Call Task", doc.call_task)
		self.assertEqual(task.mobile_no, doc.mobile_no)

	def test_lead_outcome_creates_a_lead(self):
		doc = make_visit(outcome="Lead Created (Follow-up)")
		doc.insert(ignore_permissions=True)
		doc.reload()

		self.assertTrue(doc.lead, "no lead was created")
		lead = frappe.get_doc("Lead", doc.lead)
		self.assertEqual(lead.a3_branch, "Kochi")
		self.assertEqual(lead.a3_visit_log, doc.name)

	def test_pending_visit_creates_no_followups(self):
		doc = make_visit()
		doc.insert(ignore_permissions=True)
		doc.reload()
		self.assertFalse(doc.call_task)
		self.assertFalse(doc.lead)


class TestConversionLinking(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_a_sale_back_links_to_todays_visit(self):
		doc = make_visit(mobile_no="9846099001")
		doc.insert(ignore_permissions=True)

		invoice = ensure_sales_invoice()
		linked = link_conversion("Sales Invoice", invoice, "9846099001", branch="Kochi")

		self.assertEqual(linked, doc.name)
		doc.reload()
		self.assertEqual(doc.outcome, "Converted - Sale")
		self.assertEqual(doc.reference_name, invoice)

	def test_a_job_card_records_a_service_conversion(self):
		from a3_retail.tests.test_job_card import make_job_card

		doc = make_visit(mobile_no="9846099002", purpose="Service / Repair")
		doc.insert(ignore_permissions=True)

		job = make_job_card()
		job.insert(ignore_permissions=True)
		job.submit()

		link_conversion("Service Job Card", job.name, "9846099002", branch="Kochi")
		doc.reload()
		self.assertEqual(doc.outcome, "Converted - Job Card")

	def test_no_open_visit_links_nothing(self):
		self.assertIsNone(link_conversion("Sales Invoice", "X", "9000099999"))

	def test_conversion_summary_shape(self):
		summary = conversion_summary(branch="Kochi")
		for key in ("visits", "converted", "lost", "leads", "conversion_percent", "average_ticket"):
			self.assertIn(key, summary)


class TestFootfallApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_log_visit_creates_a_record(self):
		result = log_visit(
			{
				"branch": "Kochi",
				"visitor_name": "Nithin Jose",
				"mobile_no": "9605022334",
				"purpose": "EMI Enquiry",
				"budget_range": "20K - 35K",
			}
		)
		self.assertTrue(result["visit_log"].startswith("FL-KCH-"))


class TestFeedback(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _feedback(self, rating, **overrides):
		doc = frappe.new_doc("Customer Feedback")
		doc.feedback_date = nowdate()
		doc.customer = ensure_customer()
		doc.branch = "Kochi"
		doc.channel = "WhatsApp"
		doc.overall_rating = rating
		doc.update(overrides)
		doc.flags.ignore_permissions = True
		return doc

	def test_rating_scale_conversion(self):
		# Frappe stores a Rating as 0–1.
		self.assertEqual(_stars(1.0), 5.0)
		self.assertEqual(_stars(0.4), 2.0)
		self.assertEqual(_stars(4), 4.0)

	def test_five_star_is_a_promoter(self):
		doc = self._feedback(1.0)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.sentiment, "Promoter")
		self.assertFalse(doc.requires_follow_up)

	def test_four_star_is_passive(self):
		doc = self._feedback(0.8)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.sentiment, "Passive")

	def test_two_star_is_a_detractor(self):
		doc = self._feedback(0.4)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.sentiment, "Detractor")
		self.assertTrue(doc.requires_follow_up)

	def test_detractor_opens_an_issue(self):
		doc = self._feedback(0.4, comments="Touch still not smooth after repair")
		doc.insert(ignore_permissions=True)
		doc.reload()

		self.assertTrue(doc.follow_up_issue, "no issue was opened for the detractor")
		issue = frappe.get_doc("Issue", doc.follow_up_issue)
		self.assertEqual(issue.a3_branch, "Kochi")
		self.assertEqual(issue.a3_severity, "High")

	def test_promoter_opens_no_issue(self):
		doc = self._feedback(1.0)
		doc.insert(ignore_permissions=True)
		doc.reload()
		self.assertFalse(doc.follow_up_issue)

	def test_nps_summary_shape(self):
		summary = nps_summary("Kochi")
		for key in ("responses", "promoters", "passives", "detractors", "nps", "average_rating"):
			self.assertIn(key, summary)


class TestHelpdeskSetup(FrappeTestCase):
	def test_issue_types_are_created(self):
		for name in ("Service Complaint", "Billing Query", "Warranty Query"):
			self.assertTrue(frappe.db.exists("Issue Type", name), name)

	def test_issue_custom_fields_exist(self):
		meta = frappe.get_meta("Issue")
		for fieldname in ("a3_branch", "a3_complaint_category", "a3_severity", "a3_escalation_level",
		                  "a3_job_card", "a3_csat_score"):
			self.assertTrue(meta.has_field(fieldname), fieldname)

	def test_sla_tiers_are_configured(self):
		if not frappe.db.exists("Service Level Agreement", "A3 Retail Support SLA"):
			self.skipTest("SLA not created on this site")

		rows = frappe.get_all(
			"Service Level Priority",
			filters={"parent": "A3 Retail Support SLA"},
			fields=["priority", "first_response_time", "resolution_time"],
		)
		by_priority = {r.priority: r for r in rows}
		self.assertIn("Critical", by_priority)
		# Critical: 30 minutes to respond, 4 hours to resolve.
		self.assertEqual(by_priority["Critical"].first_response_time, 1800)
		self.assertEqual(by_priority["Critical"].resolution_time, 14400)

	def test_escalation_ladder_runs(self):
		from a3_retail.setup.helpdesk import escalate_breached_issues

		self.assertIsInstance(escalate_breached_issues(), int)

	def test_lead_custom_fields_exist(self):
		meta = frappe.get_meta("Lead")
		for fieldname in ("a3_branch", "a3_visit_log", "a3_budget_range", "a3_emi_required"):
			self.assertTrue(meta.has_field(fieldname), fieldname)
