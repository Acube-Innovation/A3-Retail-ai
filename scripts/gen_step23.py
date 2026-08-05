import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

OPS = "A3 Retail Operations"

APPLICABLE_TO = ("Sales Executive\nBranch Manager\nTechnician\nTelecaller\nReception\n"
                 "Custom (Employee List)")
FREQUENCY = "Monthly\nQuarterly\nAnnual"
METRICS = ("Net Sales Value\nUnits Sold\nGross Profit\nService Revenue\nJobs Completed\n"
           "EW Plans Sold\nEMI Applications Disbursed\nAccessory Attach Value\n"
           "Footfall Conversion %\nCollections\nTelecalling Conversions")
TARGET_TYPES = "Absolute Target\n% of Branch Target\nNo Target (Slab from Zero)"
SLAB_TYPES = "% of Metric Value\nFixed Amount\nPer Unit"
RUN_STATUS = ("Draft\nCalculated\nPending Approval\nApproved\nPosted to Payroll\nCancelled")

print("Step 23 — HR, incentives, assets")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Incentive Slab", OPS, [
	f("from_percent", "Float", "From %", in_list_view=1),
	f("to_percent", "Float", "To %", in_list_view=1),
	f("incentive_type", "Select", "Type", SLAB_TYPES, default="% of Metric Value", in_list_view=1),
	f("value", "Float", "Value", in_list_view=1),
	f("remarks", "Data", "Remarks"),
], istable=1).write()

DT("Incentive Product Spiff", OPS, [
	f("item_group", "Link", "Item Group", "Item Group", in_list_view=1),
	f("brand", "Link", "Brand", "Brand", in_list_view=1),
	f("item_code", "Link", "Item", "Item", in_list_view=1),
	f("min_value", "Currency", "Minimum Value"),
	f("spiff_per_unit", "Currency", "Spiff per Unit", reqd=1, in_list_view=1),
	f("valid_from", "Date", "Valid From"),
	f("valid_upto", "Date", "Valid Upto"),
], istable=1).write()

DT("Incentive Designation", OPS,
   [f("designation", "Link", "Designation", "Designation", reqd=1, in_list_view=1)],
   istable=1).write()
DT("Incentive Employee", OPS, [
	f("employee", "Link", "Employee", "Employee", reqd=1, in_list_view=1),
	# Branches carry very different footfall, so one scheme can hold several targets.
	f("monthly_target", "Float", "Target Override", in_list_view=1, columns=3,
	  description="Blank uses the scheme target."),
], istable=1).write()

SLAB_BASIS = "Achievement %\nMetric Value"
BONUS_RULES = "\nEMI Approved Within 24 Hours\nBranch EW Attach Rate\nRepairs Within TAT"

DT("Incentive Calculation Item", OPS, editable([
	f("employee", "Link", "Employee", "Employee", reqd=1, in_list_view=1),
	f("employee_name", "Data", "Name", fetch_from="employee.employee_name", read_only=1,
	  in_list_view=1),
	f("designation", "Data", "Designation", read_only=1),
	f("branch", "Link", "Branch", "Branch", read_only=1, in_list_view=1),
	f("target", "Float", "Target", in_list_view=1),
	f("achieved", "Float", "Achieved", in_list_view=1),
	f("achievement_percent", "Percent", "Achievement %", read_only=1, in_list_view=1),
	f("slab_applied", "Data", "Slab", read_only=1),
	f("base_incentive", "Currency", "Base Incentive", read_only=1),
	f("spiff_amount", "Currency", "Spiff", read_only=1),
	f("clawback_amount", "Currency", "Clawback", read_only=1),
	f("attendance_percent", "Percent", "Attendance %", read_only=1),
	f("qc_fail_percent", "Percent", "QC Fail %", read_only=1),
	f("csat_score", "Float", "CSAT", read_only=1),
	f("gates_passed", "Check", "Gates Passed", read_only=1, in_list_view=1),
	f("gate_failure_reason", "Data", "Gate Failure", read_only=1),
	f("final_incentive", "Currency", "Final Incentive", read_only=1, in_list_view=1),
	f("additional_salary", "Link", "Additional Salary", "Additional Salary", read_only=1),
	f("remarks", "Data", "Remarks"),
]), istable=1).write()

DT("Employee Incentive Scheme", OPS, [
	f("scheme_name", "Data", "Scheme Name", reqd=1, unique=1, in_list_view=1),
	f("applicable_to", "Select", "Applicable To", APPLICABLE_TO, reqd=1, in_list_view=1),
	f("frequency", "Select", "Frequency", FREQUENCY, default="Monthly", in_list_view=1),
	f("is_active", "Check", "Active", default="1"),
	cb(),
	f("designations", "Table MultiSelect", "Designations", "Incentive Designation"),
	f("employees", "Table MultiSelect", "Employees", "Incentive Employee"),
	f("branches", "Table", "Branches", "Offer Branch"),

	sb("basis_section", "Basis"),
	f("metric", "Select", "Metric", METRICS, reqd=1, in_list_view=1),
	f("target_type", "Select", "Target Type", TARGET_TYPES, default="Absolute Target"),
	f("monthly_target", "Float", "Monthly Target"),
	cb(),
	f("minimum_qualification_percent", "Percent", "Minimum Qualification %", default="80"),
	f("slab_basis", "Select", "Match Slabs On", SLAB_BASIS, default="Achievement %",
	  description="Unit-based schemes (jobs, plans, applications) match the raw count; "
	              "value-based schemes match the achievement percentage."),
	f("payout_component", "Link", "Payout Component", "Salary Component"),
	f("cap_amount", "Currency", "Cap per Period"),

	sb("slabs_section", "Slabs & Spiffs"),
	f("slabs", "Table", "Slabs", "Incentive Slab"),
	f("product_spiffs", "Table", "Product Spiffs", "Incentive Product Spiff"),

	sb("bonus_section", "Conditional Bonus"),
	f("bonus_rule", "Select", "Bonus Rule", BONUS_RULES,
	  description="Schemes 3 and 4 in the scope pay a bonus that no product spiff can express."),
	f("bonus_value", "Currency", "Bonus Value", depends_on="bonus_rule"),
	cb(),
	f("bonus_threshold_percent", "Percent", "Bonus Threshold %", depends_on="bonus_rule"),

	sb("gates_section", "Gates"),
	f("attendance_gate_percent", "Percent", "Attendance Gate %", default="90"),
	f("quality_gate", "Check", "Apply QC Gate"),
	f("max_qc_fail_percent", "Percent", "Max QC Fail %", default="5", depends_on="quality_gate"),
	cb(),
	f("csat_gate", "Check", "Apply CSAT Gate"),
	f("min_csat", "Float", "Minimum CSAT", default="4.0", depends_on="csat_gate"),
	f("return_clawback", "Check", "Clawback on Returns"),
], autoname="field:scheme_name", title_field="scheme_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"), ("HR Manager", "CRUD"),
               ("Branch Manager", "R"), ("Accounts Manager", "R")]).write()

DT("Incentive Calculation Run", OPS, [
	f("naming_series", "Select", "Series", "INC-.YY.-.MM.-.###", hidden=1,
	  default="INC-.YY.-.MM.-.###"),
	f("scheme", "Link", "Scheme", "Employee Incentive Scheme", reqd=1, in_list_view=1),
	f("from_date", "Date", "From Date", reqd=1, in_list_view=1),
	f("to_date", "Date", "To Date", reqd=1, in_list_view=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("company", "Link", "Company", "Company", read_only=1),
	f("status", "Select", "Status", RUN_STATUS, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),

	sb("employees_section", "Employees"),
	f("employees", "Table", "Employees", "Incentive Calculation Item", allow_on_submit=1),
	f("total_incentive", "Currency", "Total Incentive", read_only=1, in_list_view=1,
	  allow_on_submit=1),

	sb("approval_section", "Approval"),
	f("approved_by", "Link", "Approved By", "User", read_only=1, allow_on_submit=1),
	cb(),
	f("posted_on", "Datetime", "Posted On", read_only=1, allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Incentive Calculation Run", read_only=1, no_copy=1,
	  print_hide=1),
], autoname="naming_series:", title_field="scheme", is_submittable=1, track_changes=1,
   sort_field="from_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("HR Manager", "CRUDS"), ("Branch Manager", "R"),
               ("Accounts Manager", "R")]).write(controller=None)
