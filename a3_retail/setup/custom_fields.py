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


ALL_FIELD_GROUPS = (BRANCH_BACKREF_FIELDS, MASTER_FIELDS, MARGIN_SCHEME_FIELDS)


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
