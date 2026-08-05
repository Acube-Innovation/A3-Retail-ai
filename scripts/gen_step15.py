import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

FIN = "A3 Retail Finance"

PARTNER_TYPES = "NBFC\nBank\nFintech / BNPL\nCard EMI"
SUBVENTION_BY = "Merchant\nManufacturer\nCustomer\nShared"
DOC_CATEGORIES = ("Identity (KYC)\nAddress Proof\nIncome Proof\nBanking\nLoan Forms\n"
                  "Device / Sale\nOther")
APPLIES_TO = "All\nSalaried\nSelf Employed\nExisting Customer (Pre-approved)"
EMPLOYMENT = "Salaried\nSelf Employed\nBusiness Owner\nRetired\nStudent"
APP_STATUS = ("Draft\nDocuments Pending\nReady to Submit\nSubmitted to Financier\nUnder Review\n"
              "Approved\nRejected\nDisbursed\nSettled\nCancelled")
REJECTION = ("\nLow CIBIL Score\nInsufficient Income\nDocument Mismatch\nExisting Overdue\n"
             "Address Verification Failed\nCustomer Withdrew\nOther")
FEE_TYPE = "Fixed\nPercentage"
SETTLEMENT_STATUS = "Draft\nReconciled\nVariance - Under Query\nClosed"

print("Step 15 — EMI & consumer finance")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


# ------------------------------------------------------------------ children
DT("Partner Branch Code", FIN, [
	f("branch", "Link", "Branch", "Branch", reqd=1, in_list_view=1),
	f("merchant_id", "Data", "Merchant ID", in_list_view=1),
	f("terminal_id", "Data", "Terminal ID", in_list_view=1),
], istable=1).write()

DT("EMI Document Checklist", FIN, editable([
	f("document_type", "Link", "Document", "EMI Document Type", reqd=1, in_list_view=1),
	f("is_mandatory", "Check", "Mandatory", in_list_view=1),
	f("is_received", "Check", "Received", in_list_view=1),
	f("attachment", "Attach", "Attachment", in_list_view=1),
	f("document_number", "Data", "Document No"),
	f("expiry_date", "Date", "Expiry"),
	f("verified", "Check", "Verified"),
	f("verified_by", "Link", "Verified By", "User", read_only=1),
	f("remarks", "Data", "Remarks"),
]), istable=1).write()

DT("EMI Application Item", FIN, editable([
	f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
	f("qty", "Float", "Qty", default="1", in_list_view=1),
	f("rate", "Currency", "Rate", in_list_view=1),
	f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
	f("serial_no", "Data", "IMEI / Serial", in_list_view=1),
]), istable=1).write()

DT("Financier Settlement Item", FIN, editable([
	f("emi_application", "Link", "EMI Application", "EMI Application", reqd=1, in_list_view=1),
	f("sales_invoice", "Link", "Sales Invoice", "Sales Invoice", read_only=1),
	f("customer", "Link", "Customer", "Customer", read_only=1, in_list_view=1),
	f("invoice_date", "Date", "Invoice Date", read_only=1),
	f("loan_amount", "Currency", "Loan Amount", read_only=1, in_list_view=1),
	f("mdr", "Currency", "MDR", read_only=1),
	f("subvention", "Currency", "Subvention", read_only=1),
	f("gst_on_mdr", "Currency", "GST on MDR", read_only=1),
	f("net_amount", "Currency", "Net", read_only=1, in_list_view=1),
	f("is_received", "Check", "Received", in_list_view=1),
	f("remarks", "Data", "Remarks"),
]), istable=1).write()

# ------------------------------------------------------------------ masters
DT("Finance Partner", FIN, [
	f("partner_name", "Data", "Partner Name", reqd=1, unique=1, in_list_view=1),
	f("partner_type", "Select", "Type", PARTNER_TYPES, reqd=1, in_list_view=1, in_standard_filter=1),
	f("legal_name", "Data", "Legal Name"),
	f("gstin", "Data", "GSTIN", length=15),
	cb(),
	f("merchant_id", "Data", "Merchant / Store ID"),
	f("is_active", "Check", "Active", default="1"),
	f("settlement_tat_days", "Int", "Settlement TAT (days)", default="3"),
	f("branch_merchant_ids", "Table", "Branch Merchant IDs", "Partner Branch Code"),

	sb("commercials_section", "Commercials"),
	f("mode_of_payment", "Link", "Mode of Payment", "Mode of Payment", reqd=1, unique=1),
	f("settlement_account", "Link", "Settlement Receivable Account", "Account", reqd=1),
	f("mdr_expense_account", "Link", "MDR / Subvention Expense Account", "Account", reqd=1),
	cb(),
	f("mdr_percent", "Percent", "MDR %", in_list_view=1),
	f("subvention_borne_by", "Select", "Subvention Borne By", SUBVENTION_BY, default="Merchant"),
	f("tds_applicable", "Check", "TDS Applicable"),
	f("min_ticket_size", "Currency", "Min Ticket"),
	f("max_ticket_size", "Currency", "Max Ticket"),

	sb("documents_section", "Default Documents"),
	f("required_documents", "Table", "Default Documents", "EMI Document Checklist"),

	sb("integration_section", "Integration & Support", collapsible=1),
	f("api_integration_enabled", "Check", "API Enabled"),
	f("api_base_url", "Data", "API Base URL", depends_on="api_integration_enabled"),
	f("api_key", "Password", "API Key", depends_on="api_integration_enabled"),
	cb(),
	f("support_contact", "Data", "Support Contact"),
	f("support_email", "Data", "Support Email", options="Email"),
], autoname="field:partner_name", title_field="partner_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("Accounts Manager", "CRUD"),
               ("EMI Coordinator", "R"), ("Sales Executive", "R")]).write()

DT("EMI Scheme", FIN, [
	f("scheme_name", "Data", "Scheme Name", reqd=1, unique=1, in_list_view=1),
	f("finance_partner", "Link", "Finance Partner", "Finance Partner", reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("scheme_code", "Data", "Partner Scheme Code"),
	f("tenure_months", "Int", "Tenure (Months)", reqd=1, in_list_view=1),
	cb(),
	f("is_no_cost_emi", "Check", "No Cost EMI", in_list_view=1),
	f("interest_rate", "Percent", "Interest Rate (% p.a.)"),
	f("processing_fee", "Currency", "Processing Fee"),
	f("processing_fee_type", "Select", "Fee Type", FEE_TYPE, default="Fixed"),
	f("is_active", "Check", "Active", default="1"),

	sb("terms_section", "Terms"),
	f("down_payment_percent", "Percent", "Down Payment %"),
	f("min_down_payment", "Currency", "Min Down Payment"),
	f("subvention_percent", "Percent", "Merchant Subvention %"),
	cb(),
	f("cashback_amount", "Currency", "Cashback"),
	f("min_invoice_amount", "Currency", "Min Invoice Amount"),
	f("max_invoice_amount", "Currency", "Max Invoice Amount"),

	sb("applicability_section", "Applicability"),
	f("applicable_brands", "Table MultiSelect", "Brands", "EMI Scheme Brand"),
	f("applicable_item_groups", "Table MultiSelect", "Item Groups", "EMI Scheme Item Group"),
	cb(),
	f("valid_from", "Date", "Valid From"),
	f("valid_upto", "Date", "Valid Upto"),
	f("applicable_branches", "Table", "Branches", "Offer Branch"),
], autoname="field:scheme_name", title_field="scheme_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("EMI Coordinator", "CRU"),
               ("Sales Executive", "R"), ("Branch Manager", "R"), ("Accounts Manager", "R")]).write()

DT("EMI Scheme Brand", FIN, [f("brand", "Link", "Brand", "Brand", reqd=1, in_list_view=1)],
   istable=1).write()
DT("EMI Scheme Item Group", FIN,
   [f("item_group", "Link", "Item Group", "Item Group", reqd=1, in_list_view=1)], istable=1).write()

DT("EMI Document Type", FIN, [
	f("document_name", "Data", "Document Name", reqd=1, unique=1, in_list_view=1),
	f("category", "Select", "Category", DOC_CATEGORIES, reqd=1, in_list_view=1, in_standard_filter=1),
	f("applies_to", "Select", "Applies To", APPLIES_TO, default="All", in_list_view=1),
	cb(),
	f("is_mandatory_default", "Check", "Mandatory by Default", in_list_view=1),
	f("requires_original_verification", "Check", "Requires Original Verification"),
	f("requires_expiry", "Check", "Has Expiry"),
	f("sample_attachment", "Attach", "Sample"),
	f("instructions", "Small Text", "Instructions for Counter Staff"),
], autoname="field:document_name", title_field="document_name",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("EMI Coordinator", "CRU"),
               ("Sales Executive", "R")]).write()

# -------------------------------------------------------------- application
app_fields = [
	f("naming_series", "Select", "Series", "EMI-.YY.-.#####", hidden=1, default="EMI-.YY.-.#####"),
	f("application_date", "Date", "Date", reqd=1, in_list_view=1),
	f("status", "Select", "Status", APP_STATUS, default="Draft", in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("company", "Link", "Company", "Company", read_only=1),

	sb("customer_section", "Customer"),
	f("customer", "Link", "Customer", "Customer", reqd=1, in_list_view=1),
	f("customer_name", "Data", "Customer Name", fetch_from="customer.customer_name", read_only=1),
	f("customer_mobile", "Data", "Mobile", fetch_from="customer.a3_mobile_no", read_only=1),
	f("customer_email", "Data", "Email", fetch_from="customer.email_id", options="Email"),
	f("employment_type", "Select", "Employment Type", EMPLOYMENT, reqd=1),
	cb(),
	f("monthly_income", "Currency", "Monthly Income"),
	f("pan_number", "Data", "PAN", reqd=1, length=10),
	f("aadhaar_last4", "Data", "Aadhaar (last 4)", reqd=1, length=4),
	f("date_of_birth", "Date", "Date of Birth"),
	f("existing_customer_of_partner", "Check", "Pre-approved with Partner"),
	f("existing_loan_account", "Data", "Existing Loan A/c"),

	sb("sale_section", "Sale Details"),
	f("items", "Table", "Items", "EMI Application Item", allow_on_submit=1),
	f("invoice_total", "Currency", "Invoice Total", reqd=1, allow_on_submit=1),

	sb("finance_section", "Finance"),
	f("finance_partner", "Link", "Finance Partner", "Finance Partner", reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("emi_scheme", "Link", "EMI Scheme", "EMI Scheme", reqd=1),
	f("tenure_months", "Int", "Tenure", read_only=1),
	f("down_payment", "Currency", "Down Payment", reqd=1),
	f("loan_amount", "Currency", "Loan Amount", read_only=1, in_list_view=1, allow_on_submit=1),
	cb(),
	f("processing_fee", "Currency", "Processing Fee", read_only=1, allow_on_submit=1),
	f("emi_amount", "Currency", "Monthly EMI", read_only=1, allow_on_submit=1),
	f("first_emi_date", "Date", "First EMI Date", allow_on_submit=1),
	# Cost fields are masked from branch users (scope 13.5).
	f("merchant_subvention_cost", "Currency", "Subvention Cost (Merchant)", read_only=1, permlevel=1,
	  allow_on_submit=1),
	f("mdr_amount", "Currency", "Expected MDR", read_only=1, permlevel=1, allow_on_submit=1),
	f("net_realisable", "Currency", "Net Realisable", read_only=1, permlevel=1, allow_on_submit=1),

	sb("documents_section", "Documents"),
	f("documents", "Table", "Document Checklist", "EMI Document Checklist", allow_on_submit=1),
	f("all_documents_received", "Check", "Documents Complete", read_only=1, allow_on_submit=1),
	cb(),
	f("documents_verified_by", "Link", "Verified By", "Employee", allow_on_submit=1),

	sb("response_section", "Financier Response"),
	f("submitted_on", "Datetime", "Submitted On", allow_on_submit=1),
	f("partner_application_no", "Data", "Partner Application No", allow_on_submit=1),
	f("approval_date", "Date", "Approval Date", allow_on_submit=1),
	f("approved_loan_amount", "Currency", "Approved Amount", allow_on_submit=1),
	f("loan_account_number", "Data", "Loan Account No", allow_on_submit=1),
	cb(),
	f("rejection_reason", "Select", "Rejection Reason", REJECTION, allow_on_submit=1),
	f("rejection_remarks", "Small Text", "Remarks", allow_on_submit=1),
	f("cibil_score", "Int", "CIBIL Score", allow_on_submit=1),

	sb("linkage_section", "Linkage & Settlement"),
	f("sales_order", "Link", "Sales Order", "Sales Order", allow_on_submit=1),
	f("sales_invoice", "Link", "Sales Invoice", "Sales Invoice", allow_on_submit=1),
	f("disbursement_date", "Date", "Disbursement Date", allow_on_submit=1),
	cb(),
	f("settlement", "Link", "Financier Settlement", "Financier Settlement", read_only=1,
	  allow_on_submit=1),
	f("amount_received", "Currency", "Amount Received", read_only=1, allow_on_submit=1),
	f("sales_person", "Link", "Sales Person", "Sales Person"),
	f("coordinator", "Link", "EMI Coordinator", "Employee"),
	f("amended_from", "Link", "Amended From", "EMI Application", read_only=1, no_copy=1, print_hide=1),
]

DT("EMI Application", FIN, app_fields, autoname="naming_series:", title_field="customer_name",
   search_fields="customer_name,partner_application_no,status", is_submittable=1, track_changes=1,
   sort_field="application_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Branch Manager", "CRUDS"), ("EMI Coordinator", "CRUDS"),
               ("Sales Executive", "CRU"), ("Reception Executive", "R"), ("Accounts Manager", "R"),
               ("A3 Retail Admin", "RU@1"), ("Branch Manager", "RU@1"),
               ("Accounts Manager", "R@1")]).write(controller=None)

# --------------------------------------------------------------- settlement
DT("Financier Settlement", FIN, [
	f("naming_series", "Select", "Series", "FS-.YY.-.####", hidden=1, default="FS-.YY.-.####"),
	f("finance_partner", "Link", "Finance Partner", "Finance Partner", reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("from_date", "Date", "From Date", reqd=1, in_list_view=1),
	f("to_date", "Date", "To Date", reqd=1, in_list_view=1),
	cb(),
	f("company", "Link", "Company", "Company", read_only=1),
	f("status", "Select", "Status", SETTLEMENT_STATUS, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	f("bank_account", "Link", "Bank Account", "Account", reqd=1),
	f("utr_reference", "Data", "Bank UTR"),

	sb("applications_section", "Applications"),
	f("applications", "Table", "Applications", "Financier Settlement Item", allow_on_submit=1),

	sb("totals_section", "Reconciliation"),
	f("gross_amount", "Currency", "Gross (Loan Amounts)", read_only=1, allow_on_submit=1),
	f("mdr_amount", "Currency", "MDR", read_only=1, allow_on_submit=1),
	f("subvention_amount", "Currency", "Subvention", read_only=1, allow_on_submit=1),
	f("gst_on_mdr", "Currency", "GST on MDR", read_only=1, allow_on_submit=1),
	cb(),
	f("tds_amount", "Currency", "TDS", allow_on_submit=1),
	f("other_deductions", "Currency", "Other Deductions", allow_on_submit=1),
	f("net_expected", "Currency", "Net Expected", read_only=1, in_list_view=1, allow_on_submit=1),
	# Not reqd: the settlement is drafted from the pending applications before
	# the bank credit lands. Enforced in before_submit instead.
	f("net_received", "Currency", "Net Received", allow_on_submit=1),
	f("variance", "Currency", "Variance", read_only=1, bold=1, allow_on_submit=1),

	sb("posting_section", "Postings"),
	f("payment_entry", "Link", "Payment Entry", "Payment Entry", read_only=1, allow_on_submit=1),
	cb(),
	f("journal_entry", "Link", "Journal Entry", "Journal Entry", read_only=1, allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Financier Settlement", read_only=1, no_copy=1,
	  print_hide=1),
], autoname="naming_series:", title_field="finance_partner", is_submittable=1, track_changes=1,
   sort_field="from_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Accounts Manager", "CRUDS"), ("EMI Coordinator", "R")]).write(controller=None)
