// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
// List view settings for Service Job Card (scope 3.2, item 9).

frappe.listview_settings["Service Job Card"] = {
	add_fields: [
		"status", "customer_name", "device_model", "imei_1",
		"assigned_technician", "sla_due_on", "is_delayed", "grand_total",
	],

	filters: [["status", "not in", ["Delivered", "Closed", "Cancelled"]]],

	get_indicator(doc) {
		// A breached SLA outranks the status colour — it is what needs attention.
		if (doc.is_delayed && !["Delivered", "Closed", "Cancelled"].includes(doc.status)) {
			return [__("{0} — Delayed", [__(doc.status)]), "red", "is_delayed,=,1"];
		}
		const colour = a3_retail.status_colour(doc.status);
		return [__(doc.status), colour, "status,=," + doc.status];
	},

	onload(listview) {
		listview.page.add_inner_button(__("Control Tower"), () =>
			frappe.set_route("a3-service-control-tower")
		);
		listview.page.add_inner_button(__("Reception Desk"), () =>
			frappe.set_route("a3-reception-desk")
		);
	},
};
