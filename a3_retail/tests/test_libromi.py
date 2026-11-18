# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Sending a customer their invoice on WhatsApp, through Libromi.

Two halves. The link — a customer's invoice has to be fetchable by Meta, from
the open internet, with no session — and the payload Libromi is handed.

Nothing here reaches the network. What is checked is what would be sent.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


def _an_invoice(branch: str | None = None) -> dict | None:
	filters = {"docstatus": 1}
	if branch:
		filters["branch"] = branch
	return frappe.db.get_value("Sales Invoice", filters, ["name", "customer", "branch"],
	                           as_dict=True)


class TestTheLinkMetaFetches(FrappeTestCase):
	def test_only_a_listed_document_can_be_shared(self):
		"""A share key is a key to a document. Without a list, one could be
		minted for a Salary Slip just as easily as for an invoice."""
		from a3_retail.api import shared_documents

		self.assertEqual(set(shared_documents.SHAREABLE),
		                 {"Sales Invoice", "Service Job Card"})
		with self.assertRaises(frappe.ValidationError):
			shared_documents.link_for("Salary Slip", "anything")

	def test_the_print_format_is_fixed_per_document(self):
		"""The caller picks the document, never the format — or an invoice link
		becomes a way of printing something else about that invoice."""
		from a3_retail.api import shared_documents

		invoice = _an_invoice()
		if not invoice:
			self.skipTest("no submitted invoice on this site")
		link = shared_documents.link_for("Sales Invoice", invoice.name)
		self.assertIn("format=Retail%20Tax%20Invoice", link)

	def test_the_link_carries_a_key_and_an_expiry(self):
		from a3_retail.api import shared_documents

		invoice = _an_invoice()
		if not invoice:
			self.skipTest("no submitted invoice on this site")
		link = shared_documents.link_for("Sales Invoice", invoice.name, ttl_days=7)
		self.assertIn("key=", link)

		key = link.split("key=")[1].split("&")[0]
		expires = frappe.db.get_value("Document Share Key",
		                              {"reference_doctype": "Sales Invoice",
		                               "reference_docname": invoice.name, "key": key},
		                              "expires_on")
		self.assertTrue(expires, "the key must exist and expire")

	def test_a_missing_document_is_refused_before_a_key_is_made(self):
		from a3_retail.api import shared_documents

		with self.assertRaises(frappe.ValidationError):
			shared_documents.link_for("Sales Invoice", "SINV-NOPE-9999")

	def test_it_is_frappe_s_own_endpoint_rather_than_one_of_ours(self):
		"""An earlier draft signed its own links and served its own PDF. Frappe
		already does both, and a guest endpoint of ours is one more thing to
		keep right."""
		body = _source("api", "shared_documents.py")
		self.assertIn("frappe.utils.print_format.download_pdf", body)
		self.assertIn("get_document_share_key", body)
		self.assertNotIn("allow_guest", body)
		self.assertNotIn("hmac", body)

	def test_the_link_is_built_on_the_site_s_public_address(self):
		"""Meta fetches it, not the counter. A localhost URL is fetched by
		nobody."""
		self.assertIn("get_url()", _source("api", "shared_documents.py"))


class TestWhatLibromiIsHanded(FrappeTestCase):
	def setUp(self):
		from a3_retail.communication.providers.libromi import LibromiProvider

		self.provider = LibromiProvider()
		self.invoice = _an_invoice()
		if not self.invoice:
			self.skipTest("no submitted invoice on this site")

		self.template = self._a_template(attaches=True)

	def _a_template(self, attaches: bool):
		name = frappe.db.get_value("WhatsApp Template", {"template_key": "sale_invoice"},
		                           "name")
		if not name:
			doc = frappe.new_doc("WhatsApp Template")
			doc.template_key = "sale_invoice"
			doc.meta_template_name = "invoice_with_review"
			doc.stream = "Sales"
			doc.language = "en"
			doc.body_text = "Hi {{1}}, invoice {{2}} for {{3}}."
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			name = doc.name
		frappe.db.set_value("WhatsApp Template", name, "attach_print_format",
		                    "Retail Tax Invoice" if attaches else None,
		                    update_modified=False)
		return name

	def _log(self, **over):
		base = {
			"name": "WAML-TEST-0001", "to_number": "9847012345",
			"template": self.template, "customer": self.invoice.customer,
			"branch": self.invoice.branch, "reference_doctype": "Sales Invoice",
			"reference_name": self.invoice.name, "sender_profile": None,
			"payload": json.dumps({"params": {"1": "Rahul", "2": self.invoice.name,
			                                  "3": "1,498.00"}}),
		}
		base.update(over)
		return frappe._dict(base)

	def test_the_variables_go_in_the_order_the_template_numbers_them(self):
		"""`{{10}}` must not sort between `{{1}}` and `{{2}}`."""
		log = self._log(payload=json.dumps({"params": {
			"2": "second", "10": "tenth", "1": "first"}}))
		body = self.provider.payload_for(log, template_id="1")
		self.assertEqual(body["body_variables"], ["first", "second", "tenth"])

	def test_the_number_is_sent_in_international_form(self):
		settings = self.provider.settings()
		for typed in ("9847012345", "09847012345", "+91 98470 12345",
		              "919847012345", "98470-12345"):
			self.assertEqual(self.provider._e164(typed, settings), "+919847012345",
			                 f"{typed!r} was not normalised")

	def test_the_invoice_pdf_rides_along(self):
		body = self.provider.payload_for(self._log(), template_id="1")
		self.assertIn("header_media_url", body)
		self.assertIn("download_pdf", body["header_media_url"])
		self.assertIn("key=", body["header_media_url"])

	def test_no_attachment_unless_the_template_asks_for_one(self):
		"""`attach_print_format` is the switch. A template without it must not
		quietly start carrying a customer's invoice."""
		self._a_template(attaches=False)
		body = self.provider.payload_for(self._log(), template_id="1")
		self.assertNotIn("header_media_url", body)

	def test_no_attachment_without_a_document_to_attach(self):
		body = self.provider.payload_for(
			self._log(reference_doctype=None, reference_name=None), template_id="1")
		self.assertNotIn("header_media_url", body)

	def test_the_review_button_points_at_this_shop(self):
		"""Parassala and Udayankulangara are separate Google listings. One
		template, and the branch supplies its own code."""
		codes = {}
		for site in ("PSLA", "UK"):
			branch = frappe.db.get_value("Branch Profile",
			                             {"site": site, "is_active": 1}, "branch")
			if not branch:
				continue
			body = self.provider.payload_for(self._log(branch=branch), template_id="1")
			suffixes = body.get("button_url_suffixes") or []
			self.assertTrue(suffixes, f"{branch} has no review link")
			codes[site] = suffixes[0]["value"]

		if len(codes) == 2:
			self.assertNotEqual(codes["PSLA"], codes["UK"],
			                    "both shops are pointing at the same review page")

	def test_a_branch_with_no_review_link_simply_has_no_button(self):
		"""The distribution desk is not a shop a customer reviews."""
		body = self.provider.payload_for(self._log(branch=None), template_id="1")
		self.assertEqual(body.get("button_url_suffixes", []), [])

	def test_the_customer_is_named_rather_than_left_a_bare_number(self):
		body = self.provider.payload_for(self._log(), template_id="1")
		self.assertTrue(body.get("name"))

	def test_a_retry_cannot_send_twice(self):
		"""Libromi requires an Idempotency-Key, and the log's own name is
		exactly "this one message"."""
		headers = self.provider._headers("token", idempotency="WAML-0001")
		self.assertEqual(headers["Idempotency-Key"], "a3-WAML-0001")
		self.assertLessEqual(len(headers["Idempotency-Key"]), 128)
		self.assertGreaterEqual(len(headers["Idempotency-Key"]), 8)

	def test_it_talks_to_libromi_and_not_to_meta(self):
		settings = self.provider.settings()
		# The doctype ships Meta's base URL as its default; Libromi's is not that.
		self.assertEqual(self.provider._base(settings), "https://api.wa-api.cloud/v1")
		self.assertIn("Bearer", self.provider._headers("tok")["Authorization"])


class TestItIsWiredIn(FrappeTestCase):
	def test_the_provider_can_be_chosen(self):
		options = frappe.get_meta("WhatsApp Settings").get_field("provider").options
		self.assertIn("Libromi", options.split("\n"))

	def test_choosing_it_returns_it(self):
		from a3_retail.communication.providers import get_provider
		from a3_retail.communication.providers.libromi import LibromiProvider

		was = frappe.db.get_single_value("WhatsApp Settings", "provider")
		self.addCleanup(frappe.db.set_single_value, "WhatsApp Settings", "provider", was)
		frappe.db.set_single_value("WhatsApp Settings", "provider", "Libromi")
		frappe.clear_cache(doctype="WhatsApp Settings")
		self.assertIsInstance(get_provider(), LibromiProvider)

	def test_every_branch_that_is_a_shop_has_a_review_link(self):
		missing = [row.branch for row in frappe.get_all(
			"Branch Profile", filters={"is_active": 1},
			fields=["branch", "site", "google_review_code"])
			if (row.site or "").upper() in ("PSLA", "UK")
			and not (row.google_review_code or "").strip()]
		self.assertEqual(missing, [], f"no review link for {missing}")

	def test_the_patch_runs_on_a_live_site(self):
		self.assertIn("a3_retail.patches.google_review_links_per_shop",
		              _source("patches.txt"))


class TestTheMessagesThemselves(FrappeTestCase):
	def test_all_seven_are_defined(self):
		from a3_retail.api.service_pos import TEMPLATE_BY_STATUS
		from a3_retail.setup.whatsapp_templates import TEMPLATES

		defined = {spec["key"] for spec in TEMPLATES}
		# Every status the service desk can message from must have a message.
		missing = set(TEMPLATE_BY_STATUS.values()) - defined
		self.assertEqual(missing, set(), f"no template for {missing}")
		self.assertIn("sale_invoice", defined)

	def test_every_one_of_them_is_transactional(self):
		"""Marketing templates are gated by opt-in, quiet hours and a daily cap.
		A customer who opted out of offers is still owed their invoice."""
		from a3_retail.setup.whatsapp_templates import TEMPLATES

		for spec in TEMPLATES:
			row = frappe.db.get_value("WhatsApp Template",
			                          {"template_key": spec["key"]}, "category")
			if row:
				self.assertEqual(row, "Utility", f"{spec['key']} is not Utility")

	def test_the_review_ask_is_a_button_and_never_a_sentence(self):
		"""A body that asks for a review reads as marketing to Meta, and would
		drag the whole template — invoice and all — into the gated category."""
		import re

		from a3_retail.setup.whatsapp_templates import TEMPLATES

		# Whole words: "star" is inside "started", and matching substrings
		# failed a perfectly good message about work having started.
		asking = re.compile(r"\b(reviews?|rate us|ratings?|feedback|stars?)\b")
		for spec in TEMPLATES:
			found = asking.search(spec["body"].lower())
			self.assertIsNone(found,
			                  f"{spec['key']} asks for a review in its body "
			                  f"({found.group(0) if found else ''})")

	def test_the_review_button_is_on_the_two_the_shop_asked_for(self):
		from a3_retail.setup.whatsapp_templates import TEMPLATES

		with_button = {spec["key"] for spec in TEMPLATES if spec.get("buttons")}
		self.assertEqual(with_button, {"sale_invoice", "device_delivered"})

	def test_only_the_invoice_carries_a_document(self):
		from a3_retail.setup.whatsapp_templates import TEMPLATES

		attaching = {spec["key"] for spec in TEMPLATES if spec.get("attach_print_format")}
		self.assertEqual(attaching, {"sale_invoice"})

	def test_every_variable_in_a_body_has_a_parameter_behind_it(self):
		"""A `{{4}}` with no parameter row arrives blank on a customer's phone."""
		import re

		from a3_retail.setup.whatsapp_templates import TEMPLATES

		for spec in TEMPLATES:
			used = {int(n) for n in re.findall(r"\{\{(\d+)\}\}", spec["body"])}
			supplied = set(range(1, len(spec["params"]) + 1))
			self.assertEqual(used, supplied,
			                 f"{spec['key']}: body uses {sorted(used)}, "
			                 f"parameters supply {sorted(supplied)}")

	def test_a_body_fits_what_whatsapp_accepts(self):
		from a3_retail.setup.whatsapp_templates import TEMPLATES

		for spec in TEMPLATES:
			self.assertLessEqual(len(spec["body"]), 1024, f"{spec['key']} is too long")

	def test_seeding_twice_changes_nothing_the_second_time(self):
		from a3_retail.setup.whatsapp_templates import ensure_templates

		first = ensure_templates()
		second = ensure_templates()
		self.assertEqual(second["created"], [],
		                 "a second run created templates all over again")
		self.assertTrue(set(second["updated"]) >= set(first["created"] + first["updated"]))


class TestTheVariablesGetFilled(FrappeTestCase):
	def test_the_direct_path_resolves_them_too(self):
		"""`notify()` is what the Bills screen and the service desk call. It
		passed no parameters, so a bill arrived with every variable blank while
		the rules path filled them correctly."""
		body = _source("communication", "engine.py")
		block = body[body.index("def send_template("):]
		block = block[:block.index("\ndef ", 10)]
		self.assertIn("resolve_parameters(template, reference_doc)", block)

	def test_a_caller_that_supplies_its_own_still_wins(self):
		body = _source("communication", "engine.py")
		self.assertIn("if template and not params and reference_doc is not None:", body)

	def test_an_invoice_fills_name_number_and_amount(self):
		from a3_retail.communication.engine import resolve_parameters

		invoice = _an_invoice()
		name = frappe.db.get_value("WhatsApp Template", {"template_key": "sale_invoice"},
		                           "name")
		if not (invoice and name):
			self.skipTest("no invoice or no sale_invoice template on this site")

		params = resolve_parameters(frappe.get_cached_doc("WhatsApp Template", name),
		                            frappe.get_doc("Sales Invoice", invoice.name))
		self.assertEqual(params["2"], invoice.name)
		self.assertTrue(params["1"], "the customer is not named")
		self.assertTrue(params["3"], "the amount is blank")

	def test_a_gated_document_is_said_out_loud(self):
		"""If Meta recategorises the invoice template, a customer who opted out
		of offers silently stops receiving their bill. That must be visible."""
		body = _source("communication", "engine.py")
		block = body[body.index("def compliance_block("):]
		block = block[:block.index("\ndef ", 10)]
		self.assertIn('template.get("attach_print_format")', block)
		self.assertIn("frappe.log_error", block)
