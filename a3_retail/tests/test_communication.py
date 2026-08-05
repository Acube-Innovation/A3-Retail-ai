# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Communication engine: rules, compliance and delivery (scope step 22, doc 09)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from a3_retail.communication.dispatch import normalize_number, render_body, resolve_sender
from a3_retail.communication.engine import (
	compliance_block,
	format_param,
	in_quiet_hours,
	marketing_sent_today,
	send_template,
)
from a3_retail.tests.fixtures import ensure_branch, ensure_customer


def _settings(**overrides):
	settings = frappe.get_single("WhatsApp Settings")
	settings.update(overrides)
	return settings


class TestMasters(FrappeTestCase):
	def test_eight_sender_profiles_seeded(self):
		self.assertGreaterEqual(frappe.db.count("WhatsApp Sender Profile"), 8)

	def test_templates_seeded(self):
		self.assertGreaterEqual(frappe.db.count("WhatsApp Template"), 26)

	def test_rules_seeded_but_inactive(self):
		"""Scope 9.6: rules ship inactive so a demo never messages anyone."""
		total = frappe.db.count("Communication Rule")
		active = frappe.db.count("Communication Rule", {"is_active": 1})
		self.assertGreaterEqual(total, 28)
		self.assertEqual(active, 0)

	def test_every_stream_has_a_sender(self):
		for stream in ("Sales", "Service", "EMI / Finance", "Warranty", "Helpdesk", "Marketing"):
			self.assertTrue(
				frappe.db.exists("WhatsApp Sender Profile", {"stream": stream, "is_active": 1}),
				stream,
			)

	def test_marketing_templates_are_categorised(self):
		for key in ("ew_upsell_offer", "seasonal_offer_blast", "birthday_greeting"):
			self.assertEqual(
				frappe.db.get_value("WhatsApp Template", key, "category"), "Marketing", key
			)

	def test_transactional_templates_are_utility(self):
		for key in ("job_card_created", "repair_ready", "sale_invoice"):
			self.assertEqual(
				frappe.db.get_value("WhatsApp Template", key, "category"), "Utility", key
			)


class TestFormatting(FrappeTestCase):
	def test_currency_formatting(self):
		self.assertIn("10,738", format_param(10738, "Currency"))

	def test_date_formatting(self):
		self.assertTrue(format_param("2026-08-05", "Date"))

	def test_blank_stays_blank(self):
		self.assertEqual(format_param(None, "Text"), "")

	def test_body_placeholders_are_substituted(self):
		template = frappe.get_cached_doc("WhatsApp Template", "repair_ready")
		body = render_body(template, {"1": "Rahul", "2": "Galaxy A55", "3": "826", "4": "123456",
		                              "5": "Kochi"})
		self.assertIn("Rahul", body)
		self.assertIn("123456", body)
		self.assertNotIn("{{1}}", body)

	def test_number_normalisation_adds_the_country_code(self):
		self.assertEqual(normalize_number("9847012345"), "919847012345")
		self.assertEqual(normalize_number("+91 98470 12345"), "919847012345")


class TestSenderResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_stream_default_is_used(self):
		self.assertEqual(resolve_sender("Service"), "MW Service")

	def test_branch_specific_profile_wins(self):
		name = "MW Service Kochi"
		if not frappe.db.exists("WhatsApp Sender Profile", name):
			doc = frappe.new_doc("WhatsApp Sender Profile")
			doc.profile_name = name
			doc.stream = "Service"
			doc.branch = "Kochi"
			doc.phone_number_id = "TEST-KCH"
			doc.is_active = 1
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)

		self.assertEqual(resolve_sender("Service", "Kochi"), name)
		frappe.delete_doc("WhatsApp Sender Profile", name, force=1, ignore_permissions=True)

	def test_unknown_stream_resolves_to_nothing(self):
		self.assertIsNone(resolve_sender("Nonexistent Stream"))


class TestCompliance(FrappeTestCase):
	"""Scope 9.5: Marketing is gated, Utility is always allowed."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_utility_is_never_blocked(self):
		template = frappe.get_cached_doc("WhatsApp Template", "job_card_created")
		customer = ensure_customer()
		frappe.db.set_value("Customer", customer, "a3_marketing_optin", 0)

		self.assertIsNone(compliance_block(template, customer))
		frappe.db.set_value("Customer", customer, "a3_marketing_optin", 1)

	def test_marketing_needs_opt_in(self):
		template = frappe.get_cached_doc("WhatsApp Template", "seasonal_offer_blast")
		customer = ensure_customer("9846088001", "Optout Customer")
		frappe.db.set_value("Customer", customer, "a3_marketing_optin", 0)

		settings = _settings(respect_marketing_optin=1, quiet_hours_from=None, quiet_hours_to=None)
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)

		self.assertEqual(compliance_block(template, customer), "Blocked (Opt-out)")

	def test_quiet_hours_hold_marketing(self):
		template = frappe.get_cached_doc("WhatsApp Template", "seasonal_offer_blast")
		customer = ensure_customer()
		frappe.db.set_value("Customer", customer, "a3_marketing_optin", 1)

		# A window that certainly contains "now".
		settings = _settings(quiet_hours_from="00:00:00", quiet_hours_to="23:59:00",
		                     respect_marketing_optin=1)
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)

		self.assertEqual(compliance_block(template, customer), "Held (Quiet Hours)")

		settings = _settings(quiet_hours_from=None, quiet_hours_to=None)
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)

	def test_quiet_hours_wrap_past_midnight(self):
		settings = frappe._dict(quiet_hours_from="21:00:00", quiet_hours_to="08:00:00")
		hour = now_datetime().hour
		expected = hour >= 21 or hour < 8
		self.assertEqual(in_quiet_hours(settings), expected)

	def test_no_quiet_hours_configured_never_holds(self):
		self.assertFalse(in_quiet_hours(frappe._dict(quiet_hours_from=None, quiet_hours_to=None)))

	def test_marketing_counter_starts_at_zero(self):
		customer = ensure_customer("9846088002", "Fresh Customer")
		self.assertEqual(marketing_sent_today(customer), 0)


class TestSendPath(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		settings = _settings(quiet_hours_from=None, quiet_hours_to=None, enabled=0)
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	def test_a_send_always_writes_a_log(self):
		"""Intent is recorded even when no provider is configured."""
		before = frappe.db.count("WhatsApp Message Log")
		send_template("job_card_created", "9847012345", {"1": "Rahul"}, stream="Service")
		self.assertEqual(frappe.db.count("WhatsApp Message Log"), before + 1)

	def test_the_log_carries_the_rendered_body(self):
		send_template("repair_ready", "9847012345",
		              {"1": "Rahul", "2": "Galaxy A55", "3": "826", "4": "999111", "5": "Kochi"},
		              stream="Service")
		log = frappe.get_last_doc("WhatsApp Message Log")
		self.assertIn("999111", log.message_body)
		self.assertEqual(log.status, "Queued")

	def test_the_log_picks_the_stream_sender(self):
		send_template("sale_invoice", "9847012345", {"1": "Rahul"}, stream="Sales")
		log = frappe.get_last_doc("WhatsApp Message Log")
		self.assertEqual(log.sender_profile, "MW Sales")

	def test_a_blocked_marketing_message_is_logged_not_sent(self):
		customer = ensure_customer("9846088003", "Blocked Customer")
		frappe.db.set_value("Customer", customer, "a3_marketing_optin", 0)

		sent = send_template("seasonal_offer_blast", "9846088003", {"1": "Onam"}, stream="Marketing")
		self.assertFalse(sent)

		log = frappe.get_last_doc("WhatsApp Message Log")
		self.assertEqual(log.status, "Blocked (Opt-out)")

	def test_no_recipient_sends_nothing(self):
		self.assertFalse(send_template("job_card_created", None, {}))

	def test_number_is_stored_normalised(self):
		send_template("job_card_created", "9847012345", {"1": "Rahul"}, stream="Service")
		log = frappe.get_last_doc("WhatsApp Message Log")
		self.assertEqual(log.to_number, "919847012345")


class TestProviders(FrappeTestCase):
	def test_null_provider_reports_no_configuration(self):
		from a3_retail.communication.providers.base import NullProvider

		result = NullProvider().send(frappe._dict(to_number="919847012345"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error_code"], "no_provider")

	def test_registry_returns_meta_by_default(self):
		from a3_retail.communication.providers import get_provider
		from a3_retail.communication.providers.meta_cloud import MetaCloudProvider

		self.assertIsInstance(get_provider(), MetaCloudProvider)

	def test_template_payload_shape(self):
		from a3_retail.communication.providers.base import BaseProvider

		log = frappe._dict(
			to_number="919847012345",
			template="job_card_created",
			payload=frappe.as_json({"template": "job_card_created", "params": {"1": "Rahul", "2": "A55"}}),
		)
		payload = BaseProvider().template_payload(log)

		self.assertEqual(payload["messaging_product"], "whatsapp")
		self.assertEqual(payload["to"], "919847012345")
		self.assertEqual(payload["template"]["name"], "job_card_created")
		self.assertEqual(len(payload["template"]["components"][0]["parameters"]), 2)


class TestValidationQueries(FrappeTestCase):
	"""Scope 9.10."""

	def test_no_marketing_to_non_opted_in_customers(self):
		rows = frappe.db.sql(
			"""
			select l.name from `tabWhatsApp Message Log` l
			join `tabWhatsApp Template` t on t.name = l.template
			join `tabCustomer` c on c.name = l.customer
			where t.category = 'Marketing' and c.a3_marketing_optin = 0
			  and l.status not in ('Blocked (Opt-out)', 'Held (Quiet Hours)', 'Failed')
			"""
		)
		self.assertFalse(rows, f"marketing sent without opt-in: {rows}")

	def test_delivery_summary_runs(self):
		from a3_retail.api.whatsapp import delivery_summary

		self.assertIsInstance(delivery_summary(30), list)


class TestWebhook(FrappeTestCase):
	def test_invalid_token_is_refused(self):
		from a3_retail.api.whatsapp import _token_is_valid

		self.assertFalse(_token_is_valid(None))
		self.assertFalse(_token_is_valid("nonsense"))

	def test_status_update_moves_the_log(self):
		from a3_retail.api.whatsapp import _update_status

		send_template("job_card_created", "9847012345", {"1": "Rahul"}, stream="Service")
		log = frappe.get_last_doc("WhatsApp Message Log")
		log.db_set("provider_message_id", "wamid.TEST123", update_modified=False)

		_update_status({"id": "wamid.TEST123", "status": "delivered"})
		log.reload()
		self.assertEqual(log.status, "Delivered")
		self.assertTrue(log.delivered_on)

	def test_unknown_message_id_is_ignored(self):
		from a3_retail.api.whatsapp import _update_status

		_update_status({"id": "wamid.NOTHING", "status": "read"})  # must not raise
