# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Meta WhatsApp Cloud API provider (scope 9.3)."""

import frappe
import requests

from a3_retail.communication.providers.base import BaseProvider

TIMEOUT = 20


class MetaCloudProvider(BaseProvider):
	def send(self, log) -> dict:
		settings = self.settings()
		phone_number_id = self._phone_number_id(log, settings)
		if not phone_number_id:
			return {"ok": False, "error": "No sender profile for this stream",
			        "error_code": "no_sender"}

		token = settings.get_password("access_token", raise_exception=False)
		if not token:
			return {"ok": False, "error": "No access token configured", "error_code": "no_token"}

		url = f"{settings.api_base_url.rstrip('/')}/{phone_number_id}/messages"
		try:
			response = requests.post(
				url,
				json=self.template_payload(log),
				headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
				timeout=TIMEOUT,
			)
		except requests.RequestException as exc:
			return {"ok": False, "error": str(exc), "error_code": "network"}

		if response.status_code >= 400:
			body = response.json() if response.content else {}
			error = (body.get("error") or {})
			return {"ok": False, "error": error.get("message", response.text),
			        "error_code": str(error.get("code", response.status_code))}

		data = response.json()
		messages = data.get("messages") or [{}]
		return {"ok": True, "message_id": messages[0].get("id")}

	def _phone_number_id(self, log, settings) -> str | None:
		if log.sender_profile:
			return frappe.db.get_value("WhatsApp Sender Profile", log.sender_profile, "phone_number_id")
		return None
