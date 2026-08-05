# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Base provider interface."""

import frappe


class BaseProvider:
	"""Every provider takes a WhatsApp Message Log and reports what happened."""

	def send(self, log) -> dict:
		raise NotImplementedError

	def settings(self):
		return frappe.get_cached_doc("WhatsApp Settings")

	def template_payload(self, log) -> dict:
		"""Meta's template message shape, which most vendors mirror."""
		payload = frappe.parse_json(log.payload or "{}")
		params = payload.get("params") or {}
		template = frappe.get_cached_doc("WhatsApp Template", log.template) if log.template else None

		components = []
		body_params = [
			{"type": "text", "text": str(params[key])}
			for key in sorted(params, key=lambda k: int(k) if str(k).isdigit() else 0)
		]
		if body_params:
			components.append({"type": "body", "parameters": body_params})

		return {
			"messaging_product": "whatsapp",
			"to": log.to_number,
			"type": "template",
			"template": {
				"name": template.meta_template_name if template else payload.get("template"),
				"language": {"code": (template.language if template else "en")},
				"components": components,
			},
		}


class NullProvider(BaseProvider):
	"""Used when no provider is configured — records intent, sends nothing."""

	def send(self, log) -> dict:
		return {"ok": False, "error": "No WhatsApp provider configured", "error_code": "no_provider"}
