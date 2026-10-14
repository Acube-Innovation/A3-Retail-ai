// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
// For license information, please see license.txt
/**
 * Change Posting Date, on a submitted Stock Entry.
 *
 * Stock does not always reach the screen the day it reaches the shelf, and a
 * bill held from the earlier day cannot be completed until the move sits on the
 * ledger before it. Correcting that by hand means cancel, amend, find the
 * "Edit Posting Date and Time" tick, re-enter the lines, submit — and the tick
 * is the step everyone misses, so the date silently snaps back to today.
 *
 * The button does the whole sequence in one go. It does not edit the date in
 * place: the entry is reversed and posted again, because the ledger rows the
 * original wrote belong to the day it was submitted on.
 */
frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (!frappe.model.can_cancel("Stock Entry")) return;

		frm.add_custom_button(__("Change Posting Date"), () => ask(frm));
	},
});

function ask(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Change Posting Date"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"This entry will be cancelled and posted again on the new date."
					+ " Both stay on file. The replacement gets its own number."
				)}</p>`,
			},
			{
				fieldname: "posting_date", fieldtype: "Date", reqd: 1,
				label: __("New Posting Date"), default: frm.doc.posting_date,
				max_date: frappe.datetime.get_today(),
			},
			{
				fieldname: "posting_time", fieldtype: "Time",
				label: __("Posting Time"), default: frm.doc.posting_time,
			},
		],
		primary_action_label: __("Move it"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "a3_retail.api.stock_desk.redate",
				args: { name: frm.doc.name, ...values },
				freeze: true,
				freeze_message: __("Re-posting…"),
			}).then((r) => {
				if (!r || !r.message) return dialog.enable_primary_action();
				dialog.hide();
				frappe.show_alert({
					message: __("Now on {0} as {1}.", [
						frappe.datetime.str_to_user(r.message.posting_date),
						r.message.name,
					]),
					indicator: "green",
				});
				frappe.set_route("Form", "Stock Entry", r.message.name);
			}).catch(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
}
