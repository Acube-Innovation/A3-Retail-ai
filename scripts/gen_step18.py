import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

OPS = "A3 Retail Operations"

DAMAGE_TYPES = ("Transit Damage\nHandling Damage\nStorage Damage\nCustomer Return - Damaged\n"
                "Manufacturing Defect\nDisplay/Demo Wear\nTheft / Pilferage\nNatural Calamity\n"
                "Expiry / Obsolescence")
DISCOVERED = ("Goods Receipt\nInter-branch Transfer Receipt\nStock Count\nSale\nService\n"
              "Routine Inspection")
REFERENCE_TYPES = ("\nPurchase Receipt\nStock Request\nDelivery Note\nSales Invoice\n"
                   "Stock Reconciliation")
RESPONSIBILITY = ("Company (No Recovery)\nEmployee\nSupplier\nCourier / Transporter\nCustomer\n"
                  "Insurance")
RECOVERY_MODE = ("\nSalary Deduction\nSupplier Credit Note\nInsurance Claim\nCourier Claim\n"
                 "Customer Charged\nWritten Off")
DISPOSITION = ("\nScrap\nReturn to Supplier\nRepair & Resell\nSell as Refurbished\n"
               "Use for Spares\nInsurance Surrender")
DAMAGE_STATUS = ("Draft\nPending Approval\nApproved\nMoved to Damaged\nDisposed\nRecovered\nRejected")

CHARGE_TYPES = ("Transporter Demurrage\nCourier Detention\nWarehouse Storage Overstay\n"
                "Customs / Octroi Detention\nCustomer Device Storage")
PARTY_TYPES = "Supplier\nCustomer\nCourier Partner"
DEM_REFERENCE = ("\nPurchase Receipt\nCourier Dispatch\nStock Request\nService Job Card")
PAYABLE = "Payable by Company\nRecoverable from Party"
DEM_STATUS = "Draft\nApproved\nInvoiced\nPaid\nRecovered\nWaived"

print("Step 18 — damages, demurrage, dead stock")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Stock Damage Item", OPS, editable([
	f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
	f("warehouse", "Link", "Warehouse", "Warehouse", in_list_view=1),
	f("qty", "Float", "Qty", default="1", reqd=1, in_list_view=1),
	f("uom", "Link", "UOM", "UOM", fetch_from="item_code.stock_uom", read_only=1),
	f("serial_no", "Small Text", "Serial No"),
	f("batch_no", "Data", "Batch No"),
	f("valuation_rate", "Currency", "Valuation Rate", permlevel=1),
	f("amount", "Currency", "Amount", permlevel=1, read_only=1),
	f("damage_description", "Small Text", "Damage Description"),
	f("is_repairable", "Check", "Repairable"),
	f("photo", "Attach Image", "Photo"),
]), istable=1).write()

damage_fields = [
	f("naming_series", "Select", "Series", "DMG-.branch_code.-.YY.-.####", hidden=1,
	  default="DMG-.branch_code.-.YY.-.####"),
	f("report_date", "Date", "Report Date", reqd=1, in_list_view=1),
	f("status", "Select", "Status", DAMAGE_STATUS, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	cb(),
	f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("company", "Link", "Company", "Company", read_only=1),
	f("reported_by", "Link", "Reported By", "Employee"),

	sb("what_section", "What Happened"),
	f("damage_type", "Select", "Damage Type", DAMAGE_TYPES, reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("discovered_during", "Select", "Discovered During", DISCOVERED),
	f("source_warehouse", "Link", "From Warehouse", "Warehouse", reqd=1),
	cb(),
	f("reference_type", "Select", "Reference", REFERENCE_TYPES),
	f("reference_name", "Dynamic Link", "Reference Doc", "reference_type"),
	f("photos", "Attach Image", "Photo"),

	sb("items_section", "Damaged Items"),
	f("items", "Table", "Damaged Items", "Stock Damage Item", reqd=1, allow_on_submit=1),
	f("total_qty", "Float", "Total Qty", read_only=1, allow_on_submit=1),
	f("total_value", "Currency", "Total Value", read_only=1, permlevel=1, allow_on_submit=1),

	sb("responsibility_section", "Responsibility"),
	f("responsibility", "Select", "Responsibility", RESPONSIBILITY, default="Company (No Recovery)",
	  reqd=1),
	f("responsible_employee", "Link", "Employee", "Employee",
	  depends_on="eval:doc.responsibility=='Employee'"),
	f("responsible_party_type", "Select", "Party Type", "\nSupplier\nCustomer"),
	f("responsible_party", "Dynamic Link", "Party", "responsible_party_type"),
	cb(),
	f("is_recoverable", "Check", "Recoverable"),
	f("recovery_amount", "Currency", "Recovery Amount", depends_on="is_recoverable"),
	f("recovery_mode", "Select", "Recovery Mode", RECOVERY_MODE, depends_on="is_recoverable"),
	f("recovery_reference", "Data", "Recovery Ref", allow_on_submit=1),

	sb("disposition_section", "Disposition"),
	f("disposition", "Select", "Disposition", DISPOSITION, allow_on_submit=1),
	f("disposal_date", "Date", "Disposal Date", allow_on_submit=1),
	cb(),
	f("salvage_value", "Currency", "Salvage Value", allow_on_submit=1),

	sb("processing_section", "Processing"),
	f("stock_entry_transfer", "Link", "Transfer to Damaged WH", "Stock Entry", read_only=1,
	  allow_on_submit=1),
	f("stock_entry_writeoff", "Link", "Write-off Entry", "Stock Entry", read_only=1,
	  allow_on_submit=1),
	cb(),
	f("journal_entry", "Link", "Recovery JE", "Journal Entry", read_only=1, allow_on_submit=1),
	f("additional_salary", "Link", "Salary Deduction", "Additional Salary", read_only=1,
	  allow_on_submit=1),
	f("approved_by", "Link", "Approved By", "User", read_only=1, allow_on_submit=1),
	f("needs_ho_approval", "Check", "Needs Head Office Approval", read_only=1, allow_on_submit=1),
	f("remarks", "Text", "Remarks", allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Stock Damage Report", read_only=1, no_copy=1,
	  print_hide=1),
]

DT("Stock Damage Report", OPS, damage_fields, autoname="naming_series:", title_field="damage_type",
   search_fields="branch,damage_type,status", is_submittable=1, track_changes=1,
   sort_field="report_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Branch Manager", "CRUS"), ("Store Keeper", "CRU"), ("Technician", "CR"),
               ("Service Manager", "R"), ("Accounts Manager", "R"),
               ("A3 Retail Admin", "RU@1"), ("Branch Manager", "RU@1"),
               ("Accounts Manager", "R@1")]).write(controller=None)

DT("Demurrage Charge", OPS, [
	f("naming_series", "Select", "Series", "DEM-.YY.-.####", hidden=1, default="DEM-.YY.-.####"),
	f("charge_type", "Select", "Charge Type", CHARGE_TYPES, reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("branch", "Link", "Branch", "Branch", in_standard_filter=1),
	f("status", "Select", "Status", DEM_STATUS, default="Draft", in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	cb(),
	f("party_type", "Select", "Party Type", PARTY_TYPES, reqd=1),
	f("party", "Dynamic Link", "Party", "party_type", reqd=1, in_list_view=1),
	f("reference_type", "Select", "Reference", DEM_REFERENCE),
	f("reference_name", "Dynamic Link", "Reference Doc", "reference_type"),

	sb("period_section", "Free Period"),
	f("arrival_date", "Date", "Arrival / Ready Date", reqd=1),
	f("free_days", "Int", "Free Days"),
	f("free_until_date", "Date", "Free Until", read_only=1),
	cb(),
	f("actual_clearance_date", "Date", "Cleared / Collected On"),
	f("chargeable_days", "Int", "Chargeable Days", read_only=1, in_list_view=1),

	sb("amount_section", "Amount"),
	f("rate_per_day", "Currency", "Rate per Day", reqd=1),
	f("charge_amount", "Currency", "Charge", read_only=1, in_list_view=1),
	f("gst_applicable", "Check", "GST Applicable"),
	cb(),
	f("tax_amount", "Currency", "GST", read_only=1),
	f("total_amount", "Currency", "Total", read_only=1),
	f("payable_or_recoverable", "Select", "Direction", PAYABLE,
	  default="Recoverable from Party", reqd=1),

	sb("settlement_section", "Settlement"),
	f("purchase_invoice", "Link", "Purchase Invoice", "Purchase Invoice", allow_on_submit=1),
	f("journal_entry", "Link", "Journal Entry", "Journal Entry", allow_on_submit=1),
	cb(),
	f("responsibility", "Select", "Responsibility", "Company\nEmployee\nSupplier\nCourier",
	  default="Company"),
	f("responsible_employee", "Link", "Employee", "Employee"),
	f("remarks", "Small Text", "Remarks"),
], autoname="naming_series:", title_field="party", track_changes=1, sort_field="arrival_date",
   sort_order="DESC",
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Accounts Manager", "CRUD"), ("Branch Manager", "CRU"),
               ("Store Keeper", "R")]).write(controller=None)
