import sys
sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb

OPS = "A3 Retail Operations"

ZONES = "Within City\nWithin State\nMetro\nRest of India\nNorth East & J&K"
SERVICE_TYPES = "Surface\nAir\nExpress\nSame Day"
DISPATCH_TYPES = ("Sales Delivery\nService Device Return\nService Device Pickup\n"
                  "Inter-branch Stock\nOEM Warranty Return\nDocument / Cheque\nMarketing Material")
DISPATCH_REF = ("\nDelivery Note\nService Job Card\nStock Request\nOEM Warranty Return\n"
                "Sales Invoice")
CONSIGNEE = "Customer\nBranch\nSupplier\nEmployee"
DISPATCH_STATUS = ("Booked\nPicked Up\nIn Transit\nOut for Delivery\nDelivered\nDelivery Failed\n"
                   "RTO (Returned)\nLost / Damaged")

print("Step 19 — courier & logistics")


def editable(rows):
	for row in rows:
		if row["fieldtype"] not in ("Section Break", "Column Break"):
			row["allow_on_submit"] = 1
	return rows


DT("Courier Rate Card", OPS, [
	f("zone", "Select", "Zone", ZONES, reqd=1, in_list_view=1),
	f("service_type", "Select", "Service Type", SERVICE_TYPES, reqd=1, in_list_view=1),
	f("weight_slab_from", "Float", "From (kg)", in_list_view=1),
	f("weight_slab_to", "Float", "To (kg)", default="0.5", in_list_view=1),
	f("base_rate", "Currency", "Base Rate", reqd=1, in_list_view=1),
	f("per_additional_500g", "Currency", "Per Extra 500 g"),
	f("fuel_surcharge_percent", "Percent", "Fuel Surcharge %"),
	f("tat_days", "Int", "TAT (days)", default="2", in_list_view=1),
], istable=1).write()

DT("Courier Service Type", OPS,
   [f("service_type", "Select", "Service Type", SERVICE_TYPES, reqd=1, in_list_view=1)],
   istable=1).write()

DT("Courier Dispatch Item", OPS, editable([
	f("item_code", "Link", "Item", "Item", in_list_view=1),
	f("description", "Data", "Description", in_list_view=1),
	f("qty", "Float", "Qty", default="1", in_list_view=1),
	f("serial_no", "Small Text", "Serial No"),
	f("value", "Currency", "Value", in_list_view=1),
]), istable=1).write()

DT("Courier Partner", OPS, [
	f("partner_name", "Data", "Partner Name", reqd=1, unique=1, in_list_view=1),
	f("supplier", "Link", "Supplier", "Supplier", in_list_view=1),
	f("is_active", "Check", "Active", default="1"),
	cb(),
	f("standard_tat_days", "Int", "Standard TAT (days)", default="2"),
	f("free_days_before_demurrage", "Int", "Free Days Before Detention", default="1"),
	f("pickup_contact", "Data", "Pickup Contact"),
	f("pickup_phone", "Data", "Pickup Phone"),

	sb("service_section", "Services"),
	f("service_types", "Table MultiSelect", "Service Types", "Courier Service Type"),
	f("tracking_url_pattern", "Data", "Tracking URL Pattern",
	  description="Use {awb} as the placeholder, e.g. https://track.example.com/?awb={awb}"),

	sb("rates_section", "Rate Card"),
	f("rate_card", "Table", "Rate Card", "Courier Rate Card"),
], autoname="field:partner_name", title_field="partner_name", track_changes=1,
   perms_spec=[("System Manager", "CRUD"), ("A3 Retail Admin", "CRUD"),
               ("Branch Manager", "R"), ("Store Keeper", "R"), ("Accounts Manager", "CRUD")]).write()

fields = [
	f("naming_series", "Select", "Series", "CD-.YY.-.#####", hidden=1, default="CD-.YY.-.#####"),
	f("dispatch_type", "Select", "Dispatch Type", DISPATCH_TYPES, reqd=1, in_list_view=1,
	  in_standard_filter=1),
	f("branch", "Link", "Branch", "Branch", reqd=1, in_standard_filter=1),
	f("branch_code", "Data", "Branch Code", read_only=1, hidden=1),
	cb(),
	f("status", "Select", "Status", DISPATCH_STATUS, default="Booked", in_list_view=1,
	  in_standard_filter=1, allow_on_submit=1),
	f("status_updated_on", "Datetime", "Last Update", read_only=1, allow_on_submit=1),
	f("company", "Link", "Company", "Company", read_only=1),

	sb("reference_section", "Reference"),
	f("reference_type", "Select", "Reference", DISPATCH_REF),
	f("reference_name", "Dynamic Link", "Reference Doc", "reference_type"),
	cb(),
	f("courier_partner", "Link", "Courier Partner", "Courier Partner", reqd=1, in_list_view=1),
	f("service_type", "Select", "Service Type", SERVICE_TYPES, default="Surface"),
	f("awb_no", "Data", "AWB / Docket No", in_list_view=1, allow_on_submit=1),
	f("tracking_url", "Data", "Tracking URL", read_only=1, allow_on_submit=1),

	sb("consignee_section", "Consignee"),
	f("consignee_type", "Select", "Consignee Type", CONSIGNEE, default="Customer"),
	f("consignee", "Dynamic Link", "Consignee", "consignee_type"),
	f("consignee_name", "Data", "Name"),
	cb(),
	f("consignee_mobile", "Data", "Mobile"),
	f("consignee_address", "Small Text", "Address"),
	f("pincode", "Data", "Pincode", reqd=1, length=6),
	f("zone", "Select", "Zone", ZONES, description="Derived from the pincode; drives the rate card"),

	sb("package_section", "Package"),
	f("items", "Table", "Contents", "Courier Dispatch Item", allow_on_submit=1),
	f("no_of_packages", "Int", "Packages", default="1"),
	f("weight_kg", "Float", "Weight (kg)", default="0.5"),
	cb(),
	f("declared_value", "Currency", "Declared Value"),
	f("is_insured", "Check", "Insured"),
	f("insurance_amount", "Currency", "Insurance", depends_on="is_insured"),
	f("is_cod", "Check", "COD"),
	f("cod_amount", "Currency", "COD Amount", depends_on="is_cod"),

	sb("dates_section", "Dates"),
	f("dispatch_date", "Datetime", "Dispatch Date", reqd=1),
	f("expected_delivery_date", "Date", "Expected Delivery", read_only=1, allow_on_submit=1),
	cb(),
	f("actual_delivery_date", "Datetime", "Actual Delivery", allow_on_submit=1),
	f("delay_days", "Int", "Delay (days)", read_only=1, in_list_view=1, allow_on_submit=1),
	f("pod_attachment", "Attach", "POD", allow_on_submit=1),
	f("received_by", "Data", "Received By", allow_on_submit=1),

	sb("cost_section", "Cost"),
	f("freight_amount", "Currency", "Freight", allow_on_submit=1),
	f("fuel_surcharge", "Currency", "Fuel Surcharge", read_only=1, allow_on_submit=1),
	f("other_charges", "Currency", "Other Charges", allow_on_submit=1),
	cb(),
	f("gst_amount", "Currency", "GST", read_only=1, allow_on_submit=1),
	f("total_cost", "Currency", "Total Cost", read_only=1, allow_on_submit=1),
	f("is_billable_to_customer", "Check", "Charge to Customer"),
	f("charged_in_invoice", "Link", "Charged In", "Sales Invoice", allow_on_submit=1),
	f("purchase_invoice", "Link", "Courier Bill", "Purchase Invoice", allow_on_submit=1),
	f("remarks", "Small Text", "Remarks", allow_on_submit=1),
	f("amended_from", "Link", "Amended From", "Courier Dispatch", read_only=1, no_copy=1,
	  print_hide=1),
]

DT("Courier Dispatch", OPS, fields, autoname="naming_series:", title_field="consignee_name",
   search_fields="awb_no,consignee_name,status", is_submittable=1, track_changes=1,
   sort_field="dispatch_date", sort_order="DESC",
   perms_spec=[("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS"),
               ("Branch Manager", "CRUDS"), ("Store Keeper", "CRUS"),
               ("Service Manager", "CRU"), ("Reception Executive", "CRU"),
               ("Accounts Manager", "R")]).write(controller=None)
