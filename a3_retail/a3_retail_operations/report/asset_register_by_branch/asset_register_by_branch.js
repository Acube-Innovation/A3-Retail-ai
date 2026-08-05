// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Asset Register by Branch"] = {
	filters: [
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
	],
};
