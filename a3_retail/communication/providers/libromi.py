# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Libromi / wa-api.cloud provider.

Libromi is a WhatsApp Business Solution Provider: Meta's Cloud API underneath,
with its own REST layer on top at `https://api.wa-api.cloud/v1`. Its send call
is flatter than Meta's — no `components` tree, just the values in named fields
— so this builds its own payload rather than reusing `template_payload()`.

Three things it gives us that Meta's own API does not:

- **`Idempotency-Key` is required on a send.** Keyed on the message log's own
  name, a retry of a message that already went out returns the first result
  instead of sending it twice. The retry logic in `dispatch` was written
  hoping for this; here it is guaranteed.
- **`header_media_url` takes a document.** That is how a customer's invoice PDF
  rides along with the message, which is the whole point of the integration.
- **Test keys (`ak_test_…`) read real data and change nothing.** The entire
  path can be proved against the real account before one real message goes out.

Templates are named here and numbered there, so the name on our
`WhatsApp Template` is resolved to Libromi's id once and cached.
"""

import frappe
import requests
from frappe.utils import cint

from a3_retail.communication.providers.base import BaseProvider

BASE_URL = "https://api.wa-api.cloud/v1"
API_VERSION = "2026-10-01"
TIMEOUT = 30
TEMPLATE_CACHE_SECONDS = 3600


class LibromiProvider(BaseProvider):
	# ------------------------------------------------------------------ send
	def send(self, log) -> dict:
		settings = self.settings()
		token = settings.get_password("access_token", raise_exception=False)
		if not token:
			return {"ok": False, "error": "No Libromi API token configured",
			        "error_code": "no_token"}

		template_id, problem = self._template_id(log, token, settings)
		if problem:
			return problem

		payload = self.payload_for(log, template_id, settings)
		if not payload.get("phone"):
			return {"ok": False, "error": "No number to send to", "error_code": "no_number"}

		try:
			response = requests.post(
				f"{self._base(settings)}/messages/template",
				json=payload,
				headers=self._headers(token, idempotency=log.name),
				timeout=TIMEOUT,
			)
		except requests.RequestException as exc:
			return {"ok": False, "error": str(exc), "error_code": "network"}

		return self._read(response)

	# --------------------------------------------------------------- payload
	def payload_for(self, log, template_id, settings=None) -> dict:
		"""What Libromi is asked to send. Separated so it can be read in a test
		without a network call."""
		settings = settings or self.settings()
		stored = frappe.parse_json(log.payload or "{}")
		params = stored.get("params") or {}

		payload = {
			"template_id": template_id,
			"phone": self._e164(log.to_number, settings),
			# One value per {{n}}, in order. Our params are keyed "1", "2", …
			"body_variables": [
				str(params[key])
				for key in sorted(params, key=lambda k: cint(k) if str(k).isdigit() else 0)
			],
		}

		channel = self._channel_id(log, settings)
		if channel:
			payload["channel_id"] = str(channel)

		# A new number becomes a contact on Libromi's side; name it rather than
		# leaving the shop with a contact list full of bare numbers.
		if log.customer:
			name = frappe.db.get_value("Customer", log.customer, "customer_name")
			if name:
				payload["name"] = name[:255]

		document = self.document_link(log)
		if document:
			payload["header_media_url"] = document

		suffixes = self.button_suffixes(log)
		if suffixes:
			payload["button_url_suffixes"] = suffixes

		return payload

	def document_link(self, log) -> str | None:
		"""The invoice PDF, as a link Meta can fetch.

		Only when the template says it carries one. `attach_print_format` on
		the WhatsApp Template is what turns an attachment on, and
		`shared_documents` decides what may be shared and for how long.
		"""
		if not (log.template and log.reference_doctype and log.reference_name):
			return None
		if not frappe.db.get_value("WhatsApp Template", log.template, "attach_print_format"):
			return None

		from a3_retail.api import shared_documents

		if log.reference_doctype not in shared_documents.SHAREABLE:
			return None
		try:
			return shared_documents.link_for(log.reference_doctype, log.reference_name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 Retail: shareable link")
			return None

	def button_suffixes(self, log) -> list[dict]:
		"""Values for dynamic URL buttons.

		The one we use is the Google review link, which differs per shop.
		Parassala and Udayankulangara have entirely different review links, so
		the template carries `https://share.google/{{1}}` and the branch
		supplies its own code — one template, every shop.
		"""
		stored = frappe.parse_json(log.payload or "{}")
		explicit = stored.get("button_url_suffixes")
		if explicit:
			return explicit

		if not log.branch:
			return []
		code = frappe.db.get_value("Branch Profile", {"branch": log.branch},
		                           "google_review_code")
		if not code:
			return []
		return [{"button_index": 0, "value": code}]

	# -------------------------------------------------------------- plumbing
	def _base(self, settings) -> str:
		configured = (settings.api_base_url or "").strip().rstrip("/")
		# The Meta default that ships in the doctype is not Libromi's.
		if not configured or "facebook.com" in configured:
			return BASE_URL
		return configured

	def _headers(self, token: str, idempotency: str | None = None) -> dict:
		headers = {
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
			"Api-Version": API_VERSION,
		}
		if idempotency:
			# 8–128 characters. A log name is unique and already means
			# "this one message", which is exactly the guarantee wanted.
			headers["Idempotency-Key"] = f"a3-{idempotency}"[:128]
		return headers

	def _channel_id(self, log, settings) -> str | None:
		"""Which WhatsApp number to send from. Libromi falls back to the
		account default when this is absent, so it stays optional."""
		if log.sender_profile:
			return frappe.db.get_value("WhatsApp Sender Profile", log.sender_profile,
			                           "phone_number_id")
		return None

	def _e164(self, number: str, settings) -> str:
		"""Libromi wants international format; the counter types ten digits."""
		digits = "".join(ch for ch in str(number or "") if ch.isdigit() or ch == "+")
		if digits.startswith("+"):
			return digits
		code = (settings.default_country_code or "91").lstrip("+")
		digits = digits.lstrip("0")
		if digits.startswith(code) and len(digits) > 10:
			return f"+{digits}"
		return f"+{code}{digits}"

	def _template_id(self, log, token, settings):
		"""Libromi's numeric id for the template we know by name."""
		if not log.template:
			return None, {"ok": False, "error": "No template on this message",
			              "error_code": "no_template"}

		name = frappe.db.get_value("WhatsApp Template", log.template, "meta_template_name")
		if not name:
			return None, {"ok": False, "error": f"{log.template} has no WhatsApp name",
			              "error_code": "no_template_name"}

		cache_key = f"a3_libromi_template:{name}"
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached, None

		try:
			response = requests.get(
				f"{self._base(settings)}/templates",
				params={"search": name, "status": "APPROVED", "limit": 100},
				headers=self._headers(token), timeout=TIMEOUT)
		except requests.RequestException as exc:
			return None, {"ok": False, "error": str(exc), "error_code": "network"}

		if response.status_code >= 400:
			return None, self._read(response)

		rows = (response.json() or {}).get("data") or []
		# `search` is "name contains", so an exact match is picked out rather
		# than trusting the first row — `invoice` would also match
		# `invoice_reminder`.
		match = next((r for r in rows if str(r.get("name")) == name), None)
		if not match:
			return None, {"ok": False,
			              "error": f"No approved WhatsApp template named {name}",
			              "error_code": "template_not_approved"}

		template_id = str(match.get("id"))
		frappe.cache().set_value(cache_key, template_id, expires_in_sec=TEMPLATE_CACHE_SECONDS)
		return template_id, None

	def _read(self, response) -> dict:
		if response.status_code >= 400:
			try:
				body = response.json() or {}
			except ValueError:
				body = {}
			error = body.get("error") or body
			message = (error.get("message") if isinstance(error, dict) else None) or response.text
			code = (error.get("code") if isinstance(error, dict) else None) or response.status_code
			return {"ok": False, "error": str(message)[:500], "error_code": str(code)}

		data = response.json() or {}
		inner = data.get("data") or data
		return {"ok": True, "message_id": str(inner.get("id") or inner.get("message_id") or "")}
