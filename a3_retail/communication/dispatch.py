# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Provider-facing send path. Fully implemented in step 22."""

import frappe


def send_template(template_key: str, to_number: str | None, params: dict, stream: str = "Service",
                  reference_doc=None) -> bool:
	"""Queue a templated WhatsApp message.

	Until the provider layer lands (step 22) this records the intent so nothing
	is silently lost and the trigger matrix can be verified.
	"""
	if not frappe.db.exists("DocType", "WhatsApp Message Log"):
		return False

	log = frappe.new_doc("WhatsApp Message Log")
	log.to_number = to_number
	log.stream = stream
	log.status = "Queued"
	log.message_body = frappe.as_json({"template": template_key, "params": params})
	if reference_doc is not None:
		log.reference_doctype = reference_doc.doctype
		log.reference_name = reference_doc.name
	log.flags.ignore_permissions = True
	log.insert(ignore_permissions=True)
	return True
