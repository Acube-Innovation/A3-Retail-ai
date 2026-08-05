import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

COMM = "A3 Retail Communication"

STREAMS = ("Sales\nService\nEMI / Finance\nWarranty\nHelpdesk\nMarketing\nDelivery\nHR Internal")
PROVIDERS = "Meta Cloud API\nGupshup\nTwilio\nInterakt\nAiSensy\nWati"
CATEGORIES = "Utility\nMarketing\nAuthentication"
HEADER_TYPES = "None\nText\nImage\nDocument\nVideo"
LANGUAGES = "en\nen_US\nml\nhi"
APPROVAL = "Draft\nSubmitted to Meta\nApproved\nRejected"
PARAM_TYPES = "Header\nBody\nButton URL"
PARAM_SOURCES = "Field\nJinja\nStatic"
PARAM_FORMATS = "Text\nCurrency\nDate\nDatetime"
BUTTON_TYPES = "URL\nQuick Reply"
TRIGGERS = ("On Insert\nOn Submit\nOn Update\nOn Status Change\nOn Cancel\n"
            "Days Before Date Field\nDays After Date Field\nScheduled (Cron)")
RECIPIENTS = "Customer\nField on Document\nRole\nEmployee Field\nStatic List"
LOG_STATUS = ("Queued\nSent\nDelivered\nRead\nFailed\nBlocked (Opt-out)\nHeld (Quiet Hours)")

print("Step 22 — communication engine")

DT("WhatsApp Template Parameter", COMM, [
	f("param_index", "Int", "Index", reqd=1, in_list_view=1),
	f("param_type", "Select", "Type", PARAM_TYPES, default="Body", in_list_view=1),
	f("source", "Select", "Source", PARAM_SOURCES, default="Field", in_list_view=1),
	f("fieldname", "Data", "Fieldname", in_list_view=1),
	f("jinja_expression", "Small Text", "Jinja Expression"),
	f("static_value", "Data", "Static Value"),
	f("format", "Select", "Format", PARAM_FORMATS, default="Text"),
], istable=1).write()

DT("WhatsApp Template Button", COMM, [
	f("button_type", "Select", "Type", BUTTON_TYPES, default="URL", in_list_view=1),
	f("text", "Data", "Text", reqd=1, in_list_view=1),
	f("url_suffix", "Data", "URL Suffix", in_list_view=1),
], istable=1).write()

DT("WhatsApp Sender Profile", COMM, [
	f("profile_name", "Data", "Profile Name", reqd=1, unique=1, in_list_view=1),
	f("stream", "Select", "Stream", STREAMS, reqd=1, in_list_view=1, in_standard_filter=1),
	f("branch", "Link", "Branch", "Branch", description="Blank applies to every branch"),
	cb(),
	f("phone_number_id", "Data", "Phone Number ID", reqd=1),
	f("display_number", "Data", "Display Number", in_list_view=1),
	f("display_name", "Data", "Display Name"),
	f("is_active", "Check", "Active", default="1"),

	sb("options_section", "Options"),
	f("default_language", "Select", "Default Language", LANGUAGES, default="en"),
	f("signature_footer", "Small Text", "Signature Footer"),
	cb(),
	f("fallback_to_sms", "Check", "Fallback to SMS"),
], autoname="field:profile_name", title_field="profile_name",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD")]).write()

DT("WhatsApp Template", COMM, [
	f("template_key", "Data", "Template Key", reqd=1, unique=1, in_list_view=1,
	  description="Internal key used in code, e.g. job_card_created"),
	f("meta_template_name", "Data", "Meta Template Name", reqd=1),
	f("stream", "Select", "Stream", STREAMS, reqd=1, in_list_view=1, in_standard_filter=1),
	f("category", "Select", "Category", CATEGORIES, reqd=1, default="Utility", in_list_view=1,
	  in_standard_filter=1),
	cb(),
	f("language", "Select", "Language", LANGUAGES, default="en"),
	f("is_active", "Check", "Active", default="1"),
	f("approval_status", "Select", "Meta Approval", APPROVAL, default="Draft", in_list_view=1),
	f("reference_doctype", "Link", "Reference DocType", "DocType"),

	sb("content_section", "Content"),
	f("header_type", "Select", "Header Type", HEADER_TYPES, default="None"),
	f("header_content", "Data", "Header Content", depends_on="eval:doc.header_type!='None'"),
	f("body_text", "Text", "Body", reqd=1,
	  description="Must match the approved Meta template exactly, placeholders included"),
	f("footer_text", "Data", "Footer"),
	cb(),
	f("attach_print_format", "Link", "Attach Print Format", "Print Format"),

	sb("params_section", "Parameters"),
	f("parameters", "Table", "Parameters", "WhatsApp Template Parameter"),
	f("buttons", "Table", "Buttons", "WhatsApp Template Button"),
], autoname="field:template_key", title_field="template_key",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Branch Manager", "R")]).write()

DT("Communication Rule", COMM, [
	f("rule_name", "Data", "Rule Name", reqd=1, unique=1, in_list_view=1),
	f("reference_doctype", "Link", "Reference DocType", "DocType", reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("trigger_type", "Select", "Trigger", TRIGGERS, reqd=1, in_list_view=1, in_standard_filter=1),
	f("is_active", "Check", "Active", in_list_view=1, in_standard_filter=1),
	cb(),
	f("watch_field", "Data", "Watch Field", description="e.g. status, for a status change"),
	f("from_value", "Data", "From Value"),
	f("to_value", "Data", "To Value"),
	f("date_field", "Data", "Date Field"),
	f("days_offset", "Int", "Days Offset"),
	f("cron_expression", "Data", "Cron Expression"),

	sb("condition_section", "Condition"),
	f("condition", "Code", "Condition (Python)", options="Python",
	  description="Evaluated with frappe.safe_eval, e.g. doc.grand_total > 0"),

	sb("channels_section", "Channels"),
	f("send_whatsapp", "Check", "Send WhatsApp", default="1"),
	f("whatsapp_template", "Link", "WhatsApp Template", "WhatsApp Template",
	  depends_on="send_whatsapp"),
	f("sender_profile", "Link", "Sender Profile", "WhatsApp Sender Profile",
	  description="Blank resolves from stream and branch"),
	cb(),
	f("send_email", "Check", "Send Email"),
	f("email_template", "Link", "Email Template", "Email Template", depends_on="send_email"),
	f("email_account", "Link", "Email Account", "Email Account", depends_on="send_email"),
	f("send_sms", "Check", "Send SMS (fallback)"),

	sb("recipients_section", "Recipients"),
	f("recipient_type", "Select", "Recipient", RECIPIENTS, default="Customer", reqd=1),
	f("recipient_field", "Data", "Recipient Field",
	  depends_on="eval:doc.recipient_type=='Field on Document'"),
	f("recipient_role", "Link", "Role", "Role", depends_on="eval:doc.recipient_type=='Role'"),
	cb(),
	f("static_recipients", "Small Text", "Static Recipients",
	  depends_on="eval:doc.recipient_type=='Static List'"),
	f("cc_branch_manager", "Check", "CC Branch Manager"),

	sb("control_section", "Control"),
	f("max_sends_per_document", "Int", "Max Sends per Document", default="1"),
	cb(),
	f("priority", "Int", "Priority", default="1"),
], autoname="field:rule_name", title_field="rule_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD")]).write()

DT("WhatsApp Message Log", COMM, [
	f("to_number", "Data", "To", in_list_view=1, search_index=1),
	f("stream", "Select", "Stream", "\n" + STREAMS, in_standard_filter=1),
	f("status", "Select", "Status", LOG_STATUS, default="Queued", in_list_view=1,
	  in_standard_filter=1),
	cb(),
	f("template", "Link", "Template", "WhatsApp Template", in_list_view=1),
	f("communication_rule", "Link", "Rule", "Communication Rule"),
	f("sender_profile", "Link", "Sender Profile", "WhatsApp Sender Profile"),
	f("customer", "Link", "Customer", "Customer"),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),

	sb("reference_section", "Reference"),
	f("reference_doctype", "Link", "Reference DocType", "DocType"),
	f("reference_name", "Dynamic Link", "Reference", "reference_doctype"),

	sb("payload_section", "Message"),
	f("message_body", "Text", "Rendered Body"),
	f("payload", "Code", "Payload", options="JSON"),
	f("provider_message_id", "Data", "Provider Message ID", search_index=1),

	sb("delivery_section", "Delivery"),
	f("sent_on", "Datetime", "Sent On"),
	f("delivered_on", "Datetime", "Delivered On"),
	f("read_on", "Datetime", "Read On"),
	cb(),
	f("retry_count", "Int", "Retries"),
	f("error_code", "Data", "Error Code"),
	f("error_message", "Small Text", "Error"),
	f("cost", "Currency", "Cost"),
], autoname="hash", title_field="to_number", sort_field="creation", sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "R"),
               ("Branch Manager", "R"), ("Accounts Manager", "R")]).write()

DT("WhatsApp Settings", COMM, [
	f("enabled", "Check", "Enabled"),
	f("provider", "Select", "Provider", PROVIDERS, default="Meta Cloud API"),
	f("api_base_url", "Data", "API Base URL", default="https://graph.facebook.com/v20.0"),
	f("business_account_id", "Data", "WABA ID"),
	cb(),
	f("access_token", "Password", "Access Token"),
	f("webhook_verify_token", "Password", "Webhook Verify Token"),
	f("default_country_code", "Data", "Default Country Code", default="91"),

	sb("delivery_section", "Delivery"),
	f("queue_messages", "Check", "Send via Background Queue", default="1"),
	f("retry_attempts", "Int", "Retry Attempts", default="3"),
	f("retry_interval_minutes", "Int", "Retry Interval (minutes)", default="15"),
	cb(),
	f("log_retention_days", "Int", "Log Retention (days)", default="365"),

	sb("compliance_section", "Compliance"),
	f("respect_marketing_optin", "Check", "Respect Marketing Opt-in", default="1"),
	f("quiet_hours_from", "Time", "Quiet Hours From", default="21:00:00"),
	f("quiet_hours_to", "Time", "Quiet Hours To", default="08:00:00"),
	cb(),
	f("daily_marketing_cap_per_customer", "Int", "Daily Marketing Cap per Customer", default="1"),
], issingle=1, perms_spec=[("System Manager", "CRU"), ("A3 Retail Admin", "CRU")]).write()
