import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SALES = "A3 Retail Sales"
OPS = "A3 Retail Operations"

VISITOR_TYPES = ("New Walk-in\nRepeat Customer\nService Follow-up\nDelivery Pickup\n"
                 "Accompanying Person\nVendor / Other")
PURPOSES = ("New Device Enquiry\nAccessory Purchase\nService / Repair\nService Status Enquiry\n"
            "Device Delivery Pickup\nEMI Enquiry\nWarranty Enquiry\nExchange Enquiry\n"
            "Complaint\nJust Browsing\nBill Payment")
BUDGETS = "< 10K\n10K - 20K\n20K - 35K\n35K - 60K\n> 60K\nNot Disclosed"
OUTCOMES = ("Pending\nConverted - Sale\nConverted - Job Card\nLead Created (Follow-up)\n"
            "Quotation Given\nLost - Price\nLost - Stock Unavailable\nLost - Model Not Available\n"
            "Lost - Went to Competitor\nLost - EMI Rejected\nInformation Only")
REF_TYPES = ("\nSales Invoice\nPOS Invoice\nSales Order\nService Job Card\nQuotation\nLead")
SOURCES = ("\nWalk Past\nGoogle\nInstagram / Facebook\nWhatsApp Offer\nFriend / Referral\n"
           "Newspaper / Pamphlet\nExisting Customer\nOther")

FEEDBACK_REF = "\nSales Invoice\nService Job Card\nIssue\nDelivery"
FEEDBACK_CHANNELS = ("WhatsApp\nSMS Link\nIn-store Tablet\nPhone\nGoogle Review\nEmail")
SENTIMENT = "Promoter\nPassive\nDetractor"

print("Step 20 — footfall, CRM, helpdesk")

DT("Visit Interest", SALES, [
	f("item_group", "Link", "Item Group", "Item Group", in_list_view=1),
	f("brand", "Link", "Brand", "Brand", in_list_view=1),
	f("item_code", "Link", "Item", "Item", in_list_view=1),
	f("remarks", "Data", "Remarks"),
], istable=1).write()

DT("Branch Visit Log", SALES, [
	f("naming_series", "Select", "Series", "FL-.branch_code.-.YY.-.######", hidden=1,
	  default="FL-.branch_code.-.YY.-.######"),
	f("visit_datetime", "Datetime", "Visit Time", reqd=1, in_list_view=1),
	f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	cb(),
	f("visitor_name", "Data", "Visitor Name", reqd=1, in_list_view=1),
	f("mobile_no", "Data", "Mobile", reqd=1, in_list_view=1, length=10),
	f("is_existing_customer", "Check", "Existing Customer", read_only=1),
	f("customer", "Link", "Customer", "Customer", read_only=1),

	sb("visit_section", "Visit"),
	f("visitor_type", "Select", "Visitor Type", VISITOR_TYPES, default="New Walk-in"),
	f("purpose", "Select", "Purpose", PURPOSES, reqd=1, in_list_view=1, in_standard_filter=1),
	f("interested_items", "Table", "Interested In", "Visit Interest"),
	cb(),
	f("budget_range", "Select", "Budget Range", BUDGETS, default="Not Disclosed"),
	f("attended_by", "Link", "Attended By", "Employee", reqd=1, in_standard_filter=1),
	f("time_spent_minutes", "Int", "Time Spent (min)"),
	f("how_did_you_hear", "Select", "Source", SOURCES),

	sb("outcome_section", "Outcome"),
	f("outcome", "Select", "Outcome", OUTCOMES, default="Pending", in_list_view=1,
	  in_standard_filter=1),
	f("reference_type", "Select", "Converted To", REF_TYPES),
	f("reference_name", "Dynamic Link", "Reference", "reference_type"),
	f("sale_value", "Currency", "Sale Value", read_only=1),
	cb(),
	f("lost_reason_detail", "Small Text", "Lost Reason Detail"),
	f("competitor_mentioned", "Data", "Competitor"),
	f("marketing_consent", "Check", "Marketing Consent", default="1"),

	sb("followup_section", "Follow-up"),
	f("follow_up_required", "Check", "Follow-up Required"),
	f("follow_up_date", "Date", "Follow-up On", depends_on="follow_up_required"),
	cb(),
	f("assigned_telecaller", "Link", "Assigned Telecaller", "Employee",
	  depends_on="follow_up_required"),
	f("call_task", "Link", "Call Task", "Call Task", read_only=1),
	f("lead", "Link", "Lead", "Lead", read_only=1),
	f("remarks", "Small Text", "Remarks"),
], autoname="naming_series:", title_field="visitor_name",
   search_fields="mobile_no,visitor_name,purpose", track_changes=1,
   sort_field="visit_datetime", sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Branch Manager", "CRUD"), ("Sales Executive", "CRUD"),
               ("Reception Executive", "CRUD"), ("Service Manager", "R"),
               ("Telecaller", "R")]).write(controller=None)

DT("Customer Feedback", OPS, [
	f("naming_series", "Select", "Series", "FB-.YY.-.#####", hidden=1, default="FB-.YY.-.#####"),
	f("feedback_date", "Date", "Date", reqd=1, in_list_view=1),
	f("customer", "Link", "Customer", "Customer", in_list_view=1),
	f("mobile_no", "Data", "Mobile"),
	cb(),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("channel", "Select", "Channel", FEEDBACK_CHANNELS, default="WhatsApp"),
	f("reference_type", "Select", "Reference", FEEDBACK_REF),
	f("reference_name", "Dynamic Link", "Reference", "reference_type"),

	sb("ratings_section", "Ratings"),
	f("overall_rating", "Rating", "Overall Rating", reqd=1, in_list_view=1),
	f("nps_score", "Int", "NPS (0-10)"),
	f("rating_service_quality", "Rating", "Service Quality"),
	f("rating_turnaround", "Rating", "Turnaround"),
	cb(),
	f("rating_staff", "Rating", "Staff"),
	f("rating_price", "Rating", "Price"),
	f("rating_cleanliness", "Rating", "Cleanliness"),
	f("would_recommend", "Check", "Would Recommend"),

	sb("outcome_section", "Outcome"),
	f("sentiment", "Select", "Sentiment", SENTIMENT, read_only=1, in_list_view=1,
	  in_standard_filter=1),
	f("comments", "Small Text", "Comments"),
	cb(),
	f("requires_follow_up", "Check", "Requires Follow-up", read_only=1),
	f("follow_up_issue", "Link", "Follow-up Issue", "Issue", read_only=1),
	f("attended_employee", "Link", "Attended By", "Employee"),
], autoname="naming_series:", title_field="customer", track_changes=1,
   sort_field="feedback_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Branch Manager", "CRU"), ("Helpdesk Agent", "CRUD"),
               ("Telecaller", "CRU"), ("Reception Executive", "CRU"),
               ("Service Manager", "R")]).write(controller=None)
