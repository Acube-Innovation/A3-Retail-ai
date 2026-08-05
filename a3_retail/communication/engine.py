# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Communication dispatch facade.

The full rule engine, provider abstraction and templates arrive in step 22. This
module is the seam other steps call so they never import provider code directly,
and so an unconfigured messaging stack can never break a business transaction.
"""

import frappe


def is_enabled() -> bool:
	return bool(frappe.db.get_single_value("A3 Retail Settings", "enable_whatsapp"))


def send_otp(mobile_no: str, otp: str, purpose: str = "General") -> bool:
	"""Deliver a one-time password. No-op until WhatsApp is configured."""
	if not is_enabled():
		return False

	from a3_retail.communication.dispatch import send_template

	return send_template(
		template_key="portal_otp",
		to_number=mobile_no,
		params={"1": otp, "2": purpose},
		stream="Service",
	)


def notify(template_key: str, doc=None, to_number: str | None = None, params: dict | None = None,
           stream: str = "Service") -> bool:
	"""Fire a template at a customer. Safe to call before step 22 is built."""
	if not is_enabled():
		return False

	from a3_retail.communication.dispatch import send_template

	return send_template(template_key=template_key, to_number=to_number, params=params or {},
	                     stream=stream, reference_doc=doc)
