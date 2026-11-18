# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Libromi provider — `wa-api.cloud/api/v1`.

Libromi is a WhatsApp Business Solution Provider: Meta's Cloud API underneath,
and the send call is Meta's own shape — the same `components` tree — wrapped
with the Libromi channel the message goes out from:

    POST https://wa-api.cloud/api/v1/messages
    Authorization: Bearer <token>
    {"channel_id": "409", "to": "+91…", "type": "template",
     "template": {"name": …, "language": {"code": "en",
                                          "policy": "deterministic"},
                  "components": [ … ]}}

So the components are built the way `BaseProvider.template_payload()` builds
them and this adds what Meta's own endpoint does not take: the channel, and the
header and button parameters an invoice needs.

A note on which Libromi API this is. There are two, and they are not the same
thing. `api.wa-api.cloud/v1` is the newer "API Platform" — numbered template
ids, required idempotency keys, an OpenAPI spec — and reaching it needs a key
that can only be minted through the Copilot, which is a paid feature. This one
is the panel's own API, it takes the token from Settings → API Tokens, and it
names templates rather than numbering them. It is the one this account can
actually use.

Templates are referred to **by name**, so there is no id to look up and no
cache to go stale. The name is `WhatsApp Template.meta_template_name`.
"""

import frappe
from frappe.utils import cint

from a3_retail.communication.providers.base import BaseProvider

BASE_URL = "https://wa-api.cloud/api/v1"
TIMEOUT = 30


class LibromiProvider(BaseProvider):
	# ------------------------------------------------------------------ send
	def send(self, log) -> dict:
		import requests

		settings = self.settings()
		token = settings.get_password("access_token", raise_exception=False)
		if not token:
			return {"ok": False, "error": "No Libromi token configured",
			        "error_code": "no_token"}

		payload = self.payload_for(log, settings)
		if not payload.get("to"):
			return {"ok": False, "error": "No number to send to", "error_code": "no_number"}
		if not payload["template"].get("name"):
			return {"ok": False, "error": f"{log.template} has no WhatsApp name",
			        "error_code": "no_template_name"}

		try:
			response = requests.post(
				f"{self._base(settings)}/messages",
				json=payload,
				headers={"Authorization": f"Bearer {token}",
				         "Content-Type": "application/json",
				         "Accept": "application/json"},
				timeout=TIMEOUT,
			)
		except requests.RequestException as exc:
			return {"ok": False, "error": str(exc), "error_code": "network"}

		return self._read(response)

	# --------------------------------------------------------------- payload
	def payload_for(self, log, settings=None) -> dict:
		"""What Libromi is asked to send. Built without a network call so a
		test can read it."""
		settings = settings or self.settings()
		template = (frappe.get_cached_doc("WhatsApp Template", log.template)
		            if log.template else None)

		body = {
			"to": self._e164(log.to_number, settings),
			"type": "template",
			"template": {
				"name": (template.meta_template_name if template else None),
				"language": {
					"code": (template.language if template else "en") or "en",
					# Libromi's own note: the policy must be this word.
					"policy": "deterministic",
				},
				"components": self.components(log, template),
			},
		}

		channel = self._channel_id(log, settings)
		if channel:
			body["channel_id"] = str(channel)
		return body

	def components(self, log, template) -> list[dict]:
		"""Meta's component tree: the header's document, the body's values,
		and a suffix for each dynamic URL button."""
		components = []

		document = self.document_link(log, template)
		if document:
			components.append({
				"type": "header",
				"parameters": [{
					"type": "document",
					"document": {
						"link": document,
						# Named, or WhatsApp shows the customer a filename
						# taken from the URL.
						"filename": f"{log.reference_name}.pdf",
					},
				}],
			})

		values = self.body_values(log)
		if values:
			components.append({
				"type": "body",
				"parameters": [{"type": "text", "text": value} for value in values],
			})

		for index, suffix in self.button_suffixes(log):
			components.append({
				"type": "button",
				"sub_type": "url",
				"index": str(index),
				"parameters": [{"type": "text", "text": suffix}],
			})

		return components

	def body_values(self, log) -> list[str]:
		"""One value per `{{n}}`, in the order the template numbers them."""
		stored = frappe.parse_json(log.payload or "{}")
		params = stored.get("params") or {}
		return [str(params[key])
		        for key in sorted(params,
		                          key=lambda k: cint(k) if str(k).isdigit() else 0)]

	def document_link(self, log, template) -> str | None:
		"""The invoice PDF, as a link WhatsApp can fetch.

		Libromi's own note prefers a media id uploaded beforehand and allows a
		public link. A link is what suits a bill: it is made when the message
		goes, it expires, and there is nothing to upload or clean up.
		"""
		if not (template and log.reference_doctype and log.reference_name):
			return None
		if not template.get("attach_print_format"):
			return None

		from a3_retail.api import shared_documents

		if log.reference_doctype not in shared_documents.SHAREABLE:
			return None
		try:
			return shared_documents.link_for(log.reference_doctype, log.reference_name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 Retail: shareable link")
			return None

	def button_suffixes(self, log) -> list[tuple[int, str]]:
		"""Values for dynamic URL buttons, as (index, suffix).

		The one in use is the Google review link, which differs per shop.
		Parassala and Udayankulangara are separate Google listings, so the
		template carries `https://share.google/{{1}}` and the branch supplies
		its own code — one template, every counter.
		"""
		stored = frappe.parse_json(log.payload or "{}")
		explicit = stored.get("button_url_suffixes")
		if explicit:
			return [(cint(row.get("button_index")), str(row.get("value")))
			        for row in explicit]

		if not log.branch:
			return []
		code = frappe.db.get_value("Branch Profile", {"branch": log.branch},
		                           "google_review_code")
		return [(0, code)] if code else []

	# -------------------------------------------------------------- plumbing
	def _base(self, settings) -> str:
		configured = (settings.api_base_url or "").strip().rstrip("/")
		# The doctype ships Meta's own base URL as its default, and the newer
		# Libromi API Platform is a different host again. Neither is this.
		if not configured or "facebook.com" in configured or "api.wa-api.cloud" in configured:
			return BASE_URL
		return configured

	def _channel_id(self, log, settings) -> str | None:
		"""Which WhatsApp number to send from."""
		if log.sender_profile:
			return frappe.db.get_value("WhatsApp Sender Profile", log.sender_profile,
			                           "phone_number_id")
		return settings.get("business_account_id") or None

	def _e164(self, number: str, settings) -> str:
		"""International format; the counter types ten digits."""
		digits = "".join(ch for ch in str(number or "") if ch.isdigit() or ch == "+")
		if digits.startswith("+"):
			return digits
		code = (settings.default_country_code or "91").lstrip("+")
		digits = digits.lstrip("0")
		if digits.startswith(code) and len(digits) > 10:
			return f"+{digits}"
		return f"+{code}{digits}"

	def _read(self, response) -> dict:
		if response.status_code >= 400:
			try:
				body = response.json() or {}
			except ValueError:
				body = {}
			return {"ok": False,
			        "error": str(body.get("message") or response.text)[:500],
			        "error_code": str(body.get("error_code") or response.status_code)}

		try:
			data = response.json() or {}
		except ValueError:
			return {"ok": True, "message_id": None}

		inner = data.get("data") or data
		if isinstance(inner, dict):
			messages = inner.get("messages") or []
			if messages and isinstance(messages[0], dict):
				return {"ok": True, "message_id": messages[0].get("id")}
			return {"ok": True,
			        "message_id": inner.get("id") or inner.get("message_id")}
		return {"ok": True, "message_id": None}
