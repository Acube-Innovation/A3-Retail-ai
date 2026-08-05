# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Portal pages, signed links, online payments and the security audit (step 26)."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.api import payments, portal
from a3_retail.setup import audit
from a3_retail.tests.fixtures import ensure_branch, ensure_customer
from a3_retail.utils import tokens

PORTAL_PAGES = [
	("track_service", "/track-service"),
	("warranty_certificate", "/warranty/<token>"),
	("pay_online", "/pay/<token>"),
	("invoice_download", "/invoice/<token>"),
	("support", "/support"),
	("feedback", "/feedback/<token>"),
	("offers", "/offers"),
	("stores", "/stores"),
	("approve_estimate", "/approve-estimate/<token>"),
]


class TestPortalPages(FrappeTestCase):
	def test_nine_pages_exist(self):
		import os

		folder = frappe.get_app_path("a3_retail", "templates", "pages")
		self.assertEqual(len(PORTAL_PAGES), 9)
		for name, _route in PORTAL_PAGES:
			self.assertTrue(os.path.exists(os.path.join(folder, f"{name}.html")), name)
			self.assertTrue(os.path.exists(os.path.join(folder, f"{name}.py")), name)

	def test_token_routes_are_registered(self):
		rules = {rule["from_route"] for rule in frappe.get_hooks("website_route_rules")}
		for _name, route in PORTAL_PAGES:
			if "<token>" in route or route == "/track-service":
				self.assertIn(route, rules, route)

	def test_the_portal_stylesheet_is_included(self):
		self.assertIn("a3_portal.css", str(frappe.get_hooks("web_include_css")))


class TestSignedTokens(FrappeTestCase):
	def test_a_token_round_trips(self):
		token = tokens.sign("Branch", "Kochi", "test")
		self.assertEqual(tokens.verify(token, "Branch", "test"), "Kochi")

	def test_a_tampered_token_is_refused(self):
		token = tokens.sign("Branch", "Kochi", "test")
		self.assertIsNone(tokens.verify(token[:-1] + "0", "Branch", "test"))

	def test_a_token_is_bound_to_its_purpose(self):
		token = tokens.sign("Branch", "Kochi", "payment")
		self.assertIsNone(tokens.verify(token, "Branch", "invoice"))

	def test_a_token_is_bound_to_its_doctype(self):
		token = tokens.sign("Branch", "Kochi", "test")
		self.assertIsNone(tokens.verify(token, "Customer", "test"))

	def test_a_token_for_a_deleted_document_is_refused(self):
		token = tokens.sign("Branch", "Nowhere Branch", "test")
		self.assertIsNone(tokens.verify(token, "Branch", "test"))

	def test_rubbish_is_refused(self):
		for value in ("", "nonsense", "no-separator"):
			self.assertIsNone(tokens.verify(value, "Branch", "test"))

	def test_portal_url_is_absolute(self):
		url = tokens.portal_url("Branch", "Kochi", "pay", "payment")
		self.assertIn("/pay/Kochi.", url)
		self.assertTrue(url.startswith("http"))


class TestPublicEndpoints(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_store_locator_lists_branches(self):
		stores = portal.store_locator()
		self.assertTrue(stores)
		for key in ("branch", "address", "phone", "latitude"):
			self.assertIn(key, stores[0])

	def test_offers_are_public_but_only_active_ones(self):
		offers = portal.active_offers()
		self.assertIsInstance(offers, list)
		for offer in offers:
			self.assertEqual(
				frappe.db.get_value("Seasonal Offer Campaign", offer["name"], "status"), "Active"
			)


class TestTrackService(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_tracking_needs_a_verified_otp(self):
		self.assertRaises(
			frappe.PermissionError, portal.track_service, "JC-KCH-26-00001", "9847012345", "bogus"
		)

	def test_a_verified_customer_sees_their_repair(self):
		job = frappe.db.get_value(
			"Service Job Card", {"docstatus": 1, "customer_mobile": ["is", "set"]},
			["name", "customer_mobile"], as_dict=True,
		)
		if not job:
			self.skipTest("no job card with a mobile number")

		token = portal._issue_session_token(job.customer_mobile, "Service Tracking")
		result = portal.track_service(job.name, job.customer_mobile, token)

		self.assertEqual(result["job_card"], job.name)
		self.assertIn("timeline", result)
		self.assertEqual(len(result["timeline"]), len(portal.TIMELINE_STAGES))

	def test_an_otp_for_another_number_is_refused(self):
		job = frappe.db.get_value(
			"Service Job Card", {"docstatus": 1, "customer_mobile": ["is", "set"]},
			["name", "customer_mobile"], as_dict=True,
		)
		if not job:
			self.skipTest("no job card with a mobile number")

		token = portal._issue_session_token("9000000000", "Service Tracking")
		self.assertRaises(
			frappe.PermissionError, portal.track_service, job.name, job.customer_mobile, token
		)

	def test_an_unknown_reference_is_not_found(self):
		token = portal._issue_session_token("9847012345", "Service Tracking")
		self.assertRaises(
			frappe.ValidationError, portal.track_service, "JC-NOPE", "9847012345", token
		)


class TestComplaintsAndFeedback(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		ensure_customer()
		frappe.db.commit()

	def test_a_complaint_needs_a_verified_otp(self):
		self.assertRaises(
			frappe.PermissionError, portal.submit_complaint, "Broken", "Details", "9847012345",
			"bogus",
		)

	def test_a_complaint_creates_an_issue(self):
		token = portal._issue_session_token("9847012345", "Complaint")
		result = portal.submit_complaint(
			"Repair took too long", "Promised Tuesday, delivered Friday", "9847012345", token,
			branch="Kochi", category="Service Delay",
		)
		issue = frappe.get_doc("Issue", result["issue"])
		self.assertEqual(issue.status, "Open")
		self.assertEqual(issue.a3_branch, "Kochi")
		self.assertEqual(issue.a3_channel, "Website")

	def test_an_empty_complaint_is_refused(self):
		token = portal._issue_session_token("9847012345", "Complaint")
		self.assertRaises(
			frappe.ValidationError, portal.submit_complaint, "  ", "", "9847012345", token
		)

	def test_feedback_needs_a_valid_link(self):
		self.assertRaises(frappe.PermissionError, portal.submit_feedback, "bogus", 5)

	def test_feedback_records_a_rating_on_the_job_card(self):
		job = frappe.db.get_value(
			"Service Job Card",
			{"docstatus": 1, "status": ["in", ["Delivered", "Closed"]],
			 "customer_feedback": ["is", "not set"]},
			"name",
		)
		if not job:
			self.skipTest("no delivered job card without feedback")

		token = tokens.sign("Service Job Card", job, "feedback")
		result = portal.submit_feedback(token, 5, comments="Quick and polite")

		feedback = frappe.get_doc("Customer Feedback", result["feedback"])
		self.assertEqual(feedback.channel, "Web Portal")
		self.assertEqual(flt(feedback.overall_rating), 1.0)
		self.assertEqual(feedback.sentiment, "Promoter")
		self.assertEqual(frappe.db.get_value("Service Job Card", job, "customer_feedback"),
		                 feedback.name)

	def test_feedback_is_recorded_once(self):
		job = frappe.db.get_value(
			"Service Job Card", {"docstatus": 1, "customer_feedback": ["is", "set"]}, "name"
		)
		if not job:
			self.skipTest("no job card with feedback")

		token = tokens.sign("Service Job Card", job, "feedback")
		result = portal.submit_feedback(token, 3)
		self.assertTrue(result.get("already_submitted"))


class TestPayments(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_an_invalid_payment_link_is_refused(self):
		self.assertRaises(frappe.PermissionError, payments.payment_context, "bogus")

	def test_the_payment_page_shows_what_is_due(self):
		invoice = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "outstanding_amount": [">", 0]}, "name"
		)
		if not invoice:
			self.skipTest("no invoice with an outstanding amount")

		token = tokens.sign("Sales Invoice", invoice, "payment")
		context = payments.payment_context(token)

		self.assertEqual(context["reference_name"], invoice)
		self.assertGreater(context["amount"], 0)
		self.assertEqual(context["currency"], "INR")

	def test_a_job_card_link_reads_the_job_card(self):
		job = frappe.db.get_value("Service Job Card", {"docstatus": 1}, "name")
		token = tokens.sign("Service Job Card", job, "payment")
		context = payments.payment_context(token)
		self.assertEqual(context["reference_doctype"], "Service Job Card")

	def test_an_unsigned_webhook_is_rejected(self):
		self.assertFalse(payments.verify_signature("{}", None))
		self.assertFalse(payments.verify_signature("{}", "deadbeef"))

	def test_a_correctly_signed_webhook_is_accepted(self):
		import hashlib
		import hmac

		secret = "test-webhook-secret"
		frappe.db.set_single_value("A3 Retail Settings", "razorpay_webhook_secret", secret)

		body = json.dumps({"event": "payment.captured"})
		signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
		self.assertTrue(payments.verify_signature(body, signature))

		frappe.db.set_single_value("A3 Retail Settings", "razorpay_webhook_secret", "")

	def test_no_secret_means_no_trust(self):
		frappe.db.set_single_value("A3 Retail Settings", "razorpay_webhook_secret", "")
		self.assertFalse(payments.verify_signature("{}", "anything"))

	def test_unmatched_transactions_reports_a_list(self):
		self.assertIsInstance(payments.unmatched_transactions(30), list)

	def test_a_payment_request_is_not_created_without_the_setting(self):
		frappe.db.set_single_value("A3 Retail Settings", "enable_online_payment", 0)
		job = frappe.get_doc("Service Job Card",
		                     frappe.db.get_value("Service Job Card", {"docstatus": 1}, "name"))
		job.status = "Ready for Delivery"
		before = frappe.db.count("Payment Request")
		payments.request_on_ready_for_delivery(job)
		self.assertEqual(frappe.db.count("Payment Request"), before)


class TestSecurityAudit(FrappeTestCase):
	"""Scope step 26 — every whitelisted method must check something."""

	def test_no_unguarded_whitelisted_method(self):
		result = audit.run(verbose=False)
		self.assertGreater(result["whitelisted"], 50)
		self.assertEqual(
			result["unguarded"], [],
			f"whitelisted without a permission check: {[f['method'] for f in result['unguarded']]}",
		)

	def test_no_endpoint_bypasses_permissions_silently(self):
		findings = audit.ignore_permissions_audit(verbose=False)
		self.assertEqual(findings, [], f"unguarded ignore_permissions: {findings}")

	def test_every_documented_exception_still_exists(self):
		for method in audit.DOCUMENTED_EXCEPTIONS:
			self.assertTrue(frappe.get_attr(method), method)


class TestDemoDataset(FrappeTestCase):
	"""Scope 14 — the seed order table is complete and the checks pass."""

	def test_every_seed_script_is_present(self):
		from a3_retail.demo.install import _seed_scripts

		orders = [order for order, _name, _path in _seed_scripts()]
		self.assertEqual(orders, [f"{index:02d}" for index in range(1, 27)])

	def test_verification_passes(self):
		from a3_retail.demo import verify

		result = verify.run(verbose=False)
		failed = [row[0] for row in result["rows"] if row[3] == "FAIL"]
		self.assertEqual(failed, [], f"failing demo checks: {failed}")

	def test_wipe_refuses_outside_developer_mode(self):
		from a3_retail.demo import install

		if frappe.conf.get("developer_mode"):
			self.skipTest("developer mode is on, wipe is allowed here")
		self.assertRaises(frappe.ValidationError, install.wipe)
