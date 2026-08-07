// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * One invoice, read-only.
 *
 * Read-only is the point: a bill that has been submitted is a document somebody
 * has already been given. Editing is offered only while it is a draft, and it
 * happens at the sales counter, which is the screen that knows how to price a
 * basket. Everything else here — print, collect a payment, send it — is an
 * action *on* the bill rather than a change to it.
 */

window.INVOICE = (function () {
	const state = { name: "", branch: "", company: "", data: null };
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);

	function esc(value) {
		const node = document.createElement("div");
		node.textContent = value == null ? "" : String(value);
		return node.innerHTML;
	}

	function day(value) {
		if (!value) return "";
		const date = new Date(String(value).slice(0, 10) + "T00:00:00");
		return isNaN(date) ? String(value)
			: date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
	}

	function stamp(value) {
		if (!value) return "";
		const date = new Date(String(value).replace(" ", "T"));
		return isNaN(date) ? String(value)
			: date.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric",
			                                 hour: "2-digit", minute: "2-digit" });
	}

	function toast(text, kind) {
		const box = document.createElement("div");
		box.className = "toast" + (kind ? " " + kind : "");
		box.textContent = text;
		document.body.appendChild(box);
		setTimeout(() => box.remove(), 3600);
	}

	function payTone(status) {
		return { "Paid": "pill-good", "Partially Paid": "pill-warn", "Unpaid": "pill-bad",
		         "Refunded": "pill-purple" }[status] || "pill-sky";
	}

	function docTone(status) {
		return { "Submitted": "pill-good", "Draft": "pill-sky", "Cancelled": "pill-bad" }[status]
			|| "pill-sky";
	}

	function icon(name) {
		const paths = {
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			pencil: '<path d="M4 20h4L20 8l-4-4L4 16z"/><path d="M14 6l4 4"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			chat: '<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
			mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
			back: '<path d="M19 12H5"/><path d="m11 18-6-6 6-6"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	/** One print path for the whole application: the counter's own link. */
	function print() {
		window.open(state.data.print_url, "_blank");
	}

	// ---------------------------------------------------------------- load
	async function load() {
		try {
			state.data = await A3.call("a3_retail.api.bills.invoice", { name: state.name });
			paint();
		} catch (error) {
			$("body").innerHTML = `<section class="svc-panel inv-error">
				<h2>Could not open ${esc(state.name)}</h2>
				<p>${esc(error.message)}</p>
				<a class="btn btn-outline" href="/branch/bills">← Back to Bills</a></section>`;
		}
	}

	function paint() {
		const data = state.data;
		const totals = data.totals;

		$("title").textContent = "Invoice #" + data.name;
		$("subtitle").innerHTML = `<span class="pill ${docTone(data.status)}">${esc(data.status)}</span>
			<span class="pill ${payTone(data.payment_status)}">${esc(data.payment_status)}</span>`;

		$("top-actions").insertAdjacentHTML("afterbegin", `
			<button class="btn btn-primary btn-icon" id="print-top">${icon("print")} Print Invoice</button>
			${data.editable
				? `<a class="btn btn-outline btn-icon" href="/branch/sales?invoice=${
					encodeURIComponent(data.name)}">${icon("pencil")} Edit</a>` : ""}`);
		$("print-top").addEventListener("click", print);

		$("body").innerHTML = `
			<section class="svc-panel inv-sheet">
				<header class="inv-head">
					<div class="inv-brand">
						<div class="inv-brand-name">A3 Retail</div>
						<div class="inv-brand-sub">BY ACUBE INNOVATIONS</div>
						<div class="inv-brand-line">${esc(data.company || "")}</div>
					</div>
					<dl class="inv-meta">
						<div><dt>Branch</dt><dd>${esc(data.branch || "—")}</dd></div>
						<div><dt>Invoice</dt><dd>${esc(data.name)}</dd></div>
						<div><dt>Invoice Date</dt><dd>${esc(day(data.posting_date))}</dd></div>
						${data.sales_person
							? `<div><dt>Sales Person</dt><dd>${esc(data.sales_person)}</dd></div>` : ""}
					</dl>
				</header>

				<div class="inv-parties">
					<div class="inv-party">
						<h3>Customer</h3>
						<div class="inv-party-name">${esc(data.customer.customer_name)}</div>
						${line(data.customer.mobile_no)}
						${line(data.customer.email)}
						${line(data.customer.address)}
						${data.customer.gstin ? line("GSTIN: " + data.customer.gstin) : ""}
					</div>
					${data.device ? `
					<div class="inv-party">
						<h3>Device</h3>
						<div class="inv-party-name">${esc(data.device.item_name)}</div>
						${data.device.model ? line("Model: " + data.device.model) : ""}
						${data.device.imei ? line("IMEI: " + data.device.imei) : ""}
						${data.device.serial_no && data.device.serial_no !== data.device.imei
							? line("Serial: " + data.device.serial_no) : ""}
						<div class="inv-line"><b class="${
							data.device.warranty === "Out of Warranty" ? "warn-red" : "good"}">${
							esc(data.device.warranty)}</b>${data.device.warranty_expiry
								? ` · until ${esc(day(data.device.warranty_expiry))}` : ""}</div>
					</div>` : ""}
				</div>

				<div class="inv-items-wrap">
					<table class="bill-table inv-items">
						<thead><tr>
							<th>#</th><th>Item / Service</th><th>HSN</th><th>IMEI / Serial</th>
							<th class="num">Qty</th><th class="num">Rate</th><th class="num">Discount</th>
							<th class="num">Tax</th><th class="num">Amount</th>
						</tr></thead>
						<tbody>${data.items.map((row) => `
							<tr>
								<td class="num">${row.idx}</td>
								<td><b>${esc(row.item_name)}</b><small>${esc(row.item_code)}</small></td>
								<td class="nowrap">${esc(row.hsn || "—")}</td>
								<td class="nowrap">${row.serials.length
									? esc(row.serials.join(", ")) : "—"}</td>
								<td class="num">${row.qty}</td>
								<td class="num">${money(row.rate)}</td>
								<td class="num">${row.discount ? "- " + money(row.discount) : "—"}</td>
								<td class="num">${row.tax_rate ? row.tax_rate + "%" : "—"}</td>
								<td class="num strong">${money(row.amount)}</td>
							</tr>`).join("")}</tbody>
					</table>
				</div>

				<div class="inv-bottom">
					<div class="inv-notes">
						${data.notes ? panelBlock("Notes", esc(data.notes)) : ""}
						${data.terms ? panelBlock("Terms &amp; Conditions", esc(data.terms)) : ""}
						${panelBlock("Additional information", `
							<div class="sum-row"><span>Branch</span><b>${esc(data.branch || "—")}</b></div>
							${data.warehouse
								? `<div class="sum-row"><span>Warehouse</span><b>${esc(data.warehouse)}</b></div>` : ""}
							${data.sales_person
								? `<div class="sum-row"><span>Sales Person</span><b>${esc(data.sales_person)}</b></div>` : ""}
							${data.payment_terms
								? `<div class="sum-row"><span>Payment Terms</span><b>${esc(data.payment_terms)}</b></div>` : ""}`)}
					</div>

					<div class="inv-totals">
						<div class="tr"><span>Subtotal</span><span>${money(totals.subtotal)}</span></div>
						<div class="tr"><span>Discount</span><span>${
							totals.discount ? "- " + money(totals.discount) : money(0)}</span></div>
						<div class="tr"><span>Taxable Amount</span><span>${money(totals.taxable)}</span></div>
						${totals.taxes.map((tax) => `<div class="tr"><span>${esc(tax.label)}${
							tax.rate ? " (" + tax.rate + "%)" : ""}</span>
							<span>${money(tax.amount)}</span></div>`).join("")}
						<div class="tr tr-grand"><span>Grand Total</span>
							<span>${money(totals.payable)}</span></div>
						<div class="tr"><span>Paid</span><span class="good">${money(totals.paid)}</span></div>
						<div class="tr tr-balance"><span>Balance Due</span>
							<span class="${totals.balance > 0 ? "warn-red" : "good"}">${
								money(totals.balance)}</span></div>
					</div>
				</div>
			</section>

			<section class="inv-side">
				${paymentsPanel(data)}
				${data.service ? servicePanel(data.service) : ""}
				${data.warranty ? warrantyPanel(data.warranty) : ""}
				${timelinePanel(data.timeline)}
			</section>

			<section class="inv-actions">
				<a class="btn btn-quiet btn-icon" href="/branch/bills">${icon("back")} Back to Bills</a>
				<button class="btn btn-primary btn-icon" id="print-bottom">${icon("print")} Print Invoice</button>
				${data.editable
					? `<a class="btn btn-outline btn-icon" href="/branch/sales?invoice=${
						encodeURIComponent(data.name)}">${icon("pencil")} Edit Invoice</a>` : ""}
				${totals.balance > 0 && data.status === "Submitted"
					? `<button class="btn btn-orange btn-icon" id="collect">${icon("cash")} Collect Payment</button>`
					: ""}
				<button class="btn btn-quiet btn-icon" data-send="WhatsApp">${icon("chat")} Send WhatsApp</button>
				<button class="btn btn-quiet btn-icon" data-send="Email">${icon("mail")} Send Email</button>
			</section>`;

		$("print-bottom").addEventListener("click", print);
		if ($("collect")) $("collect").addEventListener("click", askPayment);
		document.querySelectorAll("[data-send]").forEach((node) => {
			node.addEventListener("click", () => send(node.dataset.send));
		});
	}

	function line(value) {
		return value ? `<div class="inv-line">${esc(value)}</div>` : "";
	}

	function panelBlock(title, body) {
		return `<div class="inv-block"><h3>${title}</h3><div>${body}</div></div>`;
	}

	function paymentsPanel(data) {
		const rows = data.payments;
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Payment Summary</h2>
				<span class="pill ${payTone(data.payment_status)}">${esc(data.payment_status)}</span></div>
			${rows.length ? `<div class="row-list">${rows.map((row) => `
				<div class="row-line">
					<span class="row-main"><b>${esc(row.name)}</b><small>${esc(row.reference || "")}</small></span>
					<span class="row-date">${esc(day(row.date))}</span>
					<span class="row-amount">${money(row.amount)}</span>
					<span class="pill pill-sky">${esc(row.mode || "—")}</span>
				</div>`).join("")}</div>`
				: '<div class="cust-none">Nothing has been paid against this bill yet.</div>'}
		</div>`;
	}

	function servicePanel(service) {
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Service Booking</h2>
				<span class="pill pill-sky">${esc(service.status)}</span></div>
			<div class="sum-row"><span>Booking</span><b>${esc(service.job_card)}</b></div>
			${service.repair_category
				? `<div class="sum-row"><span>Service</span><b>${esc(service.repair_category)}</b></div>` : ""}
			${service.device_model
				? `<div class="sum-row"><span>Device</span><b>${esc(service.device_model)}</b></div>` : ""}
			${service.imei ? `<div class="sum-row"><span>IMEI</span><b>${esc(service.imei)}</b></div>` : ""}
			${service.technician
				? `<div class="sum-row"><span>Technician</span><b>${esc(service.technician)}</b></div>` : ""}
			${service.promised
				? `<div class="sum-row"><span>Expected</span><b>${esc(stamp(service.promised))}</b></div>` : ""}
			${service.delivered
				? `<div class="sum-row"><span>Delivered</span><b>${esc(stamp(service.delivered))}</b></div>` : ""}
		</div>`;
	}

	function warrantyPanel(warranty) {
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Warranty</h2>
				<span class="pill ${warranty.status === "Active" ? "pill-good" : "pill-bad"}">${
					esc(warranty.status)}</span></div>
			${warranty.plan ? `<div class="sum-row"><span>Plan</span><b>${esc(warranty.plan)}</b></div>` : ""}
			${warranty.type ? `<div class="sum-row"><span>Type</span><b>${esc(warranty.type)}</b></div>` : ""}
			${warranty.start ? `<div class="sum-row"><span>From</span><b>${esc(day(warranty.start))}</b></div>` : ""}
			${warranty.end
				? `<div class="sum-row"><span>Valid until</span><b>${esc(day(warranty.end))}</b></div>` : ""}
		</div>`;
	}

	function timelinePanel(events) {
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Timeline</h2></div>
			<ol class="inv-timeline">${events.map((event) => `
				<li><span class="dot"></span>
					<span class="tl-label">${esc(event.label)}</span>
					<span class="tl-at">${esc(stamp(event.at))}</span>
					${event.note ? `<span class="tl-note">${esc(event.note)}</span>` : ""}
				</li>`).join("")}</ol>
		</div>`;
	}

	// ------------------------------------------------------------- actions
	function askPayment() {
		const balance = state.data.totals.balance;
		$("payment-note").textContent =
			`${state.data.name} · ${state.data.customer.customer_name} · ${money(balance)} still owed`;
		$("pay-amount").value = balance.toFixed(2);
		$("pay-amount").max = balance;
		$("payment-modal").hidden = false;
		$("pay-amount").focus();
	}

	async function takePayment() {
		try {
			const result = await A3.call("a3_retail.api.bills.collect_payment", {
				name: state.name,
				amount: Number($("pay-amount").value) || 0,
				mode_of_payment: $("pay-mode").value,
				reference: $("pay-reference").value.trim() || null,
			});
			$("payment-modal").hidden = true;
			toast(`${money(result.paid)} taken — ${result.payment_status.toLowerCase()}.`, "ok");
			$("top-actions").querySelectorAll("#print-top, .btn-outline").forEach((n) => n.remove());
			load();
		} catch (error) {
			toast(error.message, "error");
		}
	}

	async function send(channel) {
		try {
			const result = await A3.call("a3_retail.api.bills.send", { name: state.name, channel });
			toast(result.sent ? channel + " sent." : channel + " was not sent — check messaging "
				+ "settings.", result.sent ? "ok" : "error");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	// --------------------------------------------------------------- start
	function start(options) {
		state.name = options.name;
		state.branch = options.branch;
		state.company = options.company;

		if (!state.name) {
			window.location = "/branch/bills";
			return;
		}

		$("pay-save").addEventListener("click", takePayment);
		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		load();
	}

	return { start, state };
})();
