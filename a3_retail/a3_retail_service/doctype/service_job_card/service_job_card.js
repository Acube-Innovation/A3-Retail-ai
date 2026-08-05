// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors

frappe.ui.form.on("Service Job Card", {
	setup(frm) {
		frm.set_query("assigned_technician", () => ({
			query: "erpnext.controllers.queries.employee_query",
			filters: { branch: frm.doc.branch, status: "Active" },
		}));
		frm.set_query("device_model", () => ({ filters: { brand: frm.doc.brand, is_active: 1 } }));
		frm.set_query("item_code", "parts", () => ({ filters: { item_group: "Spare Parts" } }));
		frm.set_query("service_item", "labour", () => ({ filters: { a3_is_service_item: 1 } }));
	},

	refresh(frm) {
		frm.trigger("render_status_actions");
		frm.trigger("render_sla_banner");

		if (frm.doc.docstatus === 1 && !frm.is_new()) {
			frm.add_custom_button(__("Assign Technician"), () => frm.trigger("assign_technician"), __("Actions"));
			frm.add_custom_button(__("Take Advance"), () => frm.trigger("take_advance"), __("Actions"));
		}
	},

	/** One button per legal next state, straight from the server-side map. */
	async render_status_actions(frm) {
		if (frm.doc.docstatus !== 1) return;

		const { message: allowed } = await frappe.call({
			method: "a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.get_allowed_transitions",
			args: { job_card: frm.doc.name },
		});

		(allowed || []).forEach((status) => {
			frm.add_custom_button(
				__(status),
				() => frm.trigger("prompt_status_change").then(() => frm.events.change_status(frm, status)),
				__("Move To")
			);
		});
	},

	prompt_status_change() {
		return Promise.resolve();
	},

	change_status(frm, status) {
		const needs_reason = status === "On Hold";
		const run = (remarks) =>
			frappe
				.call({
					method: "a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.set_status",
					args: { job_card: frm.doc.name, status, remarks },
					freeze: true,
					freeze_message: __("Updating status…"),
				})
				.then(() => frm.reload_doc());

		if (!needs_reason) return run();

		frappe.prompt(
			{ fieldname: "remarks", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			(values) => run(values.remarks),
			__("Put On Hold")
		);
	},

	render_sla_banner(frm) {
		frm.dashboard.clear_headline();
		if (!frm.doc.sla_due_on || frm.doc.docstatus !== 1) return;

		if (frm.doc.is_delayed) {
			frm.dashboard.set_headline(
				__("Delayed by {0} working hours — escalation {1}", [
					frm.doc.delay_hours,
					frm.doc.escalation_level,
				]),
				"red"
			);
		} else {
			frm.dashboard.set_headline(
				__("Due {0}", [frappe.datetime.str_to_user(frm.doc.sla_due_on)]),
				"blue"
			);
		}
	},

	assign_technician(frm) {
		frappe.prompt(
			{
				fieldname: "technician",
				fieldtype: "Link",
				options: "Employee",
				label: __("Technician"),
				reqd: 1,
				get_query: () => ({ filters: { branch: frm.doc.branch, status: "Active" } }),
			},
			(values) =>
				frappe
					.call({
						method:
							"a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.assign_technician",
						args: { job_card: frm.doc.name, technician: values.technician },
					})
					.then(() => frm.reload_doc()),
			__("Assign Technician")
		);
	},

	brand(frm) {
		frm.set_value("device_model", null);
	},

	async imei_1(frm) {
		if (!frm.doc.imei_1 || frm.doc.imei_1.length < 15) return;

		const { message } = await frappe.call({
			method: "a3_retail.overrides.serial_no.lookup_imei",
			args: { imei: frm.doc.imei_1 },
		});

		if (message && message.found) {
			frm.dashboard.set_headline(
				__("Sold by us — {0}, warranty state: {1}", [message.item_name, message.warranty_state]),
				message.warranty_state.includes("Warranty") ? "green" : "orange"
			);
		}
	},
});

frappe.ui.form.on("Job Card Part", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;
		frappe.db.get_value("Item", row.item_code, "standard_rate").then(({ message }) => {
			frappe.model.set_value(cdt, cdn, "rate", message.standard_rate);
		});
	},
});
