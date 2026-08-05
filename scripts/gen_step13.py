import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SALES = "A3 Retail Sales"

OFFER_TYPES = ("Flat Percentage\nFlat Amount\nSpecial Price\nBuy X Get Y\nBundle Price\n"
               "Cashback\nExchange Bonus\nBank/Card Offer\nNo Cost EMI")
APPLY_ON = "Item Code\nItem Group\nBrand\nEntire Catalogue"
BENEFIT = "Discount Percentage\nDiscount Amount\nRate"
CHANNELS = "All\nPOS Only\nOnline Only\nB2B Only"
STATUSES = "Draft\nPending Approval\nScheduled\nActive\nPaused\nExpired\nCancelled"
SEGMENTS = ("All Opted-in\nPurchased Last 12M\nWarranty Expiring\nLapsed 6M+\nCustom Report")

print("Step 13 — seasonal offers")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Offer Item Rule", SALES, editable([
	f("item_code", "Link", "Item", "Item", in_list_view=1),
	f("item_group", "Link", "Item Group", "Item Group", in_list_view=1),
	f("brand", "Link", "Brand", "Brand", in_list_view=1),
	f("uom", "Link", "UOM", "UOM"),
	f("min_qty", "Float", "Min Qty"),
	f("discount_percentage", "Percent", "Discount %", in_list_view=1),
	f("discount_amount", "Currency", "Discount Amount"),
	f("special_rate", "Currency", "Special Rate"),
	f("pricing_rule", "Link", "Pricing Rule", "Pricing Rule", read_only=1, in_list_view=1),
]), istable=1).write()

DT("Offer Branch", SALES, editable([
	f("branch", "Link", "Branch", "Branch", reqd=1, in_list_view=1),
	f("branch_code", "Data", "Code", fetch_from="branch.name", read_only=1),
	f("is_included", "Check", "Included", default="1", in_list_view=1),
]), istable=1).write()

fields = [
	f("campaign_name", "Data", "Campaign Name", reqd=1, in_list_view=1),
	f("naming_series", "Select", "Series", "OFR-.YY.-.####", hidden=1, default="OFR-.YY.-.####"),
	f("offer_type", "Select", "Offer Type", OFFER_TYPES, reqd=1, default="Flat Percentage",
	  in_list_view=1, in_standard_filter=1),
	f("company", "Link", "Company", "Company", reqd=1),
	cb(),
	f("valid_from", "Date", "Valid From", reqd=1, in_list_view=1),
	f("valid_upto", "Date", "Valid Upto", reqd=1, in_list_view=1),
	f("status", "Select", "Status", STATUSES, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),

	sb("applicability_section", "Applicability"),
	f("apply_on", "Select", "Apply On", APPLY_ON, default="Item Code", reqd=1),
	f("items", "Table", "Applicable Items", "Offer Item Rule", allow_on_submit=1),
	f("applicable_branches", "Table", "Branches", "Offer Branch",
	  description="Leave empty to apply at every branch"),
	cb(),
	f("customer_group", "Link", "Customer Group", "Customer Group"),
	f("min_qty", "Float", "Min Qty"),
	f("max_qty", "Float", "Max Qty"),
	f("min_amount", "Currency", "Min Amount"),
	f("max_amount", "Currency", "Max Amount"),
	f("applicable_channel", "Select", "Channel", CHANNELS, default="All"),

	sb("benefit_section", "Benefit"),
	f("rate_or_discount", "Select", "Benefit Basis", BENEFIT, default="Discount Percentage"),
	f("discount_percentage", "Percent", "Discount %"),
	f("discount_amount", "Currency", "Discount Amount"),
	f("special_rate", "Currency", "Special Rate"),
	cb(),
	f("max_discount_amount", "Currency", "Max Discount Cap"),
	f("free_item", "Link", "Free Item", "Item", depends_on="eval:doc.offer_type=='Buy X Get Y'"),
	f("free_qty", "Float", "Free Qty", depends_on="eval:doc.offer_type=='Buy X Get Y'"),
	f("exchange_bonus", "Currency", "Exchange Bonus",
	  depends_on="eval:doc.offer_type=='Exchange Bonus'"),
	f("subvention_percent", "Percent", "Subvention %",
	  depends_on="eval:doc.offer_type=='No Cost EMI'"),

	sb("control_section", "Control"),
	f("budget_cap", "Currency", "Budget Cap", description="Total discount this campaign may give away"),
	f("consumed_amount", "Currency", "Consumed", read_only=1, allow_on_submit=1),
	f("priority", "Int", "Priority", default="1"),
	cb(),
	f("coupon_required", "Check", "Requires Coupon"),
	f("coupon_code", "Link", "Coupon Code", "Coupon Code", depends_on="coupon_required"),
	f("is_cumulative", "Check", "Combine With Other Offers"),
	f("requires_approval", "Check", "Requires HO Approval", default="1"),
	f("approved_by", "Link", "Approved By", "User", read_only=1, allow_on_submit=1),

	sb("marketing_section", "Marketing", collapsible=1),
	f("banner_image", "Attach Image", "Banner"),
	f("description", "Text Editor", "Description"),
	cb(),
	f("whatsapp_template", "Link", "WhatsApp Template", "WhatsApp Template"),
	f("broadcast_segment", "Select", "Target Segment", "\n" + SEGMENTS),
	f("custom_segment_report", "Link", "Segment Report", "Report",
	  depends_on="eval:doc.broadcast_segment=='Custom Report'"),

	sb("output_section", "Generated Pricing Rules"),
	f("generated_rules", "Table", "Generated Rules", "Offer Item Rule", read_only=1,
	  allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Seasonal Offer Campaign", read_only=1, no_copy=1,
	  print_hide=1),
]

DT(
	"Seasonal Offer Campaign",
	SALES,
	fields,
	autoname="naming_series:",
	title_field="campaign_name",
	search_fields="campaign_name,offer_type,status",
	is_submittable=1,
	track_changes=1,
	sort_field="valid_from",
	sort_order="DESC",
	perms_spec=[
		("System Manager", "CRUDS"),
		("A3 Retail Admin", "CRUDS"),
		("Branch Manager", "CR"),
		("Sales Executive", "R"),
		("Reception Executive", "R"),
		("Accounts Manager", "R"),
		("Telecaller", "R"),
	],
).write(controller=None)
