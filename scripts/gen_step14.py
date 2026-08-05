import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SALES = "A3 Retail Sales"

GRADES = "A - Like New\nB - Good\nC - Average\nD - Poor / Spares"
PARAMETERS = ("Display Condition\nBody Condition\nBattery Health\nCamera\nTouch\n"
              "Charging Port\nWater Damage\nRepair History")
ID_PROOFS = "Aadhaar\nDriving Licence\nPassport\nVoter ID"
RESALE = "In Stock\nUnder Refurb\nSold\nScrapped"
STATUSES = "Draft\nValued\nAccepted\nSold\nCancelled"

print("Step 14 — device exchange")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Exchange Grading Parameter", SALES, editable([
	f("parameter", "Select", "Parameter", PARAMETERS, reqd=1, in_list_view=1),
	f("observation", "Data", "Observation", in_list_view=1),
	f("deduction_percent", "Percent", "Deduction %", in_list_view=1),
	f("deduction_amount", "Currency", "Deduction Amount", read_only=1, in_list_view=1),
]), istable=1).write()

fields = [
	f("naming_series", "Select", "Series", "EXC-.branch_code.-.YY.-.####", hidden=1,
	  default="EXC-.branch_code.-.YY.-.####"),
	f("exchange_date", "Date", "Date", reqd=1, in_list_view=1),
	f("customer", "Link", "Customer", "Customer", reqd=1, in_list_view=1),
	f("customer_mobile", "Data", "Mobile", fetch_from="customer.a3_mobile_no", read_only=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("company", "Link", "Company", "Company", read_only=1),
	f("status", "Select", "Status", STATUSES, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),

	sb("old_device_section", "Old Device"),
	f("old_brand", "Link", "Brand", "Brand", reqd=1),
	f("old_model", "Link", "Model", "Device Model", reqd=1, in_list_view=1),
	f("old_imei", "Data", "IMEI", reqd=1, length=20),
	f("imei_override", "Check", "Override IMEI Check"),
	cb(),
	f("old_purchase_year", "Int", "Purchase Year"),
	f("old_storage", "Data", "Storage"),
	f("has_box", "Check", "Box Included"),
	f("has_charger", "Check", "Charger Included"),
	f("has_bill", "Check", "Original Bill"),

	sb("grading_section", "Grading"),
	f("grading_parameters", "Table", "Grading", "Exchange Grading Parameter", allow_on_submit=1),
	f("base_value", "Currency", "Base Value", reqd=1),
	f("deductions", "Currency", "Deductions", read_only=1, allow_on_submit=1),
	cb(),
	f("grade", "Select", "Final Grade", GRADES, read_only=1, in_list_view=1, allow_on_submit=1),
	f("exchange_bonus", "Currency", "Exchange Bonus (Offer)", read_only=1, allow_on_submit=1),
	f("final_exchange_value", "Currency", "Final Exchange Value", read_only=1, bold=1,
	  in_list_view=1, allow_on_submit=1),

	sb("verification_section", "Verification"),
	f("id_proof_type", "Select", "ID Proof", ID_PROOFS, reqd=1),
	f("id_proof_number_last4", "Data", "ID Last 4", reqd=1, length=4),
	f("id_proof_attachment", "Attach", "ID Copy"),
	cb(),
	f("imei_check_done", "Check", "IMEI Blacklist Check Done"),
	f("declaration_signed", "Signature", "Customer Declaration"),
	f("device_photo_1", "Attach Image", "Photo 1"),
	f("device_photo_2", "Attach Image", "Photo 2"),
	f("device_photo_3", "Attach Image", "Photo 3"),

	sb("linkage_section", "Linkage & Resale"),
	f("new_sales_invoice", "Link", "New Sale Invoice", "Sales Invoice", allow_on_submit=1),
	f("purchase_receipt", "Link", "Purchase Receipt", "Purchase Receipt", read_only=1,
	  allow_on_submit=1),
	f("used_item_code", "Link", "Created Item", "Item", read_only=1, allow_on_submit=1),
	cb(),
	f("used_serial_no", "Link", "Created Serial", "Serial No", read_only=1, allow_on_submit=1),
	f("resale_status", "Select", "Resale Status", RESALE, default="In Stock", allow_on_submit=1),
	f("resale_invoice", "Link", "Resale Invoice", "Sales Invoice", read_only=1, allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Device Exchange", read_only=1, no_copy=1, print_hide=1),
]

DT(
	"Device Exchange",
	SALES,
	fields,
	autoname="naming_series:",
	title_field="customer",
	search_fields="old_imei,customer,grade",
	is_submittable=1,
	track_changes=1,
	sort_field="exchange_date",
	sort_order="DESC",
	perms_spec=[
		("System Manager", "CRUDS"),
		("A3 Retail Admin", "CRUDS"),
		("Branch Manager", "CRUDS"),
		("Sales Executive", "CRU"),
		("Reception Executive", "CRU"),
		("Accounts Manager", "R"),
	],
).write(controller=None)
