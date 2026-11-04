// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Brand Wise Stock"] = {
	// No dates. Stock is what is on the shelf right now; a date range would
	// only invite the question of what it meant.
	filters: [
		{
			fieldname: "brand",
			label: __("Brands"),
			fieldtype: "MultiSelectList",
			options: "Brand",
			get_data: (txt) => frappe.db.get_link_options("Brand", txt),
		},
		{ fieldname: "item_group", label: __("Category"), fieldtype: "Link",
		  options: "Item Group" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "hide_empty", label: __("Only items in stock"), fieldtype: "Check",
		  default: 1 },
	],
};
