# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The messages PhoneXpert sends its customers, as WhatsApp templates.

Every one of these is **Utility**: it is sent because the customer did
something — bought a phone, left a device for repair, collected it — and never
because the shop has an offer on. That matters beyond tidiness. Marketing
templates are gated by opt-in, by quiet hours and by a daily cap
(`engine.compliance_block`), so a customer who opted out of offers would never
receive their own invoice if these were categorised Marketing. Meta decides the
category from the wording, so the wording stays transactional.

That is also why the review request is a **button** rather than a sentence. A
body that asks for a review reads as marketing; a button under a transactional
message does not, and it can be ignored. The button's URL is dynamic —
`https://share.google/{{1}}` — so one approved template serves both shops and
`Branch Profile.google_review_code` supplies the rest.

The status a job card is in decides which of these goes out; that mapping is
`service_pos.TEMPLATE_BY_STATUS` and these are the other half of it.
"""

import frappe

REVIEW_BUTTON = {"button_type": "URL", "text": "Rate us on Google", "url_suffix": ""}

# key, Meta name, what it is for, body, parameters, buttons, attachment
TEMPLATES = [
	{
		"key": "sale_invoice",
		"meta_name": "invoice_with_review",
		"stream": "Sales",
		"reference_doctype": "Sales Invoice",
		"header_type": "Document",
		"attach_print_format": "Retail Tax Invoice",
		"body": ("Hi {{1}}, thank you for shopping at PhoneXpert.\n\n"
		         "Your invoice {{2}} for {{3}} is attached."),
		"params": [("customer_name", None, "Text"),
		           ("name", None, "Text"),
		           ("grand_total", None, "Currency")],
		"buttons": [REVIEW_BUTTON],
	},
	{
		"key": "job_card_created",
		"meta_name": "service_booked_in",
		"body": ("Hi {{1}}, we have your {{2}} at PhoneXpert.\n\n"
		         "Job card {{3}}. We will message you as the repair moves along."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("name", None, "Text")],
	},
	{
		"key": "estimate_sent",
		"meta_name": "service_estimate_sent",
		"body": ("Hi {{1}}, the estimate for your {{2}} is {{3}}.\n\n"
		         "Job card {{4}}. Reply to this message to tell us whether to "
		         "go ahead."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("estimate_amount", None, "Currency"),
		           ("name", None, "Text")],
	},
	{
		"key": "estimate_approved_ack",
		"meta_name": "service_estimate_approved",
		"body": ("Hi {{1}}, thank you for approving the estimate for your {{2}}.\n\n"
		         "Work has started. Job card {{3}}."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("name", None, "Text")],
	},
	{
		"key": "awaiting_parts",
		"meta_name": "service_awaiting_parts",
		"body": ("Hi {{1}}, your {{2}} is waiting on a spare part.\n\n"
		         "Job card {{3}}. We will let you know the moment it reaches us."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("name", None, "Text")],
	},
	{
		"key": "repair_ready",
		"meta_name": "service_ready_for_delivery",
		"body": ("Hi {{1}}, your {{2}} is repaired and ready to collect.\n\n"
		         "Job card {{3}}. Amount due on collection: {{4}}."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("name", None, "Text"),
		           ("outstanding_amount", None, "Currency")],
	},
	{
		"key": "device_delivered",
		"meta_name": "service_delivered",
		"body": ("Hi {{1}}, your {{2}} has been handed back. Thank you for "
		         "choosing PhoneXpert.\n\nJob card {{3}}."),
		"params": [("customer_name", None, "Text"),
		           ("device_model", None, "Text"),
		           ("name", None, "Text")],
		"buttons": [REVIEW_BUTTON],
	},
]

FOOTER = "PhoneXpert"


def ensure_templates() -> dict:
	"""Create or refresh every template. Safe to run again.

	Wording and parameters are overwritten, because this file is where they
	are decided. `approval_status` is not: that is Meta's answer, and it is
	not ours to reset.
	"""
	made, updated = [], []

	for spec in TEMPLATES:
		existing = frappe.db.get_value("WhatsApp Template",
		                               {"template_key": spec["key"]}, "name")
		doc = (frappe.get_doc("WhatsApp Template", existing) if existing
		       else frappe.new_doc("WhatsApp Template"))

		doc.template_key = spec["key"]
		doc.meta_template_name = spec["meta_name"]
		doc.stream = spec.get("stream", "Service")
		doc.category = "Utility"
		doc.language = "en"
		doc.is_active = 1
		doc.header_type = spec.get("header_type", "None")
		doc.body_text = spec["body"]
		doc.footer_text = FOOTER
		doc.attach_print_format = spec.get("attach_print_format")
		if spec.get("reference_doctype"):
			doc.reference_doctype = spec["reference_doctype"]

		doc.set("parameters", [])
		for index, (fieldname, jinja, fmt) in enumerate(spec["params"], start=1):
			doc.append("parameters", {
				"param_index": index,
				"param_type": "Body",
				"source": "Jinja" if jinja else "Field",
				"fieldname": fieldname,
				"jinja_expression": jinja,
				"format": fmt,
			})

		doc.set("buttons", [])
		for button in spec.get("buttons") or []:
			doc.append("buttons", dict(button))

		doc.flags.ignore_permissions = True
		if existing:
			doc.save(ignore_permissions=True)
			updated.append(spec["key"])
		else:
			doc.insert(ignore_permissions=True)
			made.append(spec["key"])

	return {"created": made, "updated": updated}
