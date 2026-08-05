import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

SALES = "A3 Retail Sales"

PURPOSES = ("Customer Sale\nService Job Card\nStock Balancing\nDisplay Unit\nReturn to HO")
STATUSES = ("Draft\nPending Approval\nApproved\nRejected\nPartially Dispatched\nIn Transit\n"
            "Received\nCancelled")

print("Step 17 — stock requests & transfers")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Stock Request Item", SALES, editable([
	f("item_code", "Link", "Item", "Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
	f("qty", "Float", "Qty", default="1", reqd=1, in_list_view=1),
	f("uom", "Link", "UOM", "UOM", fetch_from="item_code.stock_uom", read_only=1),
	f("serial_no", "Small Text", "Serial No"),
	f("available_at_source", "Float", "Available at Source", read_only=1, in_list_view=1),
	f("dispatched_qty", "Float", "Dispatched", read_only=1, in_list_view=1),
	f("received_qty", "Float", "Received", read_only=1, in_list_view=1),
	f("rate", "Currency", "Rate", permlevel=1),
	f("remarks", "Data", "Remarks"),
]), istable=1).write()

fields = [
	f("naming_series", "Select", "Series", "SR-.branch_code.-.YY.-.####", hidden=1,
	  default="SR-.branch_code.-.YY.-.####"),
	f("request_date", "Datetime", "Request Date", reqd=1, in_list_view=1),
	f("status", "Select", "Status", STATUSES, default="Draft", read_only=1, in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	f("priority", "Select", "Priority", "Normal\nUrgent", default="Normal"),
	cb(),
	f("requesting_branch", "Link", "Requesting Branch", "Branch", reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	f("requesting_warehouse", "Link", "To Warehouse", "Warehouse", reqd=1),
	f("company", "Link", "Company", "Company", read_only=1),

	sb("source_section", "Source"),
	f("source_branch", "Link", "Source Branch", "Branch", reqd=1, in_list_view=1),
	f("source_warehouse", "Link", "From Warehouse", "Warehouse", reqd=1),
	cb(),
	f("transit_warehouse", "Link", "Goods In Transit", "Warehouse", read_only=1),
	f("required_by", "Date", "Required By"),

	sb("purpose_section", "Purpose"),
	f("purpose", "Select", "Purpose", PURPOSES, default="Stock Balancing", reqd=1),
	f("reference_job_card", "Link", "Job Card", "Service Job Card",
	  depends_on="eval:doc.purpose=='Service Job Card'"),
	cb(),
	f("reference_sales_order", "Link", "Sales Order", "Sales Order",
	  depends_on="eval:doc.purpose=='Customer Sale'"),

	sb("items_section", "Items"),
	f("items", "Table", "Items", "Stock Request Item", reqd=1, allow_on_submit=1),
	f("total_value", "Currency", "Total Value", read_only=1, permlevel=1, allow_on_submit=1),

	sb("approval_section", "Approval"),
	f("approved_by", "Link", "Approved By", "User", read_only=1, allow_on_submit=1),
	f("approved_on", "Datetime", "Approved On", read_only=1, allow_on_submit=1),
	cb(),
	f("rejection_reason", "Small Text", "Rejection Reason", allow_on_submit=1),
	f("needs_ho_approval", "Check", "Needs Head Office Approval", read_only=1, allow_on_submit=1),

	sb("movement_section", "Movement"),
	f("material_request", "Link", "Material Request", "Material Request", read_only=1,
	  allow_on_submit=1),
	f("outward_stock_entry", "Link", "Outward Entry", "Stock Entry", read_only=1, allow_on_submit=1),
	f("inward_stock_entry", "Link", "Inward Entry", "Stock Entry", read_only=1, allow_on_submit=1),
	cb(),
	f("courier_dispatch", "Link", "Courier Dispatch", "Courier Dispatch", allow_on_submit=1),
	f("dispatched_on", "Datetime", "Dispatched On", read_only=1, allow_on_submit=1),
	f("received_on", "Datetime", "Received On", read_only=1, allow_on_submit=1),
	f("transit_days", "Int", "Transit Days", read_only=1, allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Stock Request", read_only=1, no_copy=1, print_hide=1),
]

DT("Stock Request", SALES, fields, autoname="naming_series:", title_field="requesting_branch",
   search_fields="requesting_branch,source_branch,status", is_submittable=1, track_changes=1,
   sort_field="request_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Branch Manager", "CRUDS"), ("Store Keeper", "CRUDS"),
               ("Service Manager", "CRU"), ("Sales Executive", "CRU"),
               ("Reception Executive", "CRU"), ("Technician", "CRU"),
               ("A3 Retail Admin", "RU@1"), ("Branch Manager", "RU@1"),
               ("Accounts Manager", "R@1")]).write(controller=None)
