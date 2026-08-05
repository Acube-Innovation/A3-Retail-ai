// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Technician Workbench (scope 3.10).
 *
 * A kanban of the logged-in technician's own job cards, with the actions a
 * technician actually needs mid-repair and a timer that writes real minutes
 * into Job Card Labour.
 */

frappe.pages["a3-technician-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Technician Workbench"),
		single_column: true,
	});
	new a3_retail.TechnicianWorkbench(page);
};

const WORKBENCH_COLUMNS = [
	"Open",
	"Under Diagnosis",
	"Estimate Pending",
	"Estimate Sent",
	"Estimate Approved",
	"Awaiting Parts",
	"In Progress",
	"Repair Completed",
	"QC Failed",
	"QC Passed",
	"Ready for Delivery",
];

a3_retail.TechnicianWorkbench = class TechnicianWorkbench {
	constructor(page) {
		this.page = page;
		this.timers = {};
		this.page.set_primary_action(__("Refresh"), () => this.load());
		this.page.main.html('<div class="a3-workbench"><div id="a3-wb-board" class="a3-board"></div></div>');
		this.load();
		frappe.realtime.on("a3_retail_dashboard_update", frappe.utils.debounce(() => this.load(), 2000));
	}

	async load() {
		const { message } = await frappe.call({ method: "a3_retail.a3_retail_service.parts.my_job_cards" });
		this.data = message;

		if (!message.technician) {
			document.getElementById("a3-wb-board").innerHTML =
				`<div class="a3-card">${__("Your user is not linked to an Employee record.")}</div>`;
			return;
		}

		this.page.set_indicator(
			__("{0} open · {1} delayed", [message.total, message.delayed]),
			message.delayed ? "red" : "green"
		);
		this.paint();
	}

	paint() {
		const columns = this.data.columns || {};
		const html = WORKBENCH_COLUMNS.filter((s) => (columns[s] || []).length)
			.map(
				(status) => `
			<div class="a3-column">
				<div class="a3-column-head">
					${__(status)} <span class="a3-pill grey">${columns[status].length}</span>
				</div>
				${columns[status].map((jc) => this.card(jc)).join("")}
			</div>`
			)
			.join("");

		document.getElementById("a3-wb-board").innerHTML =
			html || `<div class="a3-card">${__("No open job cards assigned to you.")}</div>`;
		this.bind_cards();
	}

	card(jc) {
		const due = jc.sla_due_on ? frappe.datetime.str_to_user(jc.sla_due_on) : "—";
		return `
		<div class="a3-jc-card ${jc.is_delayed ? "delayed" : ""}" data-jc="${jc.name}">
			<div class="a3-jc-head">
				<b>${jc.name}</b>
				<span class="a3-pill ${jc.is_delayed ? "red" : "grey"}">${jc.priority}</span>
			</div>
			<div class="a3-muted">${jc.customer_name || ""} · ${jc.device_model || ""}</div>
			<div class="a3-jc-complaint">${frappe.utils.escape_html(jc.complaint_description || "")}</div>
			<div class="a3-muted">${__("Due")}: ${due}${
				jc.is_delayed ? ` · <span class="a3-late">${__("late {0}h", [jc.delay_hours])}</span>` : ""
			}</div>
			<div class="a3-jc-actions">
				<button data-act="open">${__("Open")}</button>
				<button data-act="timer" class="a3-timer" data-jc="${jc.name}">▶ ${__("Start")}</button>
				<button data-act="parts">${__("Parts")}</button>
				<button data-act="estimate">${__("Estimate")}</button>
				<button data-act="done">${__("Mark Done")}</button>
			</div>
		</div>`;
	}

	bind_cards() {
		document.querySelectorAll(".a3-jc-card").forEach((card) => {
			const jc = card.dataset.jc;
			card.querySelectorAll("button[data-act]").forEach((btn) =>
				btn.addEventListener("click", (e) => {
					e.stopPropagation();
					this.act(btn.dataset.act, jc, btn);
				})
			);
		});
	}

	act(action, job_card, btn) {
		const handlers = {
			open: () => frappe.set_route("Form", "Service Job Card", job_card),
			timer: () => this.toggle_timer(job_card, btn),
			parts: () => this.parts_dialog(job_card),
			estimate: () => this.create_estimate(job_card),
			done: () => this.set_status(job_card, "Repair Completed"),
		};
		(handlers[action] || (() => {}))();
	}

	/** Wall-clock timer; on stop the elapsed minutes go into Job Card Labour. */
	toggle_timer(job_card, btn) {
		const running = this.timers[job_card];
		if (running) {
			clearInterval(running.tick);
			const minutes = Math.max(1, Math.round((Date.now() - running.started) / 60000));
			delete this.timers[job_card];
			frappe
				.call({
					method: "a3_retail.a3_retail_service.parts.log_work_minutes",
					args: { job_card, minutes },
				})
				.then(() => {
					frappe.show_alert({
						message: __("{0} minutes logged on {1}", [minutes, job_card]),
						indicator: "green",
					});
					this.load();
				});
			return;
		}

		this.timers[job_card] = {
			started: Date.now(),
			tick: setInterval(() => {
				const mins = Math.floor((Date.now() - this.timers[job_card].started) / 60000);
				btn.textContent = `■ ${mins}m`;
			}, 10000),
		};
		btn.textContent = "■ 0m";
	}

	async parts_dialog(job_card) {
		const doc = await frappe.db.get_doc("Service Job Card", job_card);
		const rows = (doc.parts || [])
			.map(
				(p) => `<tr>
					<td>${p.item_name || p.item_code}</td>
					<td class="num">${p.qty}</td>
					<td class="num">${p.available_qty}</td>
					<td>${p.part_status}</td>
					<td><button class="btn btn-xs btn-default" data-row="${p.name}">${__("Request")}</button></td>
				</tr>`
			)
			.join("");

		const dialog = new frappe.ui.Dialog({
			title: __("Parts for {0}", [job_card]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "table",
					options: `<table class="a3-table"><thead><tr>
						<th>${__("Item")}</th><th class="num">${__("Qty")}</th>
						<th class="num">${__("Available")}</th><th>${__("Status")}</th><th></th>
					</tr></thead><tbody>${rows || `<tr><td colspan="5">${__("No parts added")}</td></tr>`}</tbody></table>`,
				},
			],
			primary_action_label: __("Issue Available Parts"),
			primary_action: () =>
				frappe
					.call({ method: "a3_retail.a3_retail_service.parts.issue_parts", args: { job_card } })
					.then(({ message }) => {
						frappe.show_alert({
							message: __("{0} part(s) issued", [message.issued]),
							indicator: "green",
						});
						dialog.hide();
						this.load();
					}),
		});

		dialog.show();
		dialog.$wrapper.find("button[data-row]").on("click", (e) => {
			const row_name = e.currentTarget.dataset.row;
			frappe
				.call({
					method: "a3_retail.a3_retail_service.parts.request_part",
					args: { job_card, row_name, source: "auto" },
				})
				.then(({ message }) => {
					frappe.show_alert({
						message: __("Raised: {0}", [message.stock_request || message.material_request || "—"]),
						indicator: "blue",
					});
					dialog.hide();
					this.load();
				});
		});
	}

	create_estimate(job_card) {
		frappe
			.call({
				method:
					"a3_retail.a3_retail_service.doctype.service_estimate.service_estimate.create_from_job_card",
				args: { job_card },
			})
			.then(({ message }) => frappe.set_route("Form", "Service Estimate", message));
	}

	set_status(job_card, status) {
		frappe
			.call({
				method: "a3_retail.a3_retail_service.doctype.service_job_card.service_job_card.set_status",
				args: { job_card, status },
			})
			.then(() => this.load());
	}
};
