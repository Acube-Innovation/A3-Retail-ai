import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SVC = "A3 Retail Service"
COMM = "A3 Retail Communication"

AVAILABILITY = "In Stock\nOther Branch\nTo Purchase"
APPROVAL_STATUS = "Pending\nSent\nApproved\nRejected\nRevision Requested\nExpired"
CHANNELS = "In Person\nWhatsApp\nPortal\nPhone\nEmail"

print("Step 8 — Service Estimate & portal approval")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Service Estimate Part", SVC, editable([
	f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
	f("qty", "Float", "Qty", default="1", reqd=1, in_list_view=1),
	f("uom", "Link", "UOM", "UOM", fetch_from="item_code.stock_uom", read_only=1),
	f("rate", "Currency", "Rate", in_list_view=1),
	f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
	f("is_optional", "Check", "Optional", in_list_view=1),
	f("is_approved", "Check", "Approved by Customer", default="1"),
	f("availability", "Select", "Availability", AVAILABILITY, default="In Stock"),
	f("expected_days", "Int", "Expected Days"),
]), istable=1).write()

DT("Service Estimate Labour", SVC, editable([
	f("service_item", "Link", "Service Item", "Item", reqd=1, in_list_view=1),
	f("description", "Small Text", "Description"),
	f("minutes", "Int", "Minutes"),
	f("qty", "Float", "Qty", default="1"),
	f("rate", "Currency", "Rate", in_list_view=1),
	f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
	f("is_optional", "Check", "Optional", in_list_view=1),
	f("is_approved", "Check", "Approved by Customer", default="1"),
]), istable=1).write()

fields = [
	f("naming_series", "Select", "Series", "EST-.branch_code.-.YY.-.####", hidden=1,
	  default="EST-.branch_code.-.YY.-.####"),
	f("job_card", "Link", "Job Card", "Service Job Card", reqd=1, in_list_view=1),
	f("estimate_date", "Date", "Date", reqd=1, in_list_view=1),
	f("valid_till", "Date", "Valid Till", reqd=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", read_only=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("customer", "Link", "Customer", "Customer", read_only=1),
	f("customer_name", "Data", "Customer Name", fetch_from="customer.customer_name", read_only=1,
	  in_list_view=1),
	f("customer_mobile", "Data", "Mobile", read_only=1),

	sb("device_section", "Device"),
	f("device_model", "Link", "Model", "Device Model", read_only=1),
	cb(),
	f("imei_1", "Data", "IMEI", read_only=1),

	sb("lines_section", "Estimated Work"),
	f("parts", "Table", "Estimated Parts", "Service Estimate Part", allow_on_submit=1),
	f("labour", "Table", "Estimated Labour", "Service Estimate Labour", allow_on_submit=1),

	sb("totals_section", "Totals"),
	f("parts_total", "Currency", "Parts Total", read_only=1, allow_on_submit=1),
	f("labour_total", "Currency", "Labour Total", read_only=1, allow_on_submit=1),
	f("discount", "Currency", "Discount", allow_on_submit=1),
	cb(),
	f("net_total", "Currency", "Net Total", read_only=1, allow_on_submit=1),
	f("tax_amount", "Currency", "GST", read_only=1, allow_on_submit=1),
	f("grand_total", "Currency", "Grand Total", read_only=1, in_list_view=1, allow_on_submit=1),
	f("expected_tat_hours", "Int", "Expected TAT (hours)"),

	sb("approval_section", "Approval"),
	f("approval_status", "Select", "Approval", APPROVAL_STATUS, default="Pending", read_only=1,
	  in_list_view=1, in_standard_filter=1, allow_on_submit=1),
	f("approval_channel", "Select", "Channel", CHANNELS, allow_on_submit=1),
	f("approved_on", "Datetime", "Approved On", read_only=1, allow_on_submit=1),
	f("approver_name", "Data", "Approved By (Customer)", allow_on_submit=1),
	cb(),
	f("customer_remarks", "Small Text", "Customer Remarks", allow_on_submit=1),
	f("approval_ip", "Data", "Approval IP", read_only=1, allow_on_submit=1),
	f("sales_order", "Link", "Sales Order", "Sales Order", read_only=1, allow_on_submit=1),

	sb("token_section", "Portal Access", collapsible=1),
	f("portal_token_hash", "Data", "Portal Token Hash", read_only=1, hidden=1, allow_on_submit=1,
	  no_copy=1),
	f("portal_url", "Data", "Portal Link", read_only=1, allow_on_submit=1),
	cb(),
	f("revision_of", "Link", "Revision Of", "Service Estimate", read_only=1),
	f("version_no", "Int", "Version", default="1", read_only=1),

	sb("terms_section", "Terms", collapsible=1),
	f("terms_template", "Link", "Terms Template", "Terms and Conditions"),
	f("terms", "Text Editor", "Terms"),
	f("amended_from", "Link", "Amended From", "Service Estimate", read_only=1, no_copy=1, print_hide=1),
]

DT(
	"Service Estimate",
	SVC,
	fields,
	autoname="naming_series:",
	title_field="customer_name",
	search_fields="job_card,customer_name,approval_status",
	is_submittable=1,
	track_changes=1,
	sort_field="estimate_date",
	sort_order="DESC",
	perms_spec=[
		("System Manager", "CRUDS"),
		("A3 Retail Admin", "CRUDS"),
		("Branch Manager", "CRUDS"),
		("Service Manager", "CRUDS"),
		("Technician", "CRU"),
		("Reception Executive", "R"),
		("Sales Executive", "R"),
		("Accounts Manager", "R"),
	],
).write(controller=None)

# Portal OTP store (scope 13.1)
DT("Portal OTP", COMM, [
	f("mobile_no", "Data", "Mobile", reqd=1, in_list_view=1, search_index=1),
	f("otp_hash", "Data", "OTP Hash", read_only=1),
	f("purpose", "Select", "Purpose", "Estimate Approval\nService Tracking\nPayment\nFeedback\nComplaint\nGeneral",
	  default="General", in_list_view=1),
	f("reference_doctype", "Link", "Reference Type", "DocType", read_only=1),
	f("reference_name", "Dynamic Link", "Reference", "reference_doctype", read_only=1),
	cb(),
	f("expires_on", "Datetime", "Expires On", read_only=1, in_list_view=1),
	f("attempts", "Int", "Attempts", read_only=1),
	f("verified", "Check", "Verified", read_only=1, in_list_view=1),
	f("verified_on", "Datetime", "Verified On", read_only=1),
	f("ip_address", "Data", "IP Address", read_only=1),
], perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "R")],
   sort_field="creation", sort_order="DESC").write()
