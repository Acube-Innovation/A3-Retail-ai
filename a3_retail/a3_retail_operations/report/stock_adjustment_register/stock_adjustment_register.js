// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
frappe.query_reports["Stock Adjustment Register"] = {
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
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{
			// Opening Stock is the migration's own balances; counting is what
			// the shop means by an adjustment.
			fieldname: "purpose",
			label: __("Purpose"),
			fieldtype: "Select",
			options: "Stock Reconciliation\nOpening Stock",
			default: "Stock Reconciliation",
		},
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "only_differences",
			label: __("Only rows that changed"),
			fieldtype: "Check",
			default: 1,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (["qty_difference", "amount_difference"].includes(column.fieldname)) {
			const n = parseFloat(value);
			if (n > 0) return `<span style="color:#16a34a">${formatted}</span>`;
			if (n < 0) return `<span style="color:#e11d48">${formatted}</span>`;
		}
		return formatted;
	},
};
