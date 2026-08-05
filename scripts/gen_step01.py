import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb, write_all

OPS = "A3 Retail Operations"

print("Step 1 — settings and shared child tables")

write_all(
    DT("A3 Role Item", OPS, [f("role", "Link", "Role", "Role", reqd=1, in_list_view=1)], istable=1),
    DT(
        "A3 Reminder Day",
        OPS,
        [
            f("days_before", "Int", "Days Before", reqd=1, in_list_view=1),
            f("description", "Data", "Description", in_list_view=1),
        ],
        istable=1,
    ),
    DT(
        "A3 Dead Stock Rule",
        OPS,
        [
            f("item_group", "Link", "Item Group", "Item Group", reqd=1, in_list_view=1),
            f("dead_stock_days", "Int", "Dead Stock Days", reqd=1, default="90", in_list_view=1),
            f("provision_percent", "Percent", "Provision %", in_list_view=1),
        ],
        istable=1,
    ),
)

settings_fields = [
    sb("general_section", "General"),
    f("default_company", "Link", "Default Company", "Company"),
    f("enable_realtime_dashboard", "Check", "Enable Realtime Dashboard", default="1"),
    f("dashboard_refresh_seconds", "Int", "Dashboard Refresh (seconds)", default="30"),
    cb(),
    f("demo_data_installed", "Check", "Demo Data Installed", read_only=1),
    f("demo_data_installed_on", "Datetime", "Demo Data Installed On", read_only=1),

    sb("service_section", "Service"),
    f("default_tat_hours", "Int", "Default TAT (hours)", default="48"),
    f("require_device_photos", "Check", "Require Device Photos", default="1"),
    f("min_photos", "Int", "Minimum Photos", default="1", depends_on="require_device_photos"),
    f("require_signature", "Check", "Require Customer Signature", default="1"),
    f("diagnostic_charge_item", "Link", "Diagnostic Charge Item", "Item"),
    f("charge_diagnostic_on_rejection", "Check", "Charge Diagnostic Fee on Estimate Rejection"),
    cb(),
    f("free_storage_days", "Int", "Free Storage Days", default="15"),
    f("storage_charge_per_day", "Currency", "Storage Charge per Day", default="20"),
    f("storage_charge_item", "Link", "Storage Charge Item", "Item"),
    f("service_warranty_days", "Int", "Warranty on Repair (days)", default="90"),
    f("auto_close_after_days", "Int", "Auto Close Delivered Job Cards After (days)", default="7"),

    sb("imei_section", "IMEI"),
    f("enforce_luhn_check", "Check", "Enforce IMEI Luhn Check", default="1"),
    f(
        "allow_imei_override_roles",
        "Table MultiSelect",
        "Roles Allowed to Override IMEI Check",
        "A3 Role Item",
    ),

    sb("sales_section", "Sales"),
    f("enforce_min_selling_price", "Check", "Enforce Minimum Selling Price", default="1"),
    f("allow_discount_roles", "Table MultiSelect", "Roles Allowed to Discount", "A3 Role Item"),
    f("max_discount_percent_branch_user", "Percent", "Max Discount % (Branch User)", default="5"),
    cb(),
    f("require_sales_person", "Check", "Require Sales Person on Invoice", default="1"),
    f("require_serial_on_device_sale", "Check", "Require IMEI on Device Sale", default="1"),
    f("walkin_public_supplier", "Link", "Walk-in Public Supplier", "Supplier"),

    sb("warranty_section", "Warranty"),
    f("ew_sale_window_days", "Int", "Extended Warranty Sale Window (days)", default="15"),
    f("ew_reminder_days", "Table", "Warranty Reminder Schedule", "A3 Reminder Day"),
    cb(),
    f("deferred_revenue_enabled", "Check", "Defer Extended Warranty Revenue", default="1"),
    f("deferred_revenue_account", "Link", "Deferred EW Revenue Account", "Account"),
    f("warranty_expense_account", "Link", "Warranty Expense Account", "Account"),

    sb("emi_section", "EMI"),
    f("require_all_documents_before_submit", "Check", "Require All Documents Before Submit", default="1"),
    f("auto_cancel_approved_after_days", "Int", "Auto Cancel Approved Applications After (days)", default="7"),
    cb(),
    f("emi_followup_after_days", "Int", "Nudge Coordinator After (days)", default="3"),

    sb("inventory_section", "Inventory"),
    f("dead_stock_rules", "Table", "Dead Stock Thresholds", "A3 Dead Stock Rule"),
    cb(),
    f("transit_warehouse", "Link", "Goods In Transit Warehouse", "Warehouse"),
    f("stock_request_auto_approve_limit", "Currency", "Auto-approve Service Requests Upto", default="10000"),
    f("stock_request_ho_approval_limit", "Currency", "Head Office Approval Above", default="25000"),

    sb("communication_section", "Communication"),
    f("enable_whatsapp", "Check", "Enable WhatsApp"),
    f("enable_email", "Check", "Enable Email", default="1"),
    f("activate_communication_rules", "Check", "Activate Communication Rules"),
    cb(),
    f("default_country_code", "Data", "Default Country Code", default="91"),

    sb("portal_section", "Portal"),
    f("otp_validity_minutes", "Int", "OTP Validity (minutes)", default="10"),
    f("otp_max_attempts", "Int", "Max OTP Attempts", default="5"),
    f("otp_max_requests_per_hour", "Int", "Max OTP Requests per Hour", default="5"),
    cb(),
    f("payment_gateway_account", "Link", "Payment Gateway Account", "Payment Gateway Account"),
    f("upi_vpa", "Data", "UPI VPA"),
    f("portal_terms", "Text Editor", "Portal Terms"),

    sb("numbering_section", "Numbering"),
    f("job_card_prefix", "Data", "Job Card Prefix", default="JC"),
    f("estimate_prefix", "Data", "Estimate Prefix", default="EST"),
    f("stock_request_prefix", "Data", "Stock Request Prefix", default="SR"),
    f("damage_prefix", "Data", "Damage Report Prefix", default="DMG"),
    cb(),
    f("exchange_prefix", "Data", "Device Exchange Prefix", default="EXC"),
    f("visit_log_prefix", "Data", "Visit Log Prefix", default="FL"),
]

SETTINGS_CONTROLLER = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class A3RetailSettings(Document):
	def validate(self):
		if self.min_photos and self.min_photos > 4:
			frappe.throw(_("A job card captures at most 4 device photos."))
		if self.max_discount_percent_branch_user and self.max_discount_percent_branch_user > 100:
			frappe.throw(_("Maximum discount cannot exceed 100%."))
		if self.otp_validity_minutes and self.otp_validity_minutes < 1:
			frappe.throw(_("OTP validity must be at least one minute."))

	def on_update(self):
		frappe.clear_cache(doctype="A3 Retail Settings")


def get_settings():
	"""Cached accessor used across the app."""
	return frappe.get_cached_doc("A3 Retail Settings")


def get_value(fieldname, default=None):
	value = frappe.db.get_single_value("A3 Retail Settings", fieldname)
	return default if value in (None, "") else value
'''

write_all(
    DT(
        "A3 Retail Settings",
        OPS,
        settings_fields,
        issingle=1,
        track_changes=1,
        perms_spec=[("System Manager", "CRU"), ("A3 Retail Admin", "CRU"), ("Accounts Manager", "R")],
    ),
)

import os

path = os.path.join(
    "/home/user/A3-Retail/a3_retail/apps/a3_retail/a3_retail",
    "a3_retail_operations/doctype/a3_retail_settings/a3_retail_settings.py",
)
open(path, "w").write(SETTINGS_CONTROLLER)
print("controller written")
