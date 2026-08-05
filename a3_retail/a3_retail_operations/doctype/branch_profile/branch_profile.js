// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors

frappe.ui.form.on("Branch Profile", {
	setup(frm) {
		// Only leaf warehouses of this company can hold stock.
		["default_warehouse", "service_warehouse", "damaged_warehouse", "used_device_warehouse"].forEach(
			(field) => {
				frm.set_query(field, () => ({
					filters: { company: frm.doc.company, is_group: 0 },
				}));
			}
		);
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("branch_manager", () => ({ filters: { status: "Active" } }));
		frm.set_query("service_manager", () => ({ filters: { status: "Active" } }));
	},

	branch_code(frm) {
		if (frm.doc.branch_code) {
			frm.set_value("branch_code", frm.doc.branch_code.toUpperCase());
		}
	},

	gstin(frm) {
		if (frm.doc.gstin && frm.doc.gstin.length >= 2) {
			frm.set_value("state_code", frm.doc.gstin.substring(0, 2));
		}
	},

	refresh(frm) {
		if (frm.doc.__islocal) return;
		frm.add_custom_button(__("Stock Explorer"), () =>
			frappe.set_route("a3-stock-explorer", { branch: frm.doc.branch })
		);
	},
});
