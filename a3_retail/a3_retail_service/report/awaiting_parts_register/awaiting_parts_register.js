// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Awaiting Parts Register"] = {
	filters: [
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
	],
};
