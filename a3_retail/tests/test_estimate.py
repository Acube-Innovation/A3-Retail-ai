# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Service Estimate and portal approval (scope step 8, section 3.4)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from a3_retail.a3_retail_service.doctype.service_estimate.service_estimate import (
	create_from_job_card,
	expire_stale_estimates,
	hash_token,
	resolve_token,
)
from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.tests.fixtures import ensure_branch
from a3_retail.tests.test_job_card import make_job_card


def make_estimate(**overrides):
	job = make_job_card()
	job.insert(ignore_permissions=True)
	job.submit()
	job.status = st.UNDER_DIAGNOSIS
	job.save(ignore_permissions=True)

	estimate = frappe.new_doc("Service Estimate")
	estimate.job_card = job.name
	estimate.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
	estimate.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
	estimate.update(overrides)
	estimate.flags.ignore_permissions = True
	estimate.insert(ignore_permissions=True)
	return estimate, job


class TestServiceEstimate(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_naming_and_details_pulled_from_job_card(self):
		estimate, job = make_estimate()
		self.assertTrue(estimate.name.startswith("EST-KCH-"), estimate.name)
		self.assertEqual(estimate.customer, job.customer)
		self.assertEqual(estimate.imei_1, job.imei_1)

	def test_totals_match_the_demo_row(self):
		"""Scope 3.13: 8,400 + 700 = 9,100 net, 1,638 GST, 10,738 total."""
		estimate, _ = make_estimate()
		self.assertEqual(flt(estimate.net_total), 9100.0)
		self.assertEqual(flt(estimate.tax_amount), 1638.0)
		self.assertEqual(flt(estimate.grand_total), 10738.0)

	def test_unticked_optional_lines_are_excluded(self):
		estimate, _ = make_estimate()
		estimate.append(
			"labour",
			{"service_item": "SRV-DIAG", "qty": 1, "rate": 200, "is_optional": 1, "is_approved": 0},
		)
		estimate.save(ignore_permissions=True)
		# The optional 200 must not appear in the total.
		self.assertEqual(flt(estimate.labour_total), 700.0)

	def test_valid_till_defaults_to_three_days(self):
		estimate, _ = make_estimate()
		self.assertEqual(str(estimate.valid_till), str(add_days(estimate.estimate_date, 3)))

	def test_valid_till_before_estimate_date_is_rejected(self):
		estimate, _ = make_estimate()
		estimate.valid_till = add_days(estimate.estimate_date, -1)
		self.assertRaises(frappe.ValidationError, estimate.save)

	def test_submit_issues_a_hashed_token(self):
		estimate, job = make_estimate()
		estimate.submit()

		token = estimate.flags.portal_token
		self.assertTrue(token)
		estimate.reload()
		# Only the hash is stored, never the token itself.
		self.assertEqual(estimate.portal_token_hash, hash_token(token))
		self.assertNotIn(token, estimate.portal_token_hash)
		self.assertIn(token, estimate.portal_url)
		self.assertEqual(estimate.approval_status, "Sent")

	def test_job_card_follows_the_estimate(self):
		estimate, job = make_estimate()
		estimate.submit()
		job.reload()
		self.assertEqual(job.status, st.ESTIMATE_SENT)
		self.assertEqual(job.estimate_status, "Sent")
		self.assertEqual(job.service_estimate, estimate.name)

	def test_token_resolves_to_the_estimate(self):
		estimate, _ = make_estimate()
		estimate.submit()
		resolved = resolve_token(estimate.flags.portal_token)
		self.assertEqual(resolved.name, estimate.name)

	def test_unknown_token_is_refused(self):
		self.assertRaises(frappe.PermissionError, resolve_token, "not-a-real-token")
		self.assertRaises(frappe.PermissionError, resolve_token, "")

	def test_approval_creates_a_maintenance_sales_order(self):
		estimate, job = make_estimate()
		estimate.submit()
		estimate.record_decision("Approved", approver_name="Rahul Krishnan")

		self.assertEqual(estimate.approval_status, "Approved")
		self.assertTrue(estimate.sales_order)

		order = frappe.get_doc("Sales Order", estimate.sales_order)
		self.assertEqual(order.order_type, "Maintenance")
		self.assertEqual(order.a3_service_job_card, job.name)

		job.reload()
		self.assertEqual(job.status, st.ESTIMATE_APPROVED)

	def test_token_cannot_be_reused_after_a_decision(self):
		"""Scope step 8: a token is single-use."""
		estimate, _ = make_estimate()
		estimate.submit()
		estimate.record_decision("Approved", approver_name="Rahul")

		self.assertRaises(frappe.ValidationError, estimate.record_decision, "Rejected")

	def test_expired_estimate_refuses_approval(self):
		estimate, _ = make_estimate()
		estimate.submit()
		frappe.db.set_value("Service Estimate", estimate.name, "valid_till", add_days(nowdate(), -1))
		estimate.reload()

		self.assertRaises(frappe.ValidationError, estimate.record_decision, "Approved")

	def test_rejection_moves_the_job_card(self):
		estimate, job = make_estimate()
		estimate.submit()
		estimate.record_decision("Rejected", remarks="Too expensive")

		job.reload()
		self.assertEqual(job.status, st.ESTIMATE_REJECTED)

	def test_revision_supersedes_the_original(self):
		estimate, _ = make_estimate()
		estimate.submit()
		revision = estimate.create_revision()

		self.assertEqual(revision.revision_of, estimate.name)
		self.assertEqual(revision.version_no, 2)
		self.assertEqual(revision.approval_status, "Pending")

		estimate.reload()
		self.assertEqual(estimate.approval_status, "Expired")

	def test_scheduler_expires_stale_estimates(self):
		estimate, _ = make_estimate()
		estimate.submit()
		frappe.db.set_value("Service Estimate", estimate.name, "valid_till", add_days(nowdate(), -2))

		expire_stale_estimates()
		self.assertEqual(
			frappe.db.get_value("Service Estimate", estimate.name, "approval_status"), "Expired"
		)

	def test_create_from_job_card_copies_lines(self):
		job = make_job_card()
		job.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
		job.append("labour", {"service_item": "SRV-LAB-L2", "qty": 1, "rate": 700})
		job.insert(ignore_permissions=True)
		job.submit()
		job.status = st.UNDER_DIAGNOSIS
		job.save(ignore_permissions=True)

		name = create_from_job_card(job.name)
		estimate = frappe.get_doc("Service Estimate", name)
		self.assertEqual(len(estimate.parts), 1)
		self.assertEqual(len(estimate.labour), 1)

		job.reload()
		self.assertEqual(job.status, st.ESTIMATE_PENDING)


class TestPortalOTP(FrappeTestCase):
	MOBILE = "9847012345"

	def tearDown(self):
		frappe.db.delete("Portal OTP", {"mobile_no": self.MOBILE})
		frappe.db.commit()

	def test_otp_is_stored_hashed(self):
		from a3_retail.api.portal import _hash, request_otp

		frappe.conf.developer_mode = 1
		result = request_otp(self.MOBILE, purpose="Estimate Approval")
		otp = result["otp"]

		stored = frappe.db.get_value(
			"Portal OTP", {"mobile_no": self.MOBILE}, "otp_hash", order_by="creation desc"
		)
		self.assertEqual(stored, _hash(otp))
		self.assertNotEqual(stored, otp)

	def test_correct_otp_verifies_and_returns_a_session(self):
		from a3_retail.api.portal import request_otp, verify_otp

		frappe.conf.developer_mode = 1
		otp = request_otp(self.MOBILE, purpose="Estimate Approval")["otp"]
		result = verify_otp(self.MOBILE, otp, purpose="Estimate Approval")

		self.assertTrue(result["verified"])
		self.assertTrue(result["token"])

	def test_wrong_otp_is_rejected_and_burns_an_attempt(self):
		from a3_retail.api.portal import request_otp, verify_otp

		frappe.conf.developer_mode = 1
		request_otp(self.MOBILE, purpose="Estimate Approval")

		self.assertRaises(frappe.ValidationError, verify_otp, self.MOBILE, "000000", "Estimate Approval")
		attempts = frappe.db.get_value(
			"Portal OTP", {"mobile_no": self.MOBILE}, "attempts", order_by="creation desc"
		)
		self.assertEqual(attempts, 1)

	def test_rate_limit_blocks_the_sixth_request(self):
		from a3_retail.api.portal import request_otp

		frappe.conf.developer_mode = 1
		for _ in range(5):
			request_otp(self.MOBILE, purpose="Estimate Approval")

		self.assertRaises(Exception, request_otp, self.MOBILE, "Estimate Approval")

	def test_invalid_mobile_is_rejected(self):
		from a3_retail.api.portal import request_otp

		self.assertRaises(frappe.ValidationError, request_otp, "12345")
