// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * POS extensions P1–P9 (scope 2.2).
 *
 * ERPNext's POS is not a Form, so `frappe.ui.form.on` is unavailable. The page
 * is not forked either — we wait for `cur_pos` and wrap the specific methods we
 * need, keeping everything under `window.a3_retail_pos`.
 */

frappe.provide("a3_retail_pos");

a3_retail_pos = {
	installed: false,

	/** Poll briefly for cur_pos, then patch it once. */
	init() {
		if (this.installed) return;
		if (frappe.get_route()[0] !== "point-of-sale") return;

		const wait = setInterval(() => {
			if (!window.cur_pos || !cur_pos.cart) return;
			clearInterval(wait);
			this.install(cur_pos);
		}, 300);

		// Give up quietly if POS never finishes loading.
		setTimeout(() => clearInterval(wait), 20000);
	},

	install(pos) {
		this.pos = pos;
		this.patch_item_add();
		this.patch_customer_field();
		this.patch_submit();
		this.installed = true;
	},

	// ------------------------------------------------------------------ P1/P4/P8
	patch_item_add() {
		const original = this.pos.cart.add_item?.bind(this.pos.cart);
		if (!original) return;

		this.pos.cart.add_item = async (item) => {
			const result = original(item);

			const is_device = await frappe.db.get_value("Item", item.item_code, "a3_is_device");
			if (is_device?.message?.a3_is_device) {
				await this.prompt_imei(item);       // P1
				await this.offer_ew_plans(item);     // P4
			}
			if (flt(item.actual_qty) <= 0) {
				await this.show_other_branches(item); // P8
			}
			this.render_offer_badge();               // P3
			return result;
		};
	},

	/** P1 — force an IMEI scan for device lines, validated against the warehouse. */
	prompt_imei(item) {
		return new Promise((resolve) => {
			const dialog = new frappe.ui.Dialog({
				title: __("Scan IMEI — {0}", [item.item_name || item.item_code]),
				fields: [
					{
						fieldname: "imei",
						fieldtype: "Data",
						label: __("IMEI"),
						reqd: 1,
						description: __("Scan the box barcode, or dial *#06# on the device"),
					},
					{ fieldname: "status", fieldtype: "HTML" },
				],
				primary_action_label: __("Add"),
				primary_action: async ({ imei }) => {
					const { message } = await frappe.call({
						method: "a3_retail.overrides.sales_invoice.validate_pos_serial",
						args: {
							item_code: item.item_code,
							serial_no: imei,
							warehouse: this.pos.frm?.doc?.set_warehouse || item.warehouse,
						},
					});

					if (!message.valid) {
						dialog.set_df_property(
							"status", "options",
							`<div class="a3-pos-error">${frappe.utils.escape_html(message.reason)}</div>`
						);
						return;
					}

					await this.pos.frm.script_manager.trigger("serial_no", item.doctype, item.name);
					frappe.model.set_value(item.doctype, item.name, "serial_no", message.serial_no);
					dialog.hide();
					resolve(message.serial_no);
				},
			});

			dialog.show();
			// Keyboard-wedge scanners need the field focused and submit on Enter.
			const input = dialog.get_field("imei").$input.get(0);
			setTimeout(() => input.focus(), 100);
			a3_retail.bind_scanner(input, () => dialog.primary_action(dialog.get_values()));
		});
	},

	/** P4 — upsell a matching extended-warranty plan right after the device. */
	async offer_ew_plans(item) {
		const { message: plans } = await frappe.call({
			method: "a3_retail.overrides.sales_invoice.suggest_ew_plans",
			args: { item_code: item.item_code },
		});
		if (!plans || !plans.length) return;

		const options = plans.map((p) => ({
			label: `${p.plan_name} — ${a3_retail.money(p.plan_price)}`,
			value: p.plan_item,
		}));

		frappe.prompt(
			[
				{
					fieldname: "plan",
					fieldtype: "Select",
					label: __("Protection plan"),
					options: [{ label: __("No thanks"), value: "" }, ...options],
				},
			],
			({ plan }) => {
				if (plan) this.pos.cart.add_item({ item_code: plan, qty: 1 });
			},
			__("Add protection?"),
			__("Add")
		);
	},

	/** P8 — no stock here: show which branch has it and offer a transfer. */
	async show_other_branches(item) {
		const { message: rows } = await frappe.call({
			method: "a3_retail.overrides.sales_invoice.cross_branch_availability",
			args: { item_code: item.item_code },
		});
		if (!rows || !rows.length) return;

		const chips = rows
			.map((r) => `<span class="a3-pill green">${r.branch}: ${r.available}</span>`)
			.join(" ");

		frappe.msgprint({
			title: __("Out of stock here"),
			message: `<div>${chips}</div>`,
			primary_action: {
				label: __("Raise Stock Request"),
				action: () => frappe.new_doc("Stock Request", { }),
			},
		});
	},

	/** P3 — show what the customer saved, per line and in total. */
	render_offer_badge() {
		const doc = this.pos.frm?.doc;
		if (!doc) return;

		const saved = (doc.items || []).reduce(
			(total, row) => total + (flt(row.price_list_rate) - flt(row.rate)) * flt(row.qty),
			0
		);

		let banner = document.getElementById("a3-pos-savings");
		if (!banner) {
			banner = document.createElement("div");
			banner.id = "a3-pos-savings";
			banner.className = "a3-pos-savings";
			document.querySelector(".point-of-sale-app")?.prepend(banner);
		}
		banner.style.display = saved > 0 ? "block" : "none";
		banner.textContent = saved > 0 ? __("You saved {0}", [a3_retail.money(saved)]) : "";
	},

	/** P2 — customer quick-create straight from a 10-digit mobile number. */
	patch_customer_field() {
		const selector = this.pos.customer_selector;
		if (!selector) return;

		const field = selector.$component?.find('[data-fieldname="customer"] input').get(0);
		if (!field) return;

		field.addEventListener("change", async (e) => {
			const value = (e.target.value || "").replace(/\D/g, "");
			if (value.length !== 10) return;

			const { message } = await frappe.call({
				method: "a3_retail.api.customer.find_by_mobile",
				args: { mobile_no: value },
			});

			if (message) {
				this.pos.on_customer_change(message.name);
				return;
			}

			frappe.prompt(
				[
					{ fieldname: "customer_name", fieldtype: "Data", label: __("Name"), reqd: 1 },
					{ fieldname: "optin", fieldtype: "Check", label: __("Marketing opt-in"), default: 1 },
				],
				async ({ customer_name, optin }) => {
					const { message: created } = await frappe.call({
						method: "a3_retail.api.customer.get_or_create",
						args: { mobile_no: value, customer_name, marketing_optin: optin },
					});
					this.pos.on_customer_change(created.name);
				},
				__("New customer {0}", [value]),
				__("Create")
			);
		});
	},

	/** P7 min-price guard is server-side; P9 print + WhatsApp fire after submit. */
	patch_submit() {
		const original = this.pos.frm?.script_manager;
		frappe.ui.form.on("POS Invoice", {
			after_submit: (frm) => {
				frappe.utils.print(
					"POS Invoice", frm.doc.name, "A3 POS Receipt", frappe.boot.lang
				);
			},
		});
		return original;
	},
};

$(document).on("page-change", () => a3_retail_pos.init());
