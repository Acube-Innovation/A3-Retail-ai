// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Item Stock Card"] = {
	// Data, not Link, because the usual way in is a barcode gun pointed at the
	// box: the gun types a number and presses Enter, and that number is a
	// barcode, not an item code. The server resolves whichever was given.
	filters: [
		{
			fieldname: "item",
			label: __("Scan or search an item"),
			fieldtype: "Data",
			reqd: 1,
		},
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "sold", label: __("Include pieces already sold"), fieldtype: "Check",
		  default: 1 },
	],
};
