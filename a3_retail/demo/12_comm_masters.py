"""Seed 12 — sender profiles, 26 templates and 30 communication rules (scope 9.4 – 9.6).

Rules are seeded **inactive**: `A3 Retail Settings.activate_communication_rules`
is the master switch, so installing the demo never messages a real customer.
"""

import frappe

# profile, stream, number, display name
SENDERS = [
	("MW Sales", "Sales", "+91 90000 11111", "Mobile World Sales"),
	("MW Service", "Service", "+91 90000 22222", "Mobile World Service"),
	("MW Finance", "EMI / Finance", "+91 90000 33333", "Mobile World EMI Desk"),
	("MW Warranty", "Warranty", "+91 90000 44444", "Mobile World Warranty"),
	("MW Care", "Helpdesk", "+91 90000 55555", "Mobile World Customer Care"),
	("MW Offers", "Marketing", "+91 90000 66666", "Mobile World Offers"),
	("MW Delivery", "Delivery", "+91 90000 77777", "Mobile World Delivery"),
	("MW Internal", "HR Internal", "+91 90000 88888", "Mobile World Internal"),
]

# key, stream, category, body
TEMPLATES = [
	("job_card_created", "Service", "Utility",
	 "Hi {{1}}, we have received your {{2}} for service. Job Card: {{3}}. Expected delivery: {{4}}. Track here: {{5}}"),
	("estimate_sent", "Service", "Utility",
	 "Hi {{1}}, the repair estimate for your {{2}} is Rs {{3}}. Please approve here: {{4}} (valid till {{5}})"),
	("estimate_approved_ack", "Service", "Utility",
	 "Thank you {{1}}. Repair of your {{2}} has started. We will update you by {{3}}."),
	("awaiting_parts", "Service", "Utility",
	 "Hi {{1}}, the part required for your {{2}} (Job Card {{3}}) is being arranged. Revised delivery: {{4}}. Sorry for the delay."),
	("repair_ready", "Service", "Utility",
	 "Good news {{1}}! Your {{2}} is ready. Balance payable Rs {{3}}. Collection OTP: {{4}}. Branch: {{5}}"),
	("device_delivered", "Service", "Utility",
	 "Hi {{1}}, your {{2}} has been handed over on {{3}}. Invoice {{4}}. Thank you for choosing us."),
	("service_feedback_request", "Service", "Utility",
	 "Hi {{1}}, how was your service experience for Job Card {{2}}? Rate us here: {{3}}"),
	("pickup_reminder", "Service", "Utility",
	 "Hi {{1}}, your {{2}} has been ready since {{3}}. Please collect it. Storage charges apply after {{4}}."),
	("unclaimed_goods_notice", "Service", "Utility",
	 "Hi {{1}}, your {{2}} has been uncollected since {{3}} ({{4}} days). Please collect it to avoid further charges."),
	("advance_receipt", "Service", "Utility",
	 "Hi {{1}}, advance of Rs {{2}} received for Job Card {{3}}. Balance payable on delivery."),
	("portal_otp", "Service", "Authentication",
	 "Your Mobile World verification code is {{1}}. It is valid for a few minutes. ({{2}})"),
	("sale_invoice", "Sales", "Utility",
	 "Thank you {{1}}! Invoice {{2}} for Rs {{3}}. IMEI {{4}}. Download: {{5}}"),
	("order_ready_for_delivery", "Sales", "Utility",
	 "Hi {{1}}, your order {{2}} is out for delivery. Expected: {{3}}."),
	("payment_receipt", "Sales", "Utility",
	 "Hi {{1}}, we received Rs {{2}} on {{3}} against {{4}}. Thank you."),
	("courier_dispatched", "Delivery", "Utility",
	 "Hi {{1}}, your parcel is dispatched via {{2}}. AWB {{3}}. Track: {{4}}"),
	("emi_docs_pending", "EMI / Finance", "Utility",
	 "Hi {{1}}, to process your EMI application {{2}}, please provide: {{3}}."),
	("emi_approved", "EMI / Finance", "Utility",
	 "Congratulations {{1}}! Your EMI is approved. Loan A/c {{2}}, EMI Rs {{3}} x {{4}} months, first EMI on {{5}}."),
	("emi_rejected", "EMI / Finance", "Utility",
	 "Hi {{1}}, we could not process your EMI application {{2}}. Our team will call you with alternatives."),
	("emi_first_installment_reminder", "EMI / Finance", "Utility",
	 "Hi {{1}}, your first EMI of Rs {{2}} is due on {{3}} for loan {{4}}."),
	("warranty_registered", "Warranty", "Utility",
	 "Hi {{1}}, your {{2}} (IMEI {{3}}) is registered. Warranty valid till {{4}}. Certificate: {{5}}"),
	("ew_certificate", "Warranty", "Utility",
	 "Hi {{1}}, your {{2}} plan is active from {{3}} to {{4}}. Certificate: {{5}}"),
	("ew_upsell_offer", "Warranty", "Marketing",
	 "Hi {{1}}, warranty of your {{2}} ends on {{3}}. Extend for just Rs {{4}}. Reply YES or visit {{5}}."),
	("ew_renewal_reminder", "Warranty", "Marketing",
	 "Hi {{1}}, your protection plan expires on {{2}}. Renew now and stay covered. {{3}}"),
	("ew_winback_offer", "Warranty", "Marketing",
	 "Hi {{1}}, your protection plan expired on {{2}}. Reactivate today and stay covered. {{3}}"),
	("warranty_claim_approved", "Warranty", "Utility",
	 "Hi {{1}}, your warranty claim for {{2}} is approved. Covered amount Rs {{3}}."),
	("ticket_created", "Helpdesk", "Utility",
	 "Hi {{1}}, we have logged your complaint {{2}}. We will respond by {{3}}."),
	("ticket_resolved", "Helpdesk", "Utility",
	 "Hi {{1}}, complaint {{2}} is resolved: {{3}}. Rate our support: {{4}}"),
	("seasonal_offer_blast", "Marketing", "Marketing",
	 "{{1}} is here! {{2}} on {{3}}. Valid till {{4}}. Visit your nearest Mobile World. {{5}}"),
	("birthday_greeting", "Marketing", "Marketing",
	 "Happy Birthday {{1}}! Enjoy {{2}} off on accessories this week at Mobile World."),
]

# rule, doctype, trigger, template, watch field, to value, recipient, date field, offset
RULES = [
	("Job card created", "Service Job Card", "On Submit", "job_card_created", None, None, "Customer", None, 0),
	("Estimate sent", "Service Estimate", "On Submit", "estimate_sent", None, None, "Customer", None, 0),
	("Estimate approved", "Service Job Card", "On Status Change", "estimate_approved_ack",
	 "status", "Estimate Approved", "Customer", None, 0),
	("Awaiting parts", "Service Job Card", "On Status Change", "awaiting_parts",
	 "status", "Awaiting Parts", "Customer", None, 0),
	("Ready for delivery", "Service Job Card", "On Status Change", "repair_ready",
	 "status", "Ready for Delivery", "Customer", None, 0),
	("Device delivered", "Service Job Card", "On Status Change", "device_delivered",
	 "status", "Delivered", "Customer", None, 0),
	("Feedback request", "Service Job Card", "Days After Date Field", "service_feedback_request",
	 None, None, "Customer", "delivered_on", 1),
	("Pickup reminder", "Service Job Card", "Days After Date Field", "pickup_reminder",
	 None, None, "Customer", "ready_on", 7),
	("Advance receipt", "Payment Entry", "On Submit", "advance_receipt", None, None, "Customer", None, 0),
	("Sale invoice", "Sales Invoice", "On Submit", "sale_invoice", None, None, "Customer", None, 0),
	("Payment receipt", "Payment Entry", "On Submit", "payment_receipt", None, None, "Customer", None, 0),
	("Courier dispatched", "Courier Dispatch", "On Submit", "courier_dispatched", None, None,
	 "Customer", None, 0),
	("EMI docs pending", "EMI Application", "On Insert", "emi_docs_pending", None, None, "Customer", None, 0),
	("EMI approved", "EMI Application", "On Status Change", "emi_approved", "status", "Approved",
	 "Customer", None, 0),
	("EMI rejected", "EMI Application", "On Status Change", "emi_rejected", "status", "Rejected",
	 "Customer", None, 0),
	("First EMI reminder", "EMI Application", "Days Before Date Field",
	 "emi_first_installment_reminder", None, None, "Customer", "first_emi_date", 3),
	("Warranty registered", "Warranty Registration", "On Submit", "warranty_registered", None, None,
	 "Customer", None, 0),
	("EW certificate", "Warranty Registration", "On Submit", "ew_certificate", None, None,
	 "Customer", None, 0),
	("EW upsell", "Warranty Registration", "Days Before Date Field", "ew_upsell_offer", None, None,
	 "Customer", "brand_warranty_expiry", 30),
	("EW renewal", "Warranty Registration", "Days Before Date Field", "ew_renewal_reminder", None,
	 None, "Customer", "ew_expiry_date", 30),
	("EW win-back", "Warranty Registration", "Days After Date Field", "ew_winback_offer", None,
	 None, "Customer", "ew_expiry_date", 7),
	("Ticket created", "Issue", "On Insert", "ticket_created", None, None, "Customer", None, 0),
	("Ticket resolved", "Issue", "On Status Change", "ticket_resolved", "status", "Resolved",
	 "Customer", None, 0),
	("Offer launch", "Seasonal Offer Campaign", "On Status Change", "seasonal_offer_blast",
	 "status", "Active", "Customer", None, 0),
	("Birthday greeting", "Customer", "Days Before Date Field", "birthday_greeting", None, None,
	 "Customer", "a3_dob", 0),
	("Stock request approval", "Stock Request", "On Status Change", None, "status",
	 "Pending Approval", "Role", None, 0),
	("Damage approval", "Stock Damage Report", "On Status Change", None, "status",
	 "Pending Approval", "Role", None, 0),
	("Uncollected device notice", "Service Job Card", "Days After Date Field",
	 "unclaimed_goods_notice", None, None, "Customer", "ready_on", 90),
	("Warranty claim approved", "Warranty Registration", "On Status Change",
	 "warranty_claim_approved", "status", "Fully Claimed", "Customer", None, 0),
	("Order ready", "Sales Order", "On Submit", "order_ready_for_delivery", None, None,
	 "Customer", None, 0),
]

CONTACT_PARAMS = {
	"job_card_created": [("Field", "customer_name"), ("Field", "device_model"),
	                     ("Field", "name"), ("Field", "estimated_delivery_date"),
	                     ("Static", "")],
	"repair_ready": [("Field", "customer_name"), ("Field", "device_model"),
	                 ("Field", "customer_payable"), ("Field", "delivery_otp"),
	                 ("Field", "branch")],
}


def run():
	_settings()
	_senders()
	_templates()
	_rules()


def _settings():
	settings = frappe.get_single("WhatsApp Settings")
	if not settings.api_base_url:
		settings.api_base_url = "https://graph.facebook.com/v20.0"
	settings.default_country_code = settings.default_country_code or "91"
	settings.respect_marketing_optin = 1
	settings.queue_messages = 1
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


def _senders():
	for name, stream, number, display in SENDERS:
		if frappe.db.exists("WhatsApp Sender Profile", name):
			continue
		doc = frappe.new_doc("WhatsApp Sender Profile")
		doc.profile_name = name
		doc.stream = stream
		doc.display_number = number
		doc.display_name = display
		# Placeholder until the client's WABA numbers are provisioned.
		doc.phone_number_id = f"PENDING-{name.replace(' ', '-').upper()}"
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _templates():
	for key, stream, category, body in TEMPLATES:
		if frappe.db.exists("WhatsApp Template", key):
			continue
		doc = frappe.new_doc("WhatsApp Template")
		doc.template_key = key
		doc.meta_template_name = key
		doc.stream = stream
		doc.category = category
		doc.body_text = body
		doc.language = "en"
		doc.is_active = 1
		doc.approval_status = "Draft"

		for index, (source, value) in enumerate(CONTACT_PARAMS.get(key, []), start=1):
			doc.append(
				"parameters",
				{
					"param_index": index,
					"param_type": "Body",
					"source": source,
					"fieldname": value if source == "Field" else None,
					"static_value": value if source == "Static" else None,
					"format": "Currency" if "payable" in str(value) or "total" in str(value) else "Text",
				},
			)

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _rules():
	for (name, doctype, trigger, template, watch_field, to_value, recipient,
	     date_field, offset) in RULES:
		if frappe.db.exists("Communication Rule", name):
			continue
		if not frappe.db.exists("DocType", doctype):
			continue

		doc = frappe.new_doc("Communication Rule")
		doc.rule_name = name
		doc.reference_doctype = doctype
		doc.trigger_type = trigger
		doc.watch_field = watch_field
		doc.to_value = to_value
		doc.date_field = date_field
		doc.days_offset = offset
		doc.recipient_type = recipient
		doc.recipient_role = "Branch Manager" if recipient == "Role" else None
		doc.send_whatsapp = 1 if template else 0
		doc.whatsapp_template = template if template and frappe.db.exists("WhatsApp Template", template) else None
		doc.send_email = 0 if template else 1
		doc.max_sends_per_document = 1
		doc.priority = 1
		# Inactive by design: the settings flag is the master switch.
		doc.is_active = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
