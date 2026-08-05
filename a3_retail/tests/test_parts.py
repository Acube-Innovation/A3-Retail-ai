# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Parts request lifecycle and the TAT pause (scope step 11, section 3.11)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, flt, now_datetime

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.a3_retail_service.doctype.service_job_card.service_job_card import flag_delayed_job_cards
from a3_retail.a3_retail_service.parts import (
	find_branch_with_stock,
	log_work_minutes,
	my_job_cards,
	parts_position,
	request_part,
	resume_if_parts_ready,
)
from a3_retail.tests.fixtures import ensure_branch
from a3_retail.tests.test_job_card import make_job_card


def job_card_with_part(**overrides):
	doc = make_job_card(warranty_type="Out of Warranty", **overrides)
	doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
	doc.insert(ignore_permissions=True)
	doc.submit()
	doc.status = st.UNDER_DIAGNOSIS
	doc.save(ignore_permissions=True)
	doc.status = st.IN_PROGRESS
	doc.save(ignore_permissions=True)
	doc.reload()
	return doc


class TestPartsRequest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		ensure_branch("Thiruvananthapuram", "TVM")
		frappe.db.commit()

	def test_request_raises_a_material_request_when_nobody_has_stock(self):
		doc = job_card_with_part()
		result = request_part(doc.name, doc.parts[0].name, source="purchase")

		self.assertEqual(result["action"], "purchase")
		self.assertTrue(frappe.db.exists("Material Request", result["material_request"]))

		doc.reload()
		self.assertEqual(doc.parts[0].part_status, "Awaiting Purchase")

	def test_requesting_a_part_parks_the_job_card(self):
		doc = job_card_with_part()
		request_part(doc.name, doc.parts[0].name, source="purchase")

		doc.reload()
		self.assertEqual(doc.status, st.AWAITING_PARTS)
		self.assertEqual(doc.delay_reason, "Awaiting Parts")

	def test_material_request_carries_branch_and_service_warehouse(self):
		doc = job_card_with_part()
		result = request_part(doc.name, doc.parts[0].name, source="purchase")

		request = frappe.get_doc("Material Request", result["material_request"])
		# Material Request carries no branch dimension; the target warehouse is
		# what ties the request to the branch.
		self.assertIn("Kochi Service Bay", request.items[0].warehouse)
		self.assertEqual(
			frappe.db.get_value("Warehouse", request.items[0].warehouse, "custom_branch"), "Kochi"
		)

	def test_find_branch_with_stock_returns_none_when_empty(self):
		self.assertIsNone(find_branch_with_stock("SPR-CHP-IC-PWR", 5, "Kochi"))

	def test_receiving_the_last_part_resumes_the_job(self):
		from a3_retail.a3_retail_service.parts import mark_part_received

		doc = job_card_with_part()
		request_part(doc.name, doc.parts[0].name, source="purchase")
		doc.reload()
		self.assertEqual(doc.status, st.AWAITING_PARTS)

		result = mark_part_received(doc.name, doc.parts[0].name)
		self.assertTrue(result["job_card_resumed"])

		doc.reload()
		self.assertEqual(doc.status, st.IN_PROGRESS)
		self.assertIsNone(doc.delay_reason)

	def test_job_stays_parked_while_any_part_is_outstanding(self):
		from a3_retail.a3_retail_service.parts import mark_part_received

		doc = make_job_card(warranty_type="Out of Warranty")
		doc.append("parts", {"item_code": "SPR-DSP-A55", "qty": 1, "rate": 8400})
		doc.append("parts", {"item_code": "SPR-BAT-N13", "qty": 1, "rate": 1250})
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.status = st.UNDER_DIAGNOSIS
		doc.save(ignore_permissions=True)
		doc.status = st.IN_PROGRESS
		doc.save(ignore_permissions=True)
		doc.reload()

		request_part(doc.name, doc.parts[0].name, source="purchase")
		request_part(doc.name, doc.parts[1].name, source="purchase")

		mark_part_received(doc.name, doc.parts[0].name)
		doc.reload()
		self.assertEqual(doc.status, st.AWAITING_PARTS)

		mark_part_received(doc.name, doc.parts[1].name)
		doc.reload()
		self.assertEqual(doc.status, st.IN_PROGRESS)

	def test_resume_is_a_noop_when_not_awaiting(self):
		doc = job_card_with_part()
		self.assertFalse(resume_if_parts_ready(doc.name))


class TestTATPause(FrappeTestCase):
	"""Scope step 11 acceptance: 20 hours awaiting parts must not breach a 48 h TAT."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_paused_hours_extend_the_sla(self):
		doc = job_card_with_part()
		before = doc.sla_due_on

		# Simulate 20 hours spent waiting for a part.
		doc.paused_hours = 20
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		doc.reload()

		self.assertGreater(doc.sla_due_on, before)

	def test_a_paused_job_within_tat_is_not_flagged_delayed(self):
		doc = job_card_with_part(received_on=add_to_date(now_datetime(), hours=-30))
		doc.paused_hours = 20
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		doc.reload()

		flag_delayed_job_cards()
		doc.reload()
		self.assertFalse(doc.is_delayed, f"sla_due_on was {doc.sla_due_on}")


class TestWorkbench(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_my_job_cards_groups_by_status(self):
		technician = frappe.db.get_value("Employee", {"employee_name": "Vishnu P"}, "name")
		if not technician:
			self.skipTest("demo technicians not seeded")

		doc = job_card_with_part()
		doc.assigned_technician = technician
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

		result = my_job_cards(technician)
		self.assertEqual(result["technician"], technician)
		self.assertIn(st.IN_PROGRESS, result["columns"])
		self.assertGreaterEqual(result["total"], 1)

	def test_log_work_minutes_creates_a_labour_row(self):
		doc = job_card_with_part()
		log_work_minutes(doc.name, 45)

		doc.reload()
		self.assertTrue(doc.labour)
		self.assertEqual(flt(doc.labour[0].minutes), 45.0)

	def test_logging_twice_accumulates_minutes(self):
		doc = job_card_with_part()
		log_work_minutes(doc.name, 30)
		log_work_minutes(doc.name, 15)

		doc.reload()
		self.assertEqual(flt(doc.labour[0].minutes), 45.0)

	def test_zero_minutes_is_rejected(self):
		doc = job_card_with_part()
		self.assertRaises(frappe.ValidationError, log_work_minutes, doc.name, 0)

	def test_parts_position_lists_outstanding_items(self):
		doc = job_card_with_part()
		request_part(doc.name, doc.parts[0].name, source="purchase")

		rows = parts_position("Kochi")
		self.assertTrue(any(r["item_code"] == "SPR-DSP-A55" for r in rows))

	def test_workbench_page_is_registered_and_restricted(self):
		self.assertTrue(frappe.db.exists("Page", "a3-technician-workbench"))
		roles = set(
			frappe.get_all(
				"Has Role",
				filters={"parent": "a3-technician-workbench", "parenttype": "Page"},
				pluck="role",
			)
		)
		self.assertIn("Technician", roles)
		self.assertNotIn("Guest", roles)
