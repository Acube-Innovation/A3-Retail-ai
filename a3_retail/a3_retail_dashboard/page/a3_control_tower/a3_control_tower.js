// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Service Control Tower (scope 12.1).
 *
 * One screen that answers "what is happening right now": counters, the status
 * funnel, TAT compliance, the live job board, parts position, delivery delays,
 * technician load and the branch comparison strip.
 *
 * It refetches rather than patching state — a realtime nudge (debounced two
 * seconds) or the 30-second timer both just call the same endpoint again. That
 * is simpler than reconciling partial updates and impossible to get subtly wrong.
 */

frappe.pages["a3-control-tower"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Service Control Tower"),
		single_column: true,
	});
	new a3_retail.ControlTower(page);
};

a3_retail.ControlTower = class ControlTower {
	constructor(page) {
		this.page = page;
		this.branch = "";
		this.period = "today";
		this.refresh_seconds = 30;
		this.build();
		this.load();
		this.subscribe();
		this.timer = setInterval(() => this.load({ silent: true }), this.refresh_seconds * 1000);
		$(wrapperFor(page)).on("remove", () => clearInterval(this.timer));
	}

	build() {
		this.branch_field = this.page.add_field({
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
			change: () => {
				this.branch = this.branch_field.get_value();
				this.load();
			},
		});

		this.period_field = this.page.add_select(__("Period"), [
			{ label: __("Today"), value: "today" },
			{ label: __("Last 7 days"), value: "week" },
			{ label: __("Last 30 days"), value: "month" },
		]);
		this.period_field.on("change", () => {
			this.period = this.period_field.val();
			this.load();
		});

		this.page.set_secondary_action(__("Refresh"), () => this.load());

		this.page.main.html(`
			<div class="a3-tower">
				<div class="a3-tower-status text-muted small">${__("Loading…")}</div>
				<div class="a3-cards"></div>
				<div class="a3-row2">
					<div class="a3-panel a3-funnel"></div>
					<div class="a3-panel a3-tat"></div>
				</div>
				<div class="a3-panel a3-board"></div>
				<div class="a3-row4">
					<div class="a3-panel a3-parts"></div>
					<div class="a3-panel a3-delays"></div>
					<div class="a3-panel a3-load"></div>
				</div>
				<div class="a3-panel a3-strip"></div>
			</div>
		`);
		this.inject_styles();
	}

	inject_styles() {
		if (document.getElementById("a3-tower-styles")) return;
		$(`<style id="a3-tower-styles">
			.a3-tower { padding: 4px 0 40px; }
			.a3-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
				gap: 8px; margin-bottom: 12px; }
			.a3-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e5e7eb);
				border-radius: 8px; padding: 10px 12px; }
			.a3-card .label { font-size: 11px; color: var(--text-muted); text-transform: uppercase;
				letter-spacing: .4px; }
			.a3-card .value { font-size: 22px; font-weight: 600; line-height: 1.25; }
			.a3-card.warn .value { color: #b91c1c; }
			.a3-row2 { display: grid; grid-template-columns: 2fr 1fr; gap: 8px; }
			.a3-row4 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
			.a3-panel { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e5e7eb);
				border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; overflow-x: auto; }
			.a3-panel h5 { font-size: 12px; text-transform: uppercase; letter-spacing: .5px;
				color: var(--text-muted); margin: 0 0 8px; }
			.a3-panel table { width: 100%; font-size: 12px; border-collapse: collapse; }
			.a3-panel th { text-align: left; font-weight: 600; color: var(--text-muted);
				border-bottom: 1px solid var(--border-color, #e5e7eb); padding: 4px 6px; }
			.a3-panel td { padding: 4px 6px; border-bottom: 1px solid var(--border-color, #f1f5f9); }
			.a3-board tbody tr { cursor: pointer; }
			.a3-flag { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
			.a3-flag.green { background: #16a34a; } .a3-flag.amber { background: #f59e0b; }
			.a3-flag.red { background: #dc2626; } .a3-flag.grey { background: #9ca3af; }
			.a3-bar { background: #e5e7eb; border-radius: 3px; height: 8px; overflow: hidden; }
			.a3-bar span { display: block; height: 100%; background: #0F62FE; }
			.a3-num { text-align: right; font-variant-numeric: tabular-nums; }
		</style>`).appendTo(document.head);
	}

	subscribe() {
		frappe.realtime.on("a3_retail_dashboard_update", () => {
			clearTimeout(this.nudge);
			this.nudge = setTimeout(() => this.load({ silent: true }), 2000);
		});
	}

	load({ silent = false } = {}) {
		if (!silent) this.page.main.find(".a3-tower-status").text(__("Loading…"));
		frappe
			.call({
				method: "a3_retail.api.dashboard.control_tower",
				args: { branch: this.branch || null, period: this.period },
			})
			.then((response) => this.render(response.message))
			.catch(() => this.page.main.find(".a3-tower-status").text(__("Could not refresh.")));
	}

	render(data) {
		if (!data) return;
		this.page.main
			.find(".a3-tower-status")
			.text(__("● Live · updated {0}", [frappe.datetime.str_to_user(data.as_of)]));
		this.render_cards(data.counters);
		this.render_funnel(data.funnel);
		this.render_tat(data.tat);
		this.render_board(data.job_cards);
		this.render_parts(data.parts);
		this.render_delays(data.delivery_delays);
		this.render_load(data.technician_load);
		this.render_strip(data.branches);
	}

	render_cards(counters) {
		const cards = [
			[__("Received"), counters.received_today],
			[__("Ongoing"), counters.ongoing],
			[__("Awaiting Parts"), counters.awaiting_parts],
			[__("Ready"), counters.ready_for_delivery],
			[__("Delivered"), counters.delivered_today],
			[__("Delayed"), counters.delayed, counters.delayed > 0],
			[__("Service ₹"), format_currency(counters.service_revenue_today)],
			[__("Sales ₹"), format_currency(counters.sales_revenue_today)],
			[__("Footfall"), counters.footfall_today],
			[__("Open Tickets"), counters.open_tickets],
		];
		this.page.main.find(".a3-cards").html(
			cards
				.map(
					([label, value, warn]) => `
					<div class="a3-card ${warn ? "warn" : ""}">
						<div class="label">${label}</div>
						<div class="value">${value ?? 0}</div>
					</div>`
				)
				.join("")
		);
	}

	render_funnel(funnel) {
		const max = Math.max(1, ...funnel.map((row) => row.count));
		this.page.main.find(".a3-funnel").html(`
			<h5>${__("Job Card Funnel")}</h5>
			<table>${funnel
				.map(
					(row) => `<tr>
						<td style="width:38%">${__(row.status)}</td>
						<td><div class="a3-bar"><span style="width:${(row.count / max) * 100}%"></span></div></td>
						<td class="a3-num" style="width:44px">${row.count}</td>
					</tr>`
				)
				.join("")}</table>
		`);
	}

	render_tat(tat) {
		this.page.main.find(".a3-tat").html(`
			<h5>${__("TAT Compliance")}</h5>
			<div style="font-size:34px;font-weight:600">${tat.on_time}%</div>
			<div class="text-muted small">
				${__("On time")} ${tat.on_time}% · ${__("Breached")} ${tat.breached}%<br>
				${__("Average")} ${tat.avg_hours} ${__("hours")} · ${tat.delivered} ${__("delivered")}
			</div>
		`);
	}

	render_board(rows) {
		const head = [__("Job Card"), __("Customer"), __("Device"), __("IMEI"), __("Status"),
			__("Technician"), __("Age (h)"), __("Due"), ""];
		this.page.main.find(".a3-board").html(`
			<h5>${__("Live Job Cards")} (${rows.length})</h5>
			<table>
				<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
				<tbody>${rows
					.map(
						(row) => `<tr data-name="${frappe.utils.escape_html(row.name)}">
							<td>${row.name}</td>
							<td>${frappe.utils.escape_html(row.customer || "")}</td>
							<td>${frappe.utils.escape_html(row.device || "")}</td>
							<td>${row.imei || ""}</td>
							<td>${__(row.status)}</td>
							<td>${frappe.utils.escape_html(row.technician || "")}</td>
							<td class="a3-num">${row.age_hours}</td>
							<td>${row.due_on ? frappe.datetime.str_to_user(row.due_on) : ""}</td>
							<td><span class="a3-flag ${row.flag}"></span></td>
						</tr>`
					)
					.join("")}</tbody>
			</table>
		`);
		this.page.main.find(".a3-board tbody tr").on("click", function () {
			frappe.set_route("Form", "Service Job Card", $(this).data("name"));
		});
	}

	render_parts(rows) {
		this.page.main.find(".a3-parts").html(`
			<h5>${__("Parts Position")}</h5>
			<table>
				<thead><tr><th>${__("Part")}</th><th class="a3-num">${__("Req")}</th>
					<th class="a3-num">${__("Avail")}</th><th class="a3-num">${__("Short")}</th>
					<th>${__("ETA")}</th></tr></thead>
				<tbody>${rows
					.map(
						(row) => `<tr><td>${row.item}</td>
							<td class="a3-num">${row.required}</td>
							<td class="a3-num">${row.available}</td>
							<td class="a3-num">${row.short}</td>
							<td>${row.eta ? frappe.datetime.str_to_user(row.eta) : "—"}</td></tr>`
					)
					.join("")}</tbody>
			</table>
		`);
	}

	render_delays(rows) {
		this.page.main.find(".a3-delays").html(`
			<h5>${__("Delivery Delays")}</h5>
			<table>
				<thead><tr><th>${__("Job Card")}</th><th>${__("Promised")}</th>
					<th class="a3-num">${__("Days")}</th><th>${__("Reason")}</th></tr></thead>
				<tbody>${rows
					.map(
						(row) => `<tr><td>${row.job_card}</td>
							<td>${row.promised ? frappe.datetime.str_to_user(row.promised) : ""}</td>
							<td class="a3-num">${row.days_late}</td>
							<td>${frappe.utils.escape_html(row.reason || "")}</td></tr>`
					)
					.join("")}</tbody>
			</table>
		`);
	}

	render_load(rows) {
		this.page.main.find(".a3-load").html(`
			<h5>${__("Technician Load")}</h5>
			<table>
				<thead><tr><th>${__("Technician")}</th><th class="a3-num">${__("WIP")}</th>
					<th class="a3-num">${__("Cap")}</th><th>${__("Utilisation")}</th></tr></thead>
				<tbody>${rows
					.map(
						(row) => `<tr><td>${frappe.utils.escape_html(row.technician)}</td>
							<td class="a3-num">${row.wip}</td>
							<td class="a3-num">${row.capacity}</td>
							<td><div class="a3-bar"><span style="width:${Math.min(row.utilisation, 100)}%"></span></div></td>
						</tr>`
					)
					.join("")}</tbody>
			</table>
		`);
	}

	render_strip(rows) {
		const panel = this.page.main.find(".a3-strip");
		if (!rows || !rows.length) {
			panel.hide();
			return;
		}
		panel.show().html(`
			<h5>${__("Branch Comparison")}</h5>
			<table>
				<thead><tr><th>${__("Branch")}</th><th class="a3-num">${__("In")}</th>
					<th class="a3-num">${__("WIP")}</th><th class="a3-num">${__("Ready")}</th>
					<th class="a3-num">${__("Delayed")}</th><th class="a3-num">${__("TAT %")}</th>
					<th class="a3-num">${__("Service ₹")}</th><th class="a3-num">${__("Sales ₹")}</th>
					<th class="a3-num">${__("Footfall")}</th></tr></thead>
				<tbody>${rows
					.map(
						(row) => `<tr><td>${frappe.utils.escape_html(row.branch)}</td>
							<td class="a3-num">${row.in}</td>
							<td class="a3-num">${row.wip}</td>
							<td class="a3-num">${row.ready}</td>
							<td class="a3-num">${row.delayed}</td>
							<td class="a3-num">${row.tat_pct}</td>
							<td class="a3-num">${format_currency(row.service)}</td>
							<td class="a3-num">${format_currency(row.sales)}</td>
							<td class="a3-num">${row.footfall}</td></tr>`
					)
					.join("")}</tbody>
			</table>
		`);
	}
};

function wrapperFor(page) {
	return page.wrapper || page.main;
}
