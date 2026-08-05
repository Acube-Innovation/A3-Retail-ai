# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Custom fields on core ERPNext/HRMS doctypes.

Golden rule 1: never edit core files. Everything here is created through
`create_custom_fields`, tagged with an A3 Retail module so it is exported by the
`Custom Field` fixture in hooks.py, and is safe to re-run.

Naming: our own fields are prefixed `a3_` so they can never collide with a future
ERPNext field. The two exceptions are `custom_branch` on Warehouse / Cost Center /
POS Profile, which the scope document names explicitly (6.1) because reports and
the Stock Explorer query it by name.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OPS_MODULE = "A3 Retail Operations"


def branch_link(label="Branch", **kwargs):
	field = {
		"fieldname": "custom_branch",
		"label": label,
		"fieldtype": "Link",
		"options": "Branch",
		"module": OPS_MODULE,
		"read_only": 1,
		"no_copy": 1,
		"description": "Set from Branch Profile. Used by branch-wise reports and the Stock Explorer.",
	}
	field.update(kwargs)
	return field


# Step 2 — branch back-references on the stock/accounting masters.
BRANCH_BACKREF_FIELDS = {
	"Warehouse": [branch_link(insert_after="company", in_standard_filter=1)],
	"Cost Center": [branch_link(insert_after="company")],
	"POS Profile": [branch_link(insert_after="company")],
}


SALES_MODULE = "A3 Retail Sales"
SERVICE_MODULE = "A3 Retail Service"

WARRANTY_STATES = "Not Sold\nIn Warranty\nIn Extended Warranty\nOut of Warranty\nVoid"

EW_COVERAGE = "Extended Warranty\nScreen Protection\nAccidental & Liquid Damage\nCombo"

SUPPLIER_CATEGORIES = (
	"Device Distributor\nAccessory Vendor\nSpare Parts\nService Vendor\nCourier\n"
	"Utilities & Office\nUnregistered Local"
)


def _field(fieldname, label, fieldtype, module, **kwargs):
	field = {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": fieldtype,
		"module": module,
	}
	field.update(kwargs)
	return field


# Step 4 — Item, Serial No, Customer, Supplier (scope 1.2 – 1.4).
MASTER_FIELDS = {
	"Item": [
		_field("a3_device_section", "Device Details", "Section Break", SALES_MODULE,
			insert_after="item_group", collapsible=1),
		_field("a3_is_device", "Is Device", "Check", SALES_MODULE, insert_after="a3_device_section",
			description="Drives IMEI capture at POS and on the Reception Desk"),
		_field("a3_device_model", "Device Model", "Link", SALES_MODULE, options="Device Model",
			insert_after="a3_is_device", depends_on="eval:doc.a3_is_device"),
		_field("a3_ram", "RAM", "Data", SALES_MODULE, insert_after="a3_device_model",
			depends_on="eval:doc.a3_is_device"),
		_field("a3_storage", "Storage", "Data", SALES_MODULE, insert_after="a3_ram",
			depends_on="eval:doc.a3_is_device"),
		_field("a3_colour", "Colour", "Data", SALES_MODULE, insert_after="a3_storage"),
		_field("a3_device_col_break", "", "Column Break", SALES_MODULE, insert_after="a3_colour"),
		_field("a3_brand_warranty_months", "Brand Warranty (Months)", "Int", SALES_MODULE,
			insert_after="a3_device_col_break", default="12"),
		_field("a3_accessory_warranty_months", "Accessory Warranty (Months)", "Int", SALES_MODULE,
			insert_after="a3_brand_warranty_months", default="6"),
		_field("a3_is_margin_scheme", "Under Margin Scheme (Rule 32(5))", "Check", SALES_MODULE,
			insert_after="a3_accessory_warranty_months",
			description="Used devices: GST is charged on the margin only"),

		_field("a3_plan_section", "Extended Warranty Plan", "Section Break", SALES_MODULE,
			insert_after="a3_is_margin_scheme", collapsible=1),
		_field("a3_is_ew_plan", "Is Extended Warranty Plan", "Check", SALES_MODULE,
			insert_after="a3_plan_section"),
		_field("a3_ew_duration_months", "EW Duration (Months)", "Int", SALES_MODULE,
			insert_after="a3_is_ew_plan", depends_on="eval:doc.a3_is_ew_plan"),
		_field("a3_ew_coverage_type", "EW Coverage", "Select", SALES_MODULE, options=EW_COVERAGE,
			insert_after="a3_ew_duration_months", depends_on="eval:doc.a3_is_ew_plan"),
		_field("a3_plan_col_break", "", "Column Break", SALES_MODULE, insert_after="a3_ew_coverage_type"),
		_field("a3_ew_claim_limit", "Claim Value Cap (%)", "Percent", SALES_MODULE, default="100",
			insert_after="a3_plan_col_break", depends_on="eval:doc.a3_is_ew_plan"),

		_field("a3_service_section", "Service & Selling Controls", "Section Break", SERVICE_MODULE,
			insert_after="a3_ew_claim_limit", collapsible=1),
		_field("a3_is_service_item", "Is Service Item", "Check", SERVICE_MODULE,
			insert_after="a3_service_section", description="Labour lines on job cards and estimates"),
		_field("a3_default_labour_minutes", "Standard Labour Minutes", "Int", SERVICE_MODULE,
			insert_after="a3_is_service_item", depends_on="eval:doc.a3_is_service_item"),
		_field("a3_technician_incentive", "Technician Incentive / Unit", "Currency", SERVICE_MODULE,
			insert_after="a3_default_labour_minutes"),
		_field("a3_service_col_break", "", "Column Break", SERVICE_MODULE,
			insert_after="a3_technician_incentive"),
		# Cost/margin fields are masked from branch users (scope 13.5).
		_field("a3_sales_spiff", "Sales Spiff / Unit", "Currency", SALES_MODULE, permlevel=1,
			insert_after="a3_service_col_break"),
		_field("a3_min_selling_price", "Min Selling Price", "Currency", SALES_MODULE, permlevel=1,
			insert_after="a3_sales_spiff", description="POS blocks a lower rate unless Branch Manager"),
	],
	# The Serial No register IS the IMEI register (ADR-02).
	"Serial No": [
		_field("a3_imei_section", "IMEI & Warranty", "Section Break", SALES_MODULE,
			insert_after="item_code"),
		_field("a3_imei_1", "IMEI 1", "Data", SALES_MODULE, insert_after="a3_imei_section",
			in_standard_filter=1, search_index=1, length=20),
		_field("a3_imei_2", "IMEI 2", "Data", SALES_MODULE, insert_after="a3_imei_1", length=20,
			description="Second slot on dual-SIM devices"),
		_field("a3_device_serial", "Manufacturer Serial", "Data", SALES_MODULE, insert_after="a3_imei_2"),
		_field("a3_is_exchanged_device", "Acquired via Exchange", "Check", SALES_MODULE,
			insert_after="a3_device_serial", read_only=1),
		# Scope 1.2: refurb / grey stock can carry a non-standard IMEI. Ticking
		# this waives the Luhn check for this record only, and requires a role
		# listed in A3 Retail Settings.allow_imei_override_roles.
		_field("a3_imei_override", "Override IMEI Check", "Check", SALES_MODULE,
			insert_after="a3_is_exchanged_device"),
		_field("a3_imei_col_break", "", "Column Break", SALES_MODULE, insert_after="a3_imei_override"),
		_field("a3_activation_date", "Activation Date", "Date", SALES_MODULE,
			insert_after="a3_imei_col_break", read_only=1),
		_field("a3_sales_invoice", "Sales Invoice", "Link", SALES_MODULE, options="Sales Invoice",
			insert_after="a3_activation_date", read_only=1),
		_field("a3_branch", "Sold From Branch", "Link", SALES_MODULE, options="Branch",
			insert_after="a3_sales_invoice", read_only=1, in_standard_filter=1),
		_field("a3_purchase_cost", "Purchase Cost", "Currency", SALES_MODULE, permlevel=1,
			insert_after="a3_branch", description="Used for margin-scheme GST on resale"),

		_field("a3_warranty_section", "Warranty State", "Section Break", "A3 Retail Warranty",
			insert_after="a3_purchase_cost"),
		_field("a3_brand_warranty_expiry", "Brand Warranty Expiry", "Date", "A3 Retail Warranty",
			insert_after="a3_warranty_section", read_only=1),
		_field("a3_ew_registration", "Extended Warranty", "Link", "A3 Retail Warranty",
			options="Warranty Registration", insert_after="a3_brand_warranty_expiry", read_only=1),
		_field("a3_ew_expiry", "EW Expiry", "Date", "A3 Retail Warranty",
			insert_after="a3_ew_registration", read_only=1),
		_field("a3_warranty_col_break", "", "Column Break", "A3 Retail Warranty",
			insert_after="a3_ew_expiry"),
		_field("a3_warranty_state", "Warranty State", "Select", "A3 Retail Warranty",
			options=WARRANTY_STATES, default="Not Sold", insert_after="a3_warranty_col_break",
			read_only=1, in_standard_filter=1),
		_field("a3_service_count", "Service Count", "Int", SERVICE_MODULE,
			insert_after="a3_warranty_state", read_only=1),
		_field("a3_last_service_date", "Last Service Date", "Date", SERVICE_MODULE,
			insert_after="a3_service_count", read_only=1),
	],
	"Customer": [
		_field("a3_contact_section", "A3 Retail — Contact & CRM", "Section Break", SALES_MODULE,
			insert_after="customer_type"),
		_field("a3_mobile_no", "Mobile Number", "Data", SALES_MODULE, insert_after="a3_contact_section",
			unique=1, search_index=1, in_standard_filter=1, options="Phone",
			description="Primary search key at the counter and on the Reception Desk"),
		_field("a3_alternate_mobile", "Alternate Mobile", "Data", SALES_MODULE,
			insert_after="a3_mobile_no", options="Phone"),
		_field("a3_whatsapp_no", "WhatsApp Number", "Data", SALES_MODULE,
			insert_after="a3_alternate_mobile", options="Phone"),
		_field("a3_dob", "Date of Birth", "Date", SALES_MODULE, insert_after="a3_whatsapp_no"),
		_field("a3_source_branch", "Registered Branch", "Link", SALES_MODULE, options="Branch",
			insert_after="a3_dob"),
		_field("a3_crm_col_break", "", "Column Break", SALES_MODULE, insert_after="a3_source_branch"),
		_field("a3_customer_since", "Customer Since", "Date", SALES_MODULE,
			insert_after="a3_crm_col_break", read_only=1),
		_field("a3_lifetime_value", "Lifetime Value", "Currency", SALES_MODULE,
			insert_after="a3_customer_since", read_only=1),
		_field("a3_device_count", "Devices Owned", "Int", SALES_MODULE,
			insert_after="a3_lifetime_value", read_only=1),
		_field("a3_last_purchase_date", "Last Purchase", "Date", SALES_MODULE,
			insert_after="a3_device_count", read_only=1),
		_field("a3_last_service_date", "Last Service", "Date", SERVICE_MODULE,
			insert_after="a3_last_purchase_date", read_only=1),

		_field("a3_consent_section", "Consent & KYC", "Section Break", SALES_MODULE,
			insert_after="a3_last_service_date", collapsible=1),
		_field("a3_marketing_optin", "Marketing Opt-in", "Check", SALES_MODULE, default="1",
			insert_after="a3_consent_section",
			description="Required before any Marketing-category WhatsApp template is sent"),
		_field("a3_dnc", "Do Not Call", "Check", SALES_MODULE, insert_after="a3_marketing_optin",
			description="Excludes the customer from telecalling lists"),
		_field("a3_kyc_col_break", "", "Column Break", SALES_MODULE, insert_after="a3_dnc"),
		_field("a3_kyc_pan", "PAN", "Data", SALES_MODULE, insert_after="a3_kyc_col_break", length=10),
		# Never store a full Aadhaar number.
		_field("a3_kyc_aadhaar_last4", "Aadhaar (last 4)", "Data", SALES_MODULE,
			insert_after="a3_kyc_pan", length=4),
	],
	"Supplier": [
		_field("a3_section", "A3 Retail", "Section Break", "A3 Retail Operations",
			insert_after="supplier_group"),
		_field("a3_supplier_category", "Category", "Select", "A3 Retail Operations",
			options="\n" + SUPPLIER_CATEGORIES, insert_after="a3_section", in_standard_filter=1),
		_field("a3_is_rcm_applicable", "RCM Applicable", "Check", "A3 Retail Operations",
			insert_after="a3_supplier_category",
			description="Drives the reverse-charge purchase tax template"),
		_field("a3_supplier_col_break", "", "Column Break", "A3 Retail Operations",
			insert_after="a3_is_rcm_applicable"),
		_field("a3_credit_days", "Credit Days", "Int", "A3 Retail Operations",
			insert_after="a3_supplier_col_break"),
		_field("a3_warranty_return_allowed", "Accepts Warranty Returns", "Check", "A3 Retail Operations",
			insert_after="a3_credit_days"),
	],
}


# Step 5 — margin scheme on invoice lines (scope 11.2, Rule 32(5)).
MARGIN_SCHEME_FIELDS = {
	"Sales Invoice Item": [
		_field("a3_is_margin_scheme", "Margin Scheme", "Check", SALES_MODULE,
			insert_after="item_code", fetch_from="item_code.a3_is_margin_scheme",
			read_only=1, print_hide=1),
		_field("a3_purchase_cost", "Purchase Cost", "Currency", SALES_MODULE,
			insert_after="a3_is_margin_scheme", depends_on="eval:doc.a3_is_margin_scheme",
			permlevel=1, print_hide=1),
		_field("a3_margin_value", "Margin Value", "Currency", SALES_MODULE,
			insert_after="a3_purchase_cost", depends_on="eval:doc.a3_is_margin_scheme",
			read_only=1, permlevel=1, print_hide=1,
			description="Taxable value under Rule 32(5)"),
	],
	"POS Invoice Item": [
		_field("a3_is_margin_scheme", "Margin Scheme", "Check", SALES_MODULE,
			insert_after="item_code", fetch_from="item_code.a3_is_margin_scheme",
			read_only=1, print_hide=1),
		_field("a3_purchase_cost", "Purchase Cost", "Currency", SALES_MODULE,
			insert_after="a3_is_margin_scheme", permlevel=1, print_hide=1),
		_field("a3_margin_value", "Margin Value", "Currency", SALES_MODULE,
			insert_after="a3_purchase_cost", read_only=1, permlevel=1, print_hide=1),
	],
}



# Step 8 — service documents link back to their job card (scope 3.4, ADR-04).
SERVICE_LINK_FIELDS = {
	"Sales Order": [
		_field("a3_service_job_card", "Service Job Card", "Link", SERVICE_MODULE,
			options="Service Job Card", insert_after="order_type", read_only=1, no_copy=1),
	],
	"Sales Invoice": [
		_field("a3_service_job_card", "Service Job Card", "Link", SERVICE_MODULE,
			options="Service Job Card", insert_after="po_no", read_only=1, no_copy=1),
	],
	"Payment Entry": [
		_field("a3_service_job_card", "Service Job Card", "Link", SERVICE_MODULE,
			options="Service Job Card", insert_after="party_name", no_copy=1),
	],
}



# Step 12 — sales flags used by incentives and the attach-rate report (scope 2.5).
SELLING_FIELDS = {
	"Sales Invoice": [
		_field("a3_ew_attached", "EW Plan Attached", "Check", SALES_MODULE,
			insert_after="a3_service_job_card", read_only=1, print_hide=1),
	],
	"POS Invoice": [
		_field("a3_ew_attached", "EW Plan Attached", "Check", SALES_MODULE,
			insert_after="customer", read_only=1, print_hide=1),
	],
}



# Step 15 — invoices paid by EMI point back at their application (scope 4.5).
EMI_FIELDS = {
	"Sales Invoice": [
		_field("a3_emi_application", "EMI Application", "Link", "A3 Retail Finance",
			options="EMI Application", insert_after="a3_ew_attached", no_copy=1),
	],
	"POS Invoice": [
		_field("a3_emi_application", "EMI Application", "Link", "A3 Retail Finance",
			options="EMI Application", insert_after="a3_ew_attached", no_copy=1),
	],
}



# Step 19 — Delivery Trip is configured, not rebuilt (scope 7.2).
DELIVERY_FIELDS = {
	"Delivery Trip": [
		_field("a3_branch", "Branch", "Link", OPS_MODULE, options="Branch",
			insert_after="company", in_standard_filter=1),
		_field("a3_trip_type", "Trip Type", "Select", OPS_MODULE,
			options="Sales Delivery\nService Pickup\nService Return\nMixed",
			insert_after="a3_branch", default="Sales Delivery"),
		_field("a3_cod_collected", "COD Collected", "Currency", OPS_MODULE,
			insert_after="a3_trip_type"),
		_field("a3_cod_deposited", "COD Deposited", "Check", OPS_MODULE,
			insert_after="a3_cod_collected"),
		_field("a3_deposit_journal_entry", "Deposit Entry", "Link", OPS_MODULE,
			options="Journal Entry", insert_after="a3_cod_deposited", read_only=1),
	],
	"Delivery Stop": [
		_field("a3_job_card", "Service Job Card", "Link", SERVICE_MODULE,
			options="Service Job Card", insert_after="customer"),
		_field("a3_otp", "Delivery OTP", "Data", SERVICE_MODULE, insert_after="a3_job_card",
			read_only=1),
		_field("a3_otp_verified", "OTP Verified", "Check", SERVICE_MODULE, insert_after="a3_otp"),
		_field("a3_signature", "Signature", "Signature", SERVICE_MODULE,
			insert_after="a3_otp_verified"),
		_field("a3_cod_amount", "COD Amount", "Currency", OPS_MODULE, insert_after="a3_signature"),
		_field("a3_delivery_photo", "Delivery Photo", "Attach Image", OPS_MODULE,
			insert_after="a3_cod_amount"),
		_field("a3_failure_reason", "Failure Reason", "Select", OPS_MODULE,
			options="\nCustomer Unavailable\nAddress Wrong\nRefused\nPayment Not Ready\nRescheduled",
			insert_after="a3_delivery_photo"),
	],
}



# Step 20 — CRM and helpdesk fields on ERPNext's own doctypes (scope 8.2, 8.3).
CRM_FIELDS = {
	"Lead": [
		_field("a3_branch", "Branch", "Link", SALES_MODULE, options="Branch",
			insert_after="company_name", in_standard_filter=1),
		_field("a3_visit_log", "Visit Log", "Link", SALES_MODULE, options="Branch Visit Log",
			insert_after="a3_branch", read_only=1),
		_field("a3_budget_range", "Budget Range", "Select", SALES_MODULE,
			options="\n< 10K\n10K - 20K\n20K - 35K\n35K - 60K\n> 60K\nNot Disclosed",
			insert_after="a3_visit_log"),
		_field("a3_emi_required", "EMI Required", "Check", SALES_MODULE,
			insert_after="a3_budget_range"),
		_field("a3_exchange_device", "Exchange Device", "Data", SALES_MODULE,
			insert_after="a3_emi_required"),
		_field("a3_preferred_contact", "Preferred Contact", "Select", SALES_MODULE,
			options="Call\nWhatsApp\nSMS", insert_after="a3_exchange_device"),
	],
	"Opportunity": [
		_field("a3_branch", "Branch", "Link", SALES_MODULE, options="Branch",
			insert_after="company", in_standard_filter=1),
		_field("a3_competitor", "Competitor", "Data", SALES_MODULE, insert_after="a3_branch"),
		_field("a3_emi_application", "EMI Application", "Link", "A3 Retail Finance",
			options="EMI Application", insert_after="a3_competitor"),
	],
	"Issue": [
		_field("a3_branch", "Branch", "Link", OPS_MODULE, options="Branch",
			insert_after="customer", in_standard_filter=1),
		_field("a3_complaint_category", "Complaint Category", "Select", OPS_MODULE,
			options=("\nService Delay\nRepair Quality\nProduct Defect\nBilling / Invoice\n"
				"Refund\nEMI / Finance\nDelivery Delay\nStaff Behaviour\nWarranty Denial\n"
				"Price Dispute\nData Loss\nMissing Accessory\nOther"),
			insert_after="a3_branch", in_standard_filter=1),
		_field("a3_severity", "Severity", "Select", OPS_MODULE,
			options="Low\nMedium\nHigh\nCritical (Escalated / Social Media / Consumer Court)",
			insert_after="a3_complaint_category", default="Medium"),
		_field("a3_job_card", "Service Job Card", "Link", SERVICE_MODULE,
			options="Service Job Card", insert_after="a3_severity"),
		_field("a3_sales_invoice", "Sales Invoice", "Link", SALES_MODULE, options="Sales Invoice",
			insert_after="a3_job_card"),
		_field("a3_imei", "IMEI", "Data", SALES_MODULE, insert_after="a3_sales_invoice"),
		_field("a3_channel", "Channel", "Select", OPS_MODULE,
			options="\nPhone\nWhatsApp\nEmail\nWalk-in\nWebsite\nGoogle Review\nSocial Media",
			insert_after="a3_imei"),
		_field("a3_escalation_level", "Escalation Level", "Select", OPS_MODULE,
			options=("L0 - Agent\nL1 - Service Manager\nL2 - Branch Manager\n"
				"L3 - Head Office\nL4 - Director"),
			insert_after="a3_channel", default="L0 - Agent"),
		_field("a3_root_cause", "Root Cause", "Select", OPS_MODULE,
			options=("\nProcess Gap\nStaff Error\nTechnical Failure\nParts Unavailable\n"
				"Vendor Issue\nCustomer Expectation\nNo Fault Found"),
			insert_after="a3_escalation_level"),
		_field("a3_compensation_type", "Compensation", "Select", OPS_MODULE,
			options=("None\nDiscount\nFree Service\nFree Accessory\nRefund\nReplacement\n"
				"Extended Warranty"),
			insert_after="a3_root_cause", default="None"),
		_field("a3_compensation_value", "Compensation Value", "Currency", OPS_MODULE,
			insert_after="a3_compensation_type"),
		_field("a3_resolution_summary", "Resolution Summary", "Text Editor", OPS_MODULE,
			insert_after="a3_compensation_value"),
		_field("a3_csat_score", "CSAT", "Rating", OPS_MODULE, insert_after="a3_resolution_summary"),
	],
}


# Step 23 — HR, incentives and asset custody (scope 10.1–10.3).
HR_MODULE = "A3 Retail Operations"

HR_FIELDS = {
	"Employee": [
		_field("a3_hr_section", "Retail Profile", "Section Break", HR_MODULE,
			insert_after="branch", collapsible=1),
		_field("a3_staff_category", "Staff Category", "Select", HR_MODULE,
			options=("\nSales\nService\nCashier\nStore\nTelecalling\nDelivery\n"
				"Branch Management\nHead Office"),
			insert_after="a3_hr_section", in_standard_filter=1),
		_field("a3_shift_pattern", "Shift Pattern", "Select", HR_MODULE,
			options="\nGeneral\nMorning\nEvening\nSplit\nRotational",
			insert_after="a3_staff_category"),
		_field("a3_is_incentive_eligible", "Eligible for Incentive", "Check", HR_MODULE,
			default="1", insert_after="a3_shift_pattern"),
		_field("a3_hr_col_break", "", "Column Break", HR_MODULE,
			insert_after="a3_is_incentive_eligible"),
		_field("a3_technician_grade", "Technician Grade", "Select", HR_MODULE,
			options="\nL1\nL2\nL3\nSenior", insert_after="a3_hr_col_break"),
		_field("a3_can_handle_l3", "Certified for L3 Repairs", "Check", HR_MODULE,
			insert_after="a3_technician_grade"),
		_field("a3_geofence_exempt", "Exempt from Geofence", "Check", HR_MODULE,
			insert_after="a3_can_handle_l3",
			description="Field staff who legitimately check in away from the branch."),
	],
	"Employee Checkin": [
		_field("a3_branch", "Branch", "Link", HR_MODULE, options="Branch",
			insert_after="employee_name", read_only=1, in_standard_filter=1),
		_field("a3_distance_metres", "Distance from Branch (m)", "Int", HR_MODULE,
			insert_after="a3_branch", read_only=1),
		_field("a3_geofence_status", "Geofence", "Select", HR_MODULE,
			options="\nInside\nOutside\nNot Checked", insert_after="a3_distance_metres",
			read_only=1),
	],
	"Attendance": [
		_field("a3_branch", "Branch", "Link", HR_MODULE, options="Branch",
			insert_after="department", read_only=1, in_standard_filter=1),
	],
	"Asset": [
		_field("a3_custody_section", "Custody", "Section Break", HR_MODULE,
			insert_after="asset_category"),
		_field("a3_branch", "Branch", "Link", HR_MODULE, options="Branch",
			insert_after="a3_custody_section", in_standard_filter=1),
		_field("a3_assigned_employee", "Assigned Employee", "Link", HR_MODULE, options="Employee",
			insert_after="a3_branch", read_only=1,
			description="Maintained by Asset Movement; do not edit by hand."),
		_field("a3_custody_since", "In Custody Since", "Date", HR_MODULE,
			insert_after="a3_assigned_employee", read_only=1),
		_field("a3_custody_col_break", "", "Column Break", HR_MODULE,
			insert_after="a3_custody_since"),
		_field("a3_asset_class", "Asset Class", "Select", HR_MODULE,
			options=("\nService Tool\nTest Instrument\nDisplay Fixture\nIT Equipment\n"
				"Furniture\nVehicle\nSecurity\nOther"),
			insert_after="a3_custody_col_break"),
		_field("a3_asset_condition", "Condition", "Select", HR_MODULE,
			options="New\nGood\nFair\nNeeds Repair\nUnder Repair\nScrapped",
			insert_after="a3_asset_class", default="Good"),
		_field("a3_serial_or_imei", "Serial / IMEI", "Data", HR_MODULE,
			insert_after="a3_asset_condition"),
		_field("a3_maintenance_section", "Maintenance, Insurance & Warranty", "Section Break",
			HR_MODULE, insert_after="a3_serial_or_imei", collapsible=1),
		_field("a3_is_calibration_required", "Calibration Required", "Check", HR_MODULE,
			insert_after="a3_maintenance_section"),
		_field("a3_last_calibration_date", "Last Calibrated On", "Date", HR_MODULE,
			insert_after="a3_is_calibration_required",
			depends_on="eval:doc.a3_is_calibration_required"),
		_field("a3_next_calibration_date", "Next Calibration Due", "Date", HR_MODULE,
			insert_after="a3_last_calibration_date",
			depends_on="eval:doc.a3_is_calibration_required"),
		_field("a3_warranty_expiry", "Asset Warranty Expiry", "Date", HR_MODULE,
			insert_after="a3_next_calibration_date"),
		_field("a3_maintenance_col_break", "", "Column Break", HR_MODULE,
			insert_after="a3_warranty_expiry"),
		_field("a3_insurance_policy_no", "Insurance Policy No", "Data", HR_MODULE,
			insert_after="a3_maintenance_col_break"),
		_field("a3_insurance_expiry", "Insurance Expiry", "Date", HR_MODULE,
			insert_after="a3_insurance_policy_no"),
		_field("a3_purchase_invoice", "Purchase Invoice", "Link", HR_MODULE,
			options="Purchase Invoice", insert_after="a3_insurance_expiry"),
		_field("a3_qr_code", "Asset Tag (QR)", "Attach Image", HR_MODULE,
			insert_after="a3_purchase_invoice"),
	],
	"Asset Movement": [
		_field("a3_branch", "Branch", "Link", HR_MODULE, options="Branch",
			insert_after="company", in_standard_filter=1),
		_field("a3_acknowledged", "Acknowledged by Holder", "Check", HR_MODULE,
			insert_after="reference_name"),
	],
	"Additional Salary": [
		_field("a3_branch", "Branch", "Link", HR_MODULE, options="Branch",
			insert_after="company", read_only=1),
	],
}


ALL_FIELD_GROUPS = (
	BRANCH_BACKREF_FIELDS,
	MASTER_FIELDS,
	MARGIN_SCHEME_FIELDS,
	SERVICE_LINK_FIELDS,
	SELLING_FIELDS,
	EMI_FIELDS,
	DELIVERY_FIELDS,
	CRM_FIELDS,
	HR_FIELDS,
)


def run():
	"""Create every custom field this app owns. Idempotent."""
	for group in ALL_FIELD_GROUPS:
		create_custom_fields(group, ignore_validate=True, update=True)
	_tag_module()
	_add_indexes()


def _add_indexes():
	"""Indexes the counter flows depend on (mobile lookup, IMEI lookup)."""
	for doctype, column in (("Customer", "a3_mobile_no"), ("Serial No", "a3_imei_1")):
		try:
			frappe.db.add_index(doctype, [column])
		except Exception:
			# Index already present, or the column has not been created yet.
			pass


def _tag_module():
	"""Ensure every field we own carries an A3 module so fixtures pick it up."""
	fieldnames = set()
	for group in ALL_FIELD_GROUPS:
		for fields in group.values():
			fieldnames.update(f["fieldname"] for f in fields)

	for name in frappe.get_all(
		"Custom Field",
		filters={"fieldname": ["in", list(fieldnames)], "module": ["in", [None, ""]]},
		pluck="name",
	):
		frappe.db.set_value("Custom Field", name, "module", OPS_MODULE, update_modified=False)
