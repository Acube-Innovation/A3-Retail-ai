import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

WAR = "A3 Retail Warranty"

COVERAGE = ("Extended Warranty\nScreen Protection\nAccidental & Liquid Damage\n"
            "Combo (EW + Screen)\nTheft Protection")
STARTS_FROM = "Date of Purchase\nAfter Brand Warranty Expiry"
REG_TYPES = "Brand Warranty Only\nExtended Warranty\nScreen Protection\nCombo\nAMC"
REG_STATUS = ("Active\nExpiring Soon\nExpired\nFully Claimed\nVoid\nTransferred\nCancelled")
VOID_REASONS = ("\nPhysical Tampering\nThird-party Repair\nLiquid Damage (uncovered)\n"
                "IMEI Mismatch\nPlan Cancelled")
COMPONENTS = ("Display\nBattery\nMotherboard\nCamera\nCharging Port\nSpeaker\nButtons\nBody\n"
              "Software\nWater Damage\nAccidental Damage")
OEM_TYPES = "Defective Part Return\nDOA Device Return\nBulk Warranty Return"
OEM_STATUS = ("Draft\nDispatched\nAcknowledged\nCredit Received\nRejected by OEM\n"
              "Partially Credited")
OEM_ITEM_STATUS = "Pending\nAccepted\nRejected"

print("Step 16 — warranty management")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Warranty Coverage Item", WAR, [
	f("component", "Select", "Component", COMPONENTS, reqd=1, in_list_view=1),
	f("is_covered", "Check", "Covered", default="1", in_list_view=1),
	f("coverage_percent", "Percent", "Coverage %", default="100", in_list_view=1),
	f("remarks", "Data", "Remarks"),
], istable=1).write()

DT("Warranty Claim Log", WAR, editable([
	f("job_card", "Link", "Job Card", "Service Job Card", in_list_view=1),
	f("claim_date", "Date", "Date", in_list_view=1),
	f("amount", "Currency", "Amount", in_list_view=1),
	f("status", "Data", "Status", in_list_view=1),
	f("remarks", "Small Text", "Remarks"),
]), istable=1).write()

DT("OEM Return Item", WAR, editable([
	f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
	f("serial_no", "Data", "Serial / IMEI", in_list_view=1),
	f("qty", "Float", "Qty", default="1", in_list_view=1),
	f("job_card", "Link", "Job Card", "Service Job Card"),
	f("defect_description", "Small Text", "Defect"),
	f("claim_value", "Currency", "Claim Value", in_list_view=1),
	f("oem_status", "Select", "OEM Status", OEM_ITEM_STATUS, default="Pending", in_list_view=1),
	f("credit_received", "Currency", "Credit Received"),
	f("remarks", "Data", "Remarks"),
]), istable=1).write()

DT("Extended Warranty Plan", WAR, [
	f("plan_name", "Data", "Plan Name", reqd=1, unique=1, in_list_view=1),
	f("plan_item", "Link", "Sellable Item", "Item", reqd=1, in_list_view=1),
	f("coverage_type", "Select", "Coverage Type", COVERAGE, reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("duration_months", "Int", "Duration (Months)", reqd=1, in_list_view=1),
	cb(),
	f("starts_from", "Select", "Coverage Starts", STARTS_FROM, default="Date of Purchase"),
	f("waiting_period_days", "Int", "Waiting Period (Days)"),
	f("sale_window_days", "Int", "Must Be Sold Within (days)", default="15"),
	f("is_active", "Check", "Active", default="1"),
	f("is_transferable", "Check", "Transferable"),

	sb("pricing_section", "Pricing & Limits"),
	f("plan_price", "Currency", "Plan Price"),
	f("price_percent_of_device", "Percent", "Price as % of Device"),
	f("min_device_value", "Currency", "Min Device Value"),
	f("max_device_value", "Currency", "Max Device Value"),
	cb(),
	f("max_claims", "Int", "Max Claims Allowed", default="1"),
	f("claim_value_cap_percent", "Percent", "Claim Cap (% of device value)", default="100"),
	f("deductible_amount", "Currency", "Customer Deductible per Claim"),

	sb("eligibility_section", "Eligibility"),
	f("eligible_item_groups", "Table MultiSelect", "Eligible Item Groups", "EMI Scheme Item Group"),
	f("eligible_brands", "Table MultiSelect", "Eligible Brands", "EMI Scheme Brand"),
	cb(),
	f("underwriter", "Link", "Underwriter / Partner", "Supplier"),
	f("technician_incentive", "Currency", "Technician Incentive", permlevel=1),
	f("sales_incentive", "Currency", "Sales Incentive", permlevel=1),

	sb("coverage_section", "Coverage"),
	f("coverage_items", "Table", "Covered Components", "Warranty Coverage Item"),
	f("exclusions", "Text Editor", "Exclusions"),
	f("terms", "Link", "Terms & Conditions", "Terms and Conditions"),
], autoname="field:plan_name", title_field="plan_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("Service Manager", "R"),
               ("Sales Executive", "R"), ("Branch Manager", "R"), ("Reception Executive", "R"),
               ("A3 Retail Admin", "RU@1"), ("Branch Manager", "RU@1")]).write()

reg_fields = [
	f("naming_series", "Select", "Series", "WR-.YY.-.#####", hidden=1, default="WR-.YY.-.#####"),
	f("registration_type", "Select", "Type", REG_TYPES, reqd=1, default="Brand Warranty Only",
	  in_list_view=1, in_standard_filter=1, allow_on_submit=1),
	f("customer", "Link", "Customer", "Customer", reqd=1, in_list_view=1),
	f("customer_mobile", "Data", "Mobile", fetch_from="customer.a3_mobile_no", read_only=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("status", "Select", "Status", REG_STATUS, default="Active", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	f("void_reason", "Select", "Void Reason", VOID_REASONS, allow_on_submit=1),

	sb("device_section", "Device"),
	f("serial_no", "Link", "Serial No (IMEI)", "Serial No", reqd=1, in_list_view=1),
	f("imei_1", "Data", "IMEI 1", read_only=1),
	f("item_code", "Link", "Item", "Item", read_only=1),
	f("item_name", "Data", "Item Name", read_only=1),
	cb(),
	f("brand", "Link", "Brand", "Brand", read_only=1),
	f("device_model", "Link", "Device Model", "Device Model", read_only=1),
	f("device_value", "Currency", "Device Value", read_only=1),
	f("sales_invoice", "Link", "Sales Invoice", "Sales Invoice", reqd=1),
	f("purchase_date", "Date", "Purchase Date", reqd=1),

	sb("brand_warranty_section", "Brand Warranty"),
	f("brand_warranty_months", "Int", "Brand Warranty (Months)"),
	cb(),
	f("brand_warranty_expiry", "Date", "Brand Warranty Expiry", read_only=1, allow_on_submit=1),

	sb("plan_section", "Extended Plan"),
	f("ew_plan", "Link", "Plan", "Extended Warranty Plan", allow_on_submit=1),
	f("plan_item", "Link", "Plan Item", "Item", read_only=1, allow_on_submit=1),
	f("plan_amount", "Currency", "Plan Amount", allow_on_submit=1),
	cb(),
	f("ew_start_date", "Date", "EW Start", read_only=1, allow_on_submit=1),
	f("ew_expiry_date", "Date", "EW Expiry", read_only=1, in_list_view=1, allow_on_submit=1),
	f("certificate_no", "Data", "Certificate No", read_only=1, allow_on_submit=1),
	f("certificate_url", "Data", "Certificate Link", read_only=1, allow_on_submit=1),
	f("certificate_token_hash", "Data", "Certificate Token", read_only=1, hidden=1, no_copy=1,
	  allow_on_submit=1),

	sb("claims_section", "Claims"),
	f("max_claims", "Int", "Max Claims", read_only=1, allow_on_submit=1),
	f("claims_used", "Int", "Claims Used", read_only=1, allow_on_submit=1),
	f("claim_value_used", "Currency", "Claim Value Used", read_only=1, allow_on_submit=1),
	cb(),
	f("claim_value_cap", "Currency", "Claim Cap", read_only=1, allow_on_submit=1),
	f("deductible_amount", "Currency", "Deductible per Claim", read_only=1, allow_on_submit=1),
	f("claims", "Table", "Claim History", "Warranty Claim Log", read_only=1, allow_on_submit=1),

	sb("renewal_section", "Renewal", collapsible=1),
	f("renewal_reminder_sent", "Check", "Reminder Sent", read_only=1, allow_on_submit=1),
	cb(),
	f("renewed_to", "Link", "Renewed To", "Warranty Registration", allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Warranty Registration", read_only=1, no_copy=1,
	  print_hide=1),
]

DT("Warranty Registration", WAR, reg_fields, autoname="naming_series:", title_field="customer",
   search_fields="imei_1,customer,status", is_submittable=1, track_changes=1,
   sort_field="purchase_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Service Manager", "RU"), ("Branch Manager", "R"), ("Sales Executive", "R"),
               ("Reception Executive", "R"), ("Technician", "R"), ("Accounts Manager", "R"),
               ("Telecaller", "R")]).write(controller=None)

DT("OEM Warranty Return", WAR, [
	f("naming_series", "Select", "Series", "OEM-.YY.-.####", hidden=1, default="OEM-.YY.-.####"),
	f("supplier", "Link", "Supplier", "Supplier", reqd=1, in_list_view=1),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("return_type", "Select", "Return Type", OEM_TYPES, default="Defective Part Return",
	  in_list_view=1),
	cb(),
	f("dispatch_date", "Date", "Dispatch Date", allow_on_submit=1),
	f("courier_dispatch", "Link", "Courier Dispatch", "Courier Dispatch", allow_on_submit=1),
	f("docket_no", "Data", "Docket No", allow_on_submit=1),
	f("status", "Select", "Status", OEM_STATUS, default="Draft", in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),

	sb("items_section", "Items"),
	f("items", "Table", "Items", "OEM Return Item", allow_on_submit=1),
	f("total_claim_value", "Currency", "Total Claim Value", read_only=1, in_list_view=1,
	  allow_on_submit=1),

	sb("credit_section", "Credit"),
	f("expected_credit_date", "Date", "Expected Credit Date", allow_on_submit=1),
	f("credit_note_no", "Data", "Credit Note No", allow_on_submit=1),
	f("credit_amount", "Currency", "Credit Amount", allow_on_submit=1),
	cb(),
	f("purchase_invoice_return", "Link", "Debit Note", "Purchase Invoice", allow_on_submit=1),
	f("ageing_days", "Int", "Ageing (days)", read_only=1, allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "OEM Warranty Return", read_only=1, no_copy=1,
	  print_hide=1),
], autoname="naming_series:", title_field="supplier", is_submittable=1, track_changes=1,
   sort_field="dispatch_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Service Manager", "CRUDS"), ("Store Keeper", "CRU"),
               ("Accounts Manager", "R")]).write(controller=None)
