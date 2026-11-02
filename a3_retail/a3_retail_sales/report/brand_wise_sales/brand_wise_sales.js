// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Brand Wise Sales"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "brand",
			label: __("Brands"),
			fieldtype: "MultiSelectList",
			options: "Brand",
			get_data: (txt) => frappe.db.get_link_options("Brand", txt),
		},
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "group_by_brand", label: __("Group by brand"), fieldtype: "Check" },
	],
};
