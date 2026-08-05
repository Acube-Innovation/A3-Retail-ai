import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

COMM = "A3 Retail Communication"

OBJECTIVES = ("Warranty Renewal\nService Reminder\nOffer Promotion\nLost Lead Follow-up\n"
              "Feedback Collection\nPayment / EMI Reminder\nDevice Pickup Reminder\n"
              "New Launch Announcement\nBirthday / Anniversary\nWin-back (Lapsed Customer)")
TARGET_SOURCES = "Report\nDocType Filter\nManual Upload (CSV)\nBranch Visit Log"
CAMPAIGN_STATUS = "Draft\nActive\nPaused\nCompleted\nCancelled"
CALL_STATUS = ("Not Called\nConnected\nNo Answer\nBusy\nSwitched Off\nWrong Number\n"
               "Call Back Later\nDo Not Call")
OUTCOMES = ("Pending\nConverted\nInterested - Follow-up\nNot Interested\n"
            "Already Done Elsewhere\nInvalid Contact")
TASK_REF = "\nWarranty Registration\nService Job Card\nBranch Visit Log\nLead\nCustomer"
OUTCOME_REF = "\nSales Invoice\nService Job Card\nWarranty Registration\nLead\nQuotation"
DISPOSITION_CATEGORIES = "Positive\nNeutral\nNegative\nInvalid"

print("Step 21 — telecalling")

DT("Campaign Telecaller", COMM, [
	f("employee", "Link", "Telecaller", "Employee", reqd=1, in_list_view=1),
	f("employee_name", "Data", "Name", fetch_from="employee.employee_name", read_only=1,
	  in_list_view=1),
	f("target_calls", "Int", "Target Calls", in_list_view=1),
	f("allocated", "Int", "Allocated", read_only=1, in_list_view=1),
	f("completed", "Int", "Completed", read_only=1, in_list_view=1),
], istable=1).write()

DT("Call Disposition", COMM, [
	f("disposition_name", "Data", "Disposition", reqd=1, unique=1, in_list_view=1),
	f("category", "Select", "Category", DISPOSITION_CATEGORIES, reqd=1, in_list_view=1,
	  in_standard_filter=1),
	cb(),
	f("requires_next_call", "Check", "Requires Next Call", in_list_view=1),
	f("default_next_call_days", "Int", "Next Call After (days)",
	  depends_on="requires_next_call"),
	f("triggers_whatsapp", "Check", "Triggers WhatsApp"),
	f("whatsapp_template", "Link", "WhatsApp Template", "WhatsApp Template",
	  depends_on="triggers_whatsapp"),
	f("is_dnc", "Check", "Marks Do Not Call"),
], autoname="field:disposition_name", title_field="disposition_name",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("Telecaller", "R")]).write()

DT("Telecalling Campaign", COMM, [
	f("campaign_name", "Data", "Campaign Name", reqd=1, in_list_view=1),
	f("naming_series", "Select", "Series", "TCC-.YY.-.####", hidden=1, default="TCC-.YY.-.####"),
	f("objective", "Select", "Objective", OBJECTIVES, reqd=1, in_list_view=1, in_standard_filter=1),
	f("branch", "Link", "Branch", "Branch", description="Blank targets every branch"),
	cb(),
	f("start_date", "Date", "Start Date", reqd=1),
	f("end_date", "Date", "End Date"),
	f("status", "Select", "Status", CAMPAIGN_STATUS, default="Draft", in_list_view=1,
	  in_standard_filter=1),

	sb("target_section", "Target List"),
	f("target_source", "Select", "Target Source", TARGET_SOURCES, default="DocType Filter"),
	f("source_report", "Link", "Source Report", "Report",
	  depends_on="eval:doc.target_source=='Report'"),
	f("source_doctype", "Link", "Source DocType", "DocType",
	  depends_on="eval:doc.target_source=='DocType Filter'"),
	cb(),
	f("source_filters", "Code", "Filters (JSON)", options="JSON"),
	f("exclude_contacted_days", "Int", "Exclude Contacted In Last (days)", default="30"),

	sb("script_section", "Script"),
	f("script", "Text Editor", "Call Script"),
	f("objection_handling", "Text Editor", "Objection Handling"),
	cb(),
	f("offer_campaign", "Link", "Offer to Pitch", "Seasonal Offer Campaign"),
	f("whatsapp_template", "Link", "Follow-up Template", "WhatsApp Template"),

	sb("team_section", "Team"),
	f("assigned_team", "Table", "Telecallers", "Campaign Telecaller"),

	sb("metrics_section", "Metrics"),
	f("target_count", "Int", "Target", read_only=1),
	f("allocated_count", "Int", "Allocated", read_only=1, in_list_view=1),
	f("called_count", "Int", "Called", read_only=1),
	cb(),
	f("connected_count", "Int", "Connected", read_only=1),
	f("converted_count", "Int", "Converted", read_only=1),
	f("conversion_value", "Currency", "Conversion Value", read_only=1),
], autoname="naming_series:", title_field="campaign_name", track_changes=1,
   sort_field="start_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Branch Manager", "R"), ("Telecaller", "R")]).write(controller=None)

DT("Call Task", COMM, [
	f("naming_series", "Select", "Series", "CT-.YY.-.######", hidden=1, default="CT-.YY.-.######"),
	f("campaign", "Link", "Campaign", "Telecalling Campaign", in_standard_filter=1),
	f("customer", "Link", "Customer", "Customer", in_list_view=1),
	f("contact_name", "Data", "Contact Name", reqd=1, in_list_view=1),
	f("mobile_no", "Data", "Mobile", reqd=1, in_list_view=1, length=10),
	cb(),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("assigned_to", "Link", "Assigned To", "Employee", in_standard_filter=1),
	f("priority", "Select", "Priority", "Low\nNormal\nHigh", default="Normal"),
	f("scheduled_date", "Date", "Scheduled", in_list_view=1),

	sb("context_section", "Context"),
	f("context", "Small Text", "Context"),
	f("reference_type", "Select", "Reference", TASK_REF),
	cb(),
	f("reference_name", "Dynamic Link", "Reference", "reference_type"),

	sb("call_section", "Call"),
	f("call_status", "Select", "Call Status", CALL_STATUS, default="Not Called", in_list_view=1,
	  in_standard_filter=1),
	f("disposition", "Link", "Disposition", "Call Disposition"),
	f("call_datetime", "Datetime", "Called On"),
	f("duration_seconds", "Int", "Duration (s)"),
	cb(),
	f("attempt_no", "Int", "Attempt", default="1"),
	f("recording_url", "Data", "Recording"),
	f("call_log", "Link", "Call Log", "Call Log"),
	f("notes", "Small Text", "Notes"),

	sb("outcome_section", "Outcome"),
	f("outcome", "Select", "Outcome", OUTCOMES, default="Pending", in_standard_filter=1),
	f("outcome_reference_type", "Select", "Converted To", OUTCOME_REF),
	f("outcome_reference_name", "Dynamic Link", "Reference", "outcome_reference_type"),
	cb(),
	f("conversion_value", "Currency", "Conversion Value"),
	f("next_call_date", "Date", "Next Call"),
	f("whatsapp_sent", "Check", "WhatsApp Sent"),
], autoname="naming_series:", title_field="contact_name",
   search_fields="mobile_no,contact_name,call_status", track_changes=1,
   sort_field="scheduled_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Telecaller", "CRU"), ("Branch Manager", "R"),
               ("Helpdesk Agent", "R")]).write(controller=None)
