import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SVC = "A3 Retail Service"

STATUSES = "\n".join([
    "Draft", "Open", "Under Diagnosis", "Estimate Pending", "Estimate Sent", "Estimate Approved",
    "Estimate Rejected", "Awaiting Parts", "In Progress", "On Hold", "Repair Completed",
    "QC Failed", "QC Passed", "Not Repairable", "Ready for Delivery", "Delivered", "Closed", "Cancelled",
])
DEVICE_TYPES = "Mobile\nTablet\nSmartwatch\nEarbuds\nOther"
LEAD_SOURCES = "Walk-in\nPhone Call\nWhatsApp\nWebsite\nReferral\nRepeat Customer\nCorporate AMC"
WARRANTY_TYPES = ("Brand Warranty\nExtended Warranty\nScreen Protection Plan\nInsurance Claim\n"
                  "Out of Warranty\nGoodwill/Free")
REPAIR_CATEGORIES = ("Software\nHardware - Component\nHardware - Board Level\nPhysical Damage\n"
                     "Liquid Damage\nBattery\nDisplay\nAccessory")
PRIORITIES = "Low\nNormal\nHigh\nUrgent (Same Day)"
ROOT_CAUSES = ("\nManufacturing Defect\nUser Damage\nLiquid Ingress\nWear & Tear\n"
               "Software Corruption\nThird-party Repair\nNo Fault Found")
ESTIMATE_STATUS = "Not Required\nPending\nSent\nApproved\nRejected\nRevision Requested"
PAYMENT_STATUS = "Unpaid\nPartly Paid (Advance)\nPaid\nWarranty - No Charge"
DELAY_REASONS = ("\nAwaiting Parts\nAwaiting Customer Approval\nAwaiting Payment\n"
                 "Technician Unavailable\nComplex Repair\nVendor/OEM Delay\nCustomer Not Reachable")
ESCALATION = "None\nL1 - Service Manager\nL2 - Branch Manager\nL3 - Head Office"
DELIVERY_MODES = "Counter Pickup\nHome Delivery\nCourier"
PART_STATUS = ("Required\nReserved\nIssued\nAwaiting Purchase\nAwaiting Transfer\nReceived\nReturned")
ACCESSORIES = ("Charger\nCable\nEarphone\nBox\nSIM Card\nSIM Tray\nMemory Card\nBack Cover\n"
               "Screen Guard\nBill Copy")

print("Step 7 — Service Job Card")


def editable_after_submit(rows):
	"""Mark every field in a child table as editable after submit.

	Frappe validates child fields individually: flagging only the parent table
	still raises UpdateAfterSubmitError when a row value changes.
	"""
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows

# ---------------------------------------------------------------- child tables
DT("Job Card Part", SVC, editable_after_submit([
    f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
    f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
    f("description", "Small Text", "Description"),
    f("qty", "Float", "Qty", default="1", reqd=1, in_list_view=1),
    f("uom", "Link", "UOM", "UOM", fetch_from="item_code.stock_uom", read_only=1),
    f("warehouse", "Link", "Warehouse", "Warehouse"),
    f("serial_no", "Small Text", "Serial No"),
    f("available_qty", "Float", "Available", read_only=1, in_list_view=1,
      description="Live from Bin at the service warehouse"),
    f("is_customer_provided", "Check", "Customer Provided"),
    f("rate", "Currency", "Rate", in_list_view=1),
    f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
    f("valuation_rate", "Currency", "Cost", permlevel=1, read_only=1),
    f("part_status", "Select", "Status", PART_STATUS, default="Required", in_list_view=1),
    f("is_warranty_covered", "Check", "Warranty Covered"),
    f("old_part_returned", "Check", "Defective Part Collected"),
    f("material_request", "Link", "Material Request", "Material Request", read_only=1),
    f("stock_request", "Link", "Stock Request", "Stock Request", read_only=1),
    f("stock_entry", "Link", "Stock Entry", "Stock Entry", read_only=1),
    f("oem_return", "Link", "OEM Return", "OEM Warranty Return", read_only=1),
]), istable=1).write()

DT("Job Card Labour", SVC, editable_after_submit([
    f("service_item", "Link", "Service Item", "Item", reqd=1, in_list_view=1),
    f("description", "Small Text", "Description"),
    f("technician", "Link", "Technician", "Employee", in_list_view=1),
    f("minutes", "Int", "Minutes", in_list_view=1),
    f("qty", "Float", "Qty", default="1"),
    f("rate", "Currency", "Rate", in_list_view=1),
    f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
    f("is_warranty_covered", "Check", "Warranty Covered"),
    f("technician_incentive", "Currency", "Technician Incentive", permlevel=1, read_only=1),
]), istable=1).write()

DT("Job Card Accessory", SVC, editable_after_submit([
    f("accessory", "Select", "Accessory", ACCESSORIES, reqd=1, in_list_view=1),
    f("received", "Check", "Received", in_list_view=1),
    f("condition", "Select", "Condition", "Good\nDamaged\nMissing", default="Good", in_list_view=1),
    f("returned", "Check", "Returned", in_list_view=1),
    f("remarks", "Data", "Remarks"),
]), istable=1).write()

DT("Job Card Status Log", SVC, editable_after_submit([
    f("from_status", "Data", "From", read_only=1, in_list_view=1),
    f("to_status", "Data", "To", read_only=1, in_list_view=1),
    f("changed_by", "Link", "Changed By", "User", read_only=1, in_list_view=1),
    f("changed_on", "Datetime", "Changed On", read_only=1, in_list_view=1),
    f("duration_hours", "Float", "Hours in Previous State", read_only=1, in_list_view=1),
    f("remarks", "Small Text", "Remarks"),
]), istable=1).write()

# ------------------------------------------------------------------- main
fields = [
    f("naming_series", "Select", "Series", "JC-.branch_code.-.YY.-.#####", hidden=1,
      default="JC-.branch_code.-.YY.-.#####"),
    f("status", "Select", "Status", STATUSES, default="Draft", reqd=1, in_list_view=1,
      in_standard_filter=1, no_copy=1),
    cb(),
    f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
    f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
    f("company", "Link", "Company", "Company", read_only=1),

    sb("customer_section", "Customer"),
    f("customer", "Link", "Customer", "Customer", reqd=1, in_standard_filter=1),
    f("customer_name", "Data", "Customer Name", fetch_from="customer.customer_name", read_only=1,
      in_list_view=1),
    f("customer_mobile", "Data", "Mobile", fetch_from="customer.a3_mobile_no", in_list_view=1),
    f("alternate_mobile", "Data", "Alternate Mobile"),
    cb(),
    f("customer_email", "Data", "Email", fetch_from="customer.email_id", options="Email"),
    f("customer_address", "Link", "Address", "Address"),
    f("lead_source", "Select", "Source", LEAD_SOURCES, default="Walk-in"),
    f("is_repeat_customer", "Check", "Repeat Customer", read_only=1),

    sb("device_section", "Device"),
    f("device_type", "Select", "Device Type", DEVICE_TYPES, default="Mobile", reqd=1),
    f("brand", "Link", "Brand", "Brand", reqd=1),
    f("device_model", "Link", "Model", "Device Model", reqd=1, in_list_view=1),
    f("imei_1", "Data", "IMEI 1", in_list_view=1, in_standard_filter=1, length=20),
    f("imei_2", "Data", "IMEI 2", length=20),
    f("imei_override", "Check", "Override IMEI Check"),
    cb(),
    f("serial_no", "Link", "Serial No (sold by us)", "Serial No", read_only=1),
    f("sold_by_us", "Check", "Purchased From Us", read_only=1),
    f("purchase_invoice_ref", "Link", "Original Invoice", "Sales Invoice", read_only=1),
    f("device_purchase_date", "Date", "Purchase Date"),

    sb("warranty_section", "Warranty"),
    f("warranty_type", "Select", "Warranty Type", WARRANTY_TYPES, default="Out of Warranty", reqd=1,
      in_standard_filter=1),
    f("warranty_expiry_date", "Date", "Warranty Expiry", read_only=1),
    cb(),
    f("warranty_registration", "Link", "EW Registration", "Warranty Registration"),
    f("is_chargeable", "Check", "Chargeable to Customer", default="1"),

    sb("intake_section", "Intake"),
    f("received_on", "Datetime", "Received On", reqd=1),
    f("received_by", "Link", "Received By", "Employee"),
    f("complaint_description", "Small Text", "Customer Complaint", reqd=1),
    f("reported_issues", "Table MultiSelect", "Reported Issues", "Job Card Reported Issue"),
    f("repair_category", "Select", "Repair Category", REPAIR_CATEGORIES, in_standard_filter=1),
    cb(),
    f("priority", "Select", "Priority", PRIORITIES, default="Normal"),
    f("physical_condition", "Small Text", "Physical Condition Notes"),
    f("device_password", "Password", "Device Lock Code / Pattern"),
    f("data_backup_required", "Check", "Data Backup Required"),
    f("data_loss_consent", "Check", "Customer Consented to Data Loss"),
    f("estimated_delivery_date", "Datetime", "Promised Delivery"),

    sb("condition_section", "Condition & Evidence", collapsible=1),
    f("device_condition_checklist", "Table", "Accessory / Condition Checklist", "Job Card Accessory"),
    f("device_photo_1", "Attach Image", "Photo 1"),
    f("device_photo_2", "Attach Image", "Photo 2"),
    cb(),
    f("device_photo_3", "Attach Image", "Photo 3"),
    f("device_photo_4", "Attach Image", "Photo 4"),
    f("customer_signature", "Signature", "Customer Signature"),

    sb("diagnosis_section", "Diagnosis & Assignment"),
    f("assigned_technician", "Link", "Technician", "Employee", in_standard_filter=1, in_list_view=1),
    f("assigned_on", "Datetime", "Assigned On", read_only=1),
    f("diagnosed_on", "Datetime", "Diagnosed On", read_only=1),
    f("root_cause", "Select", "Root Cause", ROOT_CAUSES),
    cb(),
    f("requires_estimate", "Check", "Requires Customer Estimate", default="1"),
    f("service_estimate", "Link", "Estimate", "Service Estimate", read_only=1),
    f("estimate_status", "Select", "Estimate Status", ESTIMATE_STATUS, default="Not Required",
      read_only=1),
    f("diagnosis_notes", "Text Editor", "Diagnosis"),

    sb("parts_section", "Parts & Labour"),
    f("parts", "Table", "Parts Used", "Job Card Part"),
    f("labour", "Table", "Labour", "Job Card Labour"),

    sb("totals_section", "Totals"),
    f("parts_total", "Currency", "Parts Total", read_only=1),
    f("labour_total", "Currency", "Labour Total", read_only=1),
    f("total_before_discount", "Currency", "Total", read_only=1),
    f("discount_amount", "Currency", "Discount"),
    f("discount_reason", "Small Text", "Discount Reason", depends_on="eval:doc.discount_amount>0"),
    cb(),
    f("net_total", "Currency", "Net Total", read_only=1),
    f("tax_template", "Link", "Tax Template", "Sales Taxes and Charges Template"),
    f("tax_amount", "Currency", "GST", read_only=1),
    f("grand_total", "Currency", "Grand Total", read_only=1, in_list_view=1),
    f("warranty_borne_amount", "Currency", "Amount Borne (Warranty)", read_only=1),
    f("customer_payable", "Currency", "Customer Payable", read_only=1, bold=1),

    sb("payment_section", "Payments"),
    f("advance_amount", "Currency", "Advance Received", read_only=1),
    f("advance_payment_entry", "Link", "Advance Payment Entry", "Payment Entry", read_only=1),
    f("sales_order", "Link", "Sales Order", "Sales Order", read_only=1),
    cb(),
    f("sales_invoice", "Link", "Sales Invoice", "Sales Invoice", read_only=1),
    f("outstanding_amount", "Currency", "Balance Due", read_only=1),
    f("payment_status", "Select", "Payment Status", PAYMENT_STATUS, default="Unpaid", read_only=1),

    sb("sla_section", "Status & SLA"),
    f("tat_policy", "Link", "TAT Policy", "Service TAT Policy", read_only=1),
    f("sla_due_on", "Datetime", "SLA Due", read_only=1, in_list_view=1),
    f("is_delayed", "Check", "Delayed", read_only=1, in_standard_filter=1),
    f("delay_hours", "Float", "Delay (hrs)", read_only=1),
    f("paused_hours", "Float", "Paused (hrs)", read_only=1,
      description="Time awaiting parts, approval or payment — excluded from the TAT clock"),
    cb(),
    f("delay_reason", "Select", "Delay Reason", DELAY_REASONS),
    f("escalation_level", "Select", "Escalation", ESCALATION, default="None", read_only=1),
    f("hold_reason", "Small Text", "On Hold Reason"),
    f("status_log", "Table", "Status History", "Job Card Status Log", read_only=1),

    sb("delivery_section", "Delivery"),
    f("delivery_mode", "Select", "Delivery Mode", DELIVERY_MODES, default="Counter Pickup"),
    f("ready_on", "Datetime", "Ready On", read_only=1),
    f("delivery_otp", "Data", "Delivery OTP", read_only=1, no_copy=1, hidden=1),
    f("otp_verified", "Check", "OTP Verified", read_only=1),
    f("delivered_on", "Datetime", "Delivered On", read_only=1),
    f("delivered_by", "Link", "Delivered By", "Employee", read_only=1),
    cb(),
    f("receiver_name", "Data", "Received By (Name)"),
    f("receiver_id_proof", "Data", "ID Proof Ref"),
    f("receiver_signature", "Signature", "Receiver Signature"),
    f("accessories_returned", "Check", "Accessories Returned"),
    f("courier_dispatch", "Link", "Courier Dispatch", "Courier Dispatch",
      depends_on="eval:doc.delivery_mode=='Courier'"),
    f("delivery_note", "Link", "Delivery Note", "Delivery Note", read_only=1),

    sb("feedback_section", "Feedback", collapsible=1),
    f("feedback_rating", "Rating", "Feedback"),
    f("feedback_comments", "Small Text", "Feedback Comments"),
    cb(),
    f("customer_feedback", "Link", "Feedback Record", "Customer Feedback", read_only=1),
    f("amended_from", "Link", "Amended From", "Service Job Card", read_only=1, no_copy=1, print_hide=1),
]


# A job card is worked on for days after intake, so almost every operational
# field must stay editable after submit. Intake evidence (IMEI, complaint,
# signature, photos) deliberately stays locked — that is the audit trail.
ALLOW_ON_SUBMIT = {
    "status", "assigned_technician", "assigned_on", "diagnosed_on", "diagnosis_notes",
    "root_cause", "requires_estimate", "service_estimate", "estimate_status",
    "parts", "labour", "parts_total", "labour_total", "total_before_discount",
    "discount_amount", "discount_reason", "net_total", "tax_template", "tax_amount",
    "grand_total", "warranty_borne_amount", "customer_payable",
    "advance_amount", "advance_payment_entry", "sales_order", "sales_invoice",
    "outstanding_amount", "payment_status",
    "tat_policy", "sla_due_on", "is_delayed", "delay_hours", "paused_hours",
    "delay_reason", "escalation_level", "hold_reason", "status_log",
    "delivery_mode", "ready_on", "delivery_otp", "otp_verified", "delivered_on",
    "delivered_by", "receiver_name", "receiver_id_proof", "receiver_signature",
    "accessories_returned", "courier_dispatch", "delivery_note",
    "feedback_rating", "feedback_comments", "customer_feedback",
    "warranty_type", "warranty_registration", "warranty_expiry_date", "is_chargeable",
    "repair_category", "priority", "estimated_delivery_date", "is_repeat_customer",
    "serial_no", "sold_by_us", "purchase_invoice_ref", "device_purchase_date",
    "device_condition_checklist", "physical_condition",
}

for _fd in fields:
    if _fd["fieldname"] in ALLOW_ON_SUBMIT:
        _fd["allow_on_submit"] = 1

DT("Job Card Reported Issue", SVC, editable_after_submit([
    f("issue_type", "Link", "Issue Type", "Service Issue Type", reqd=1, in_list_view=1),
]), istable=1).write()

DT(
    "Service Job Card",
    SVC,
    fields,
    autoname="naming_series:",
    title_field="customer_name",
    search_fields="imei_1,customer_mobile,customer_name,status",
    is_submittable=1,
    track_changes=1,
    sort_field="received_on",
    sort_order="DESC",
    perms_spec=[
        ("System Manager", "CRUDS"),
        ("A3 Retail Admin", "CRUDS"),
        ("Branch Manager", "CRUDS"),
        ("Service Manager", "CRUDS"),
        ("Reception Executive", "CRUS"),
        ("Technician", "RU"),
        ("Sales Executive", "R"),
        ("Store Keeper", "R"),
        ("Accounts Manager", "R"),
        ("Telecaller", "R"),
        # permlevel 1 — cost and incentive fields (scope 13.5)
        ("A3 Retail Admin", "RU@1"),
        ("Branch Manager", "RU@1"),
        ("Accounts Manager", "R@1"),
    ],
).write(controller=None, client=None, test=None)
print("  (controller written separately)")
