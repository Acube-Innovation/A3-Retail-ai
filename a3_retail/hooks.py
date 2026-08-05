from a3_retail.install import A3_ROLES

app_name = "a3_retail"
app_title = "A3 Retail"
app_publisher = "Acube Innovations Pvt Ltd"
app_description = "Mobile retail and service chain management for ERPNext"
app_email = "saaspurchases@acube.co"
app_license = "mit"

required_apps = ["frappe/erpnext"]

# Modules owned by this app — used to scope every fixture export.
A3_MODULES = [
	"A3 Retail Service",
	"A3 Retail Sales",
	"A3 Retail Finance",
	"A3 Retail Warranty",
	"A3 Retail Communication",
	"A3 Retail Operations",
	"A3 Retail Dashboard",
]

A3_ROLE_NAMES = [role["role_name"] for role in A3_ROLES]

# ---------------------------------------------------------------------------
# Includes
# ---------------------------------------------------------------------------
app_include_css = "/assets/a3_retail/css/a3_retail.css"
app_include_js = [
	"/assets/a3_retail/js/a3_retail.js",
	# POS is not a Form; the bundle patches cur_pos in place (scope 2.2).
	"/assets/a3_retail/js/pos_extension.js",
]

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
before_install = "a3_retail.install.before_install"
after_install = "a3_retail.install.after_install"
after_migrate = "a3_retail.install.after_migrate"
before_tests = "a3_retail.install.before_tests"

# ---------------------------------------------------------------------------
# Fixtures — every customisation ships as data so migrations are reproducible.
# Workflow and Role have no `module` field, so those are filtered by name.
# ---------------------------------------------------------------------------
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Property Setter", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Client Script", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Print Format", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Number Card", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Dashboard Chart", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Workspace", "filters": [["module", "in", A3_MODULES]]},
	{"dt": "Role", "filters": [["name", "in", A3_ROLE_NAMES]]},
	{"dt": "Workflow", "filters": [["name", "like", "A3 %"]]},
	{"dt": "Print Style", "filters": [["name", "like", "A3 Retail%"]]},
]

# ---------------------------------------------------------------------------
# Permissions — branch isolation on list views and reports.
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Branch Profile": "a3_retail.utils.permissions.branch_profile_query",
	"Service Job Card": "a3_retail.utils.permissions.service_job_card_query",
	"Service Estimate": "a3_retail.utils.permissions.service_estimate_query",
	"Technician Profile": "a3_retail.utils.permissions.technician_profile_query",
	"Stock Request": "a3_retail.utils.permissions.stock_request_query",
	"Stock Damage Report": "a3_retail.utils.permissions.stock_damage_report_query",
	"Demurrage Charge": "a3_retail.utils.permissions.demurrage_charge_query",
	"Device Exchange": "a3_retail.utils.permissions.device_exchange_query",
	"EMI Application": "a3_retail.utils.permissions.emi_application_query",
	"Warranty Registration": "a3_retail.utils.permissions.warranty_registration_query",
	"OEM Warranty Return": "a3_retail.utils.permissions.oem_warranty_return_query",
	"Branch Visit Log": "a3_retail.utils.permissions.branch_visit_log_query",
	"Customer Feedback": "a3_retail.utils.permissions.customer_feedback_query",
	"Call Task": "a3_retail.utils.permissions.call_task_query",
	"Courier Dispatch": "a3_retail.utils.permissions.courier_dispatch_query",
	"Incentive Calculation Run": "a3_retail.utils.permissions.incentive_calculation_run_query",
	"WhatsApp Message Log": "a3_retail.utils.permissions.whatsapp_message_log_query",
}

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
doc_events = {
	"Employee": {
		"on_update": "a3_retail.overrides.employee.on_update",
		"on_trash": "a3_retail.overrides.employee.on_trash",
	},
	"Service Job Card": {
		"on_update_after_submit": "a3_retail.a3_retail_operations.doctype.courier_dispatch.courier_dispatch.auto_draft_for_job_card",
	},
	"Serial No": {
		"before_insert": "a3_retail.overrides.serial_no.before_insert",
		"validate": "a3_retail.overrides.serial_no.validate",
	},
	"Customer": {
		"validate": "a3_retail.api.customer.validate_customer",
	},
	# Branch stamping for the accounting dimension (scope 1.1, 11.1).
	"Sales Invoice": {
		"before_validate": "a3_retail.overrides.transactions.stamp_branch",
		"validate": [
			"a3_retail.overrides.transactions.apply_margin_scheme",
			"a3_retail.overrides.sales_invoice.validate",
			"a3_retail.a3_retail_finance.doctype.emi_application.emi_application.validate_emi_payment",
		],
		"on_submit": [
			"a3_retail.overrides.sales_invoice.on_submit",
			"a3_retail.a3_retail_sales.doctype.seasonal_offer_campaign.seasonal_offer_campaign.track_offer_consumption",
			"a3_retail.a3_retail_finance.doctype.emi_application.emi_application.stamp_invoice_on_application",
			"a3_retail.a3_retail_warranty.doctype.warranty_registration.warranty_registration.register_from_invoice",
		],
		"on_cancel": [
			"a3_retail.overrides.sales_invoice.on_cancel",
			"a3_retail.a3_retail_finance.doctype.emi_application.emi_application.unstamp_invoice_on_application",
		],
	},
	"POS Invoice": {
		"before_validate": "a3_retail.overrides.transactions.stamp_branch",
		"validate": [
			"a3_retail.overrides.transactions.apply_margin_scheme",
			"a3_retail.overrides.sales_invoice.validate",
		],
		"on_submit": "a3_retail.overrides.sales_invoice.on_submit",
		"on_cancel": "a3_retail.overrides.sales_invoice.on_cancel",
	},
	"Purchase Invoice": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Journal Entry": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Payment Entry": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Stock Entry": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Delivery Note": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Purchase Receipt": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Sales Order": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Purchase Order": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
	"Material Request": {"before_validate": "a3_retail.overrides.transactions.stamp_branch"},
}

# ---------------------------------------------------------------------------
# Website routes — customer portal (scope 13.1)
# ---------------------------------------------------------------------------
website_route_rules = [
	{"from_route": "/approve-estimate/<token>", "to_route": "approve_estimate"},
	{"from_route": "/warranty/<token>", "to_route": "warranty_certificate"},
	{"from_route": "/feedback/<token>", "to_route": "feedback"},
	{"from_route": "/pay/<token>", "to_route": "pay_online"},
	{"from_route": "/invoice/<token>", "to_route": "invoice_download"},
]

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
scheduler_events = {
	"hourly": [
		"a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.flag_delayed_job_cards",
		"a3_retail.a3_retail_operations.doctype.courier_dispatch.courier_dispatch.scan_delayed_dispatches",
		"a3_retail.setup.helpdesk.escalate_breached_issues",
	],
	"daily": [
		"a3_retail.overrides.serial_no.recompute_warranty_state",
		"a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.auto_close_delivered",
		"a3_retail.a3_retail_service.doctype.service_estimate.service_estimate.expire_stale_estimates",
		"a3_retail.api.portal.clear_expired_otps",
		"a3_retail.a3_retail_sales.doctype.seasonal_offer_campaign.seasonal_offer_campaign.refresh_campaign_statuses",
		"a3_retail.a3_retail_finance.doctype.emi_application.emi_application.nudge_stale_applications",
		"a3_retail.a3_retail_warranty.doctype.warranty_registration.warranty_registration.recompute_statuses",
		"a3_retail.a3_retail_warranty.doctype.warranty_registration.warranty_registration.send_renewal_reminders",
		"a3_retail.a3_retail_operations.doctype.demurrage_charge.demurrage_charge.raise_storage_charges",
		"a3_retail.a3_retail_communication.doctype.telecalling_campaign.telecalling_campaign.close_finished_campaigns",
	],
	"weekly": [
		"a3_retail.a3_retail_warranty.doctype.oem_warranty_return.oem_warranty_return.flag_overdue_returns",
		"a3_retail.a3_retail_sales.doctype.stock_request.stock_request.flag_stuck_transfers",
		"a3_retail.a3_retail_operations.doctype.demurrage_charge.demurrage_charge.generate_dead_stock_todos",
	],
	"cron": {},
}

# ---------------------------------------------------------------------------
# Jinja
# ---------------------------------------------------------------------------
jinja = {
	"methods": [
		"a3_retail.utils.imei.format_imei",
	],
}
