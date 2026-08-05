// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Pending Job Cards Ageing"] = {
	filters: [
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
	],
};
