// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * One service booking.
 *
 * The view the service desk did not have: the device, what the customer said,
 * what was done to it, what it costs, and everything that has happened to it
 * since it came across the counter. Read-only about the repair itself — the
 * work is done at the service counter and by the technician's own screen; what
 * happens here is what happens *to* a booking: print it, take money against it,
 * tell the customer where it is, or write a note the next person will read.
 */

window.BOOKING = (function () {
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
		setTimeout(() => box.remove(), 4200);
	}

	function icon(name) {
		const paths = {
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 21H10L4.3 15.3a4 4 0 0 1 5-5z"/><path d="M9 9l6 6"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			chat: '<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
			mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
			note: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
			key: '<circle cx="8" cy="14" r="4"/><path d="m11 11 8-8 2 2-2 2 2 2-2 2-2-2-2 2z"/>',
			file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
			back: '<path d="M19 12H5"/><path d="m11 18-6-6 6-6"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	// ---------------------------------------------------------------- load
	async function load() {
		try {
			state.data = await A3.call("a3_retail.api.bookings.booking", { name: state.name });
			paint();
		} catch (error) {
			$("body").innerHTML = `<section class="svc-panel inv-error">
				<h2>Could not open ${esc(state.name)}</h2>
				<p>${esc(error.message)}</p>
				<a class="btn btn-outline" href="/retail/bookings">← Back to Bookings</a></section>`;
		}
	}

	function paint() {
		const data = state.data;
		const totals = data.totals;

		$("title").textContent = "Booking " + data.name;
		$("subtitle").innerHTML = `<span class="pill ${data.tone}">${esc(data.status)}</span>
			${data.is_delayed ? '<span class="pill pill-bad">Running late</span>' : ""}
			${data.priority && data.priority !== "Normal"
				? `<span class="pill pill-warn">${esc(data.priority)}</span>` : ""}
			<span class="topbar-when">Booked ${esc(stamp(data.received_on))}</span>`;

		$("top-actions").insertAdjacentHTML("afterbegin", `
			<button class="btn btn-primary btn-icon" id="print-top">${icon("print")} Print</button>
			<a class="btn btn-outline btn-icon" href="/retail/service?booking=${
				encodeURIComponent(data.name)}">${icon("wrench")} Open at the counter</a>`);
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
						<div><dt>Booking</dt><dd>${esc(data.name)}</dd></div>
						<div><dt>Booked in</dt><dd>${esc(stamp(data.received_on))}</dd></div>
						<div><dt>Promised</dt><dd class="${data.is_delayed ? "warn-red" : ""}">${
							esc(stamp(data.promised)) || "—"}</dd></div>
						${data.received_by
							? `<div><dt>Taken in by</dt><dd>${esc(data.received_by)}</dd></div>` : ""}
					</dl>
				</header>

				<div class="inv-parties">
					<div class="inv-party">
						<h3>Customer</h3>
						<div class="inv-party-name">${esc(data.customer.customer_name)}${
							data.customer.is_repeat ? ' <span class="pill pill-sky">Repeat</span>' : ""}</div>
						${line(data.customer.mobile_no)}
						${line(data.customer.alternate_mobile)}
						${line(data.customer.email)}
						${line(data.lead_source ? "Came in by: " + data.lead_source : "")}
					</div>
					<div class="inv-party">
						<h3>Device</h3>
						<div class="inv-party-name">${esc([data.device.brand, data.device.model]
							.filter(Boolean).join(" ") || data.device.device_type || "—")}</div>
						${data.device.imei_1 ? line("IMEI: " + data.device.imei_1) : ""}
						${data.device.serial_no ? line("Serial: " + data.device.serial_no) : ""}
						${data.device.purchase_date
							? line("Bought " + day(data.device.purchase_date)) : ""}
						<div class="inv-line"><b class="${
							data.warranty.type === "Out of Warranty" ? "warn-red" : "good"}">${
							esc(data.warranty.type || "Out of Warranty")}</b>${data.warranty.expiry
								? ` · until ${esc(day(data.warranty.expiry))}` : ""}</div>
						${data.device.sold_by_us ? line("Sold by this shop") : ""}
					</div>
					<div class="inv-party">
						<h3>The repair</h3>
						<div class="inv-party-name">${esc(data.repair_category || "—")}</div>
						${line(data.complaint)}
						${data.issues.length ? line("Reported: " + data.issues.join(", ")) : ""}
						${line(data.technician_name
							? "Technician: " + data.technician_name : "No technician assigned yet")}
						${data.device.condition ? line("Condition in: " + data.device.condition) : ""}
					</div>
				</div>

				${workTable(data)}

				<div class="inv-bottom">
					<div class="inv-notes">
						${data.diagnosis ? panelBlock("Diagnosis", esc(stripTags(data.diagnosis))) : ""}
						${data.accessories.length ? panelBlock("What came with it",
							data.accessories.map((row) => `<div class="sum-row"><span>${
								esc(row.accessory)}</span><b>${row.received
									? (row.returned ? "returned" : "held") : "not received"}</b></div>`).join(""))
							: ""}
						${data.device.photos.length ? panelBlock("Photos taken at intake",
							`<div class="bkg-photos">${data.device.photos.map((src, index) =>
								`<button class="bkg-photo" data-photo="${index}">
									<img src="${esc(src)}" alt="Device photo ${index + 1}"></button>`).join("")}</div>`)
							: ""}
						${panelBlock("Promise", `
							<div class="sum-row"><span>Promised</span><b>${
								esc(stamp(data.promised)) || "—"}</b></div>
							${data.sla_due_on
								? `<div class="sum-row"><span>Due by policy</span><b>${
									esc(stamp(data.sla_due_on))}</b></div>` : ""}
							<div class="sum-row"><span>Running late</span><b class="${
								data.is_delayed ? "warn-red" : "good"}">${data.is_delayed
									? Math.round(data.delay_hours) + " hours over" : "no"}</b></div>
							${data.delivered_on
								? `<div class="sum-row"><span>Handed over</span><b>${
									esc(stamp(data.delivered_on))}</b></div>` : ""}`)}
					</div>

					<div class="inv-totals">
						<div class="tr"><span>Parts</span><span>${money(totals.parts)}</span></div>
						<div class="tr"><span>Labour</span><span>${money(totals.labour)}</span></div>
						<div class="tr"><span>Discount</span><span>${
							totals.discount ? "- " + money(totals.discount) : money(0)}</span></div>
						${totals.discount_reason
							? `<div class="tr tr-note"><span>Why</span><span>${
								esc(totals.discount_reason)}</span></div>` : ""}
						<div class="tr"><span>Taxable Amount</span><span>${money(totals.taxable)}</span></div>
						<div class="tr"><span>GST</span><span>${money(totals.tax)}</span></div>
						<div class="tr tr-grand"><span>Total</span><span>${money(totals.grand_total)}</span></div>
						${totals.warranty_borne
							? `<div class="tr"><span>Warranty bears</span><span class="good">- ${
								money(totals.warranty_borne)}</span></div>` : ""}
						<div class="tr"><span>Customer pays</span><span>${money(totals.payable)}</span></div>
						<div class="tr"><span>Advance taken</span><span class="good">${
							money(totals.advance)}</span></div>
						<div class="tr tr-balance"><span>Balance</span>
							<span class="${totals.balance > 0 ? "warn-red" : "good"}">${
								money(totals.balance)}</span></div>
					</div>
				</div>
			</section>

			<section class="inv-side">
				${paymentsPanel(data)}
				${deliveryPanel(data)}
				${data.feedback ? feedbackPanel(data.feedback) : ""}
				${timelinePanel(data.activity)}
			</section>

			<section class="inv-actions">
				<a class="btn btn-quiet btn-icon" href="/retail/bookings">${icon("back")} Back to Bookings</a>
				<button class="btn btn-primary btn-icon" id="print-bottom">${
					icon("print")} Print Acknowledgement</button>
				<a class="btn btn-outline btn-icon" href="/retail/service?booking=${
					encodeURIComponent(data.name)}">${icon("wrench")} Open at the counter</a>
				${data.can.take_money && totals.balance > 0
					? `<button class="btn btn-orange btn-icon" id="collect">${
						icon("cash")} Take Payment</button>` : ""}
				${data.sales_invoice
					? `<a class="btn btn-quiet btn-icon" href="/retail/invoice?name=${
						encodeURIComponent(data.sales_invoice)}">${icon("file")} ${
						esc(data.sales_invoice)}</a>` : ""}
				${data.delivery.otp_pending
					? `<button class="btn btn-quiet btn-icon" id="otp">${
						icon("key")} Re-send collection OTP</button>` : ""}
				<button class="btn btn-quiet btn-icon" data-send="WhatsApp">${
					icon("chat")} Send WhatsApp</button>
				<button class="btn btn-quiet btn-icon" data-send="Email">${icon("mail")} Send Email</button>
				${data.can.note
					? `<button class="btn btn-quiet btn-icon" id="add-note">${icon("note")} Add a note</button>`
					: ""}
			</section>`;

		$("print-bottom").addEventListener("click", print);
		if ($("collect")) $("collect").addEventListener("click", askPayment);
		if ($("add-note")) $("add-note").addEventListener("click", askNote);
		if ($("otp")) $("otp").addEventListener("click", resendOtp);
		document.querySelectorAll("[data-send]").forEach((node) => {
			node.addEventListener("click", () => send(node.dataset.send));
		});
		document.querySelectorAll("[data-photo]").forEach((node) => {
			node.addEventListener("click", () => {
				$("photo-body").innerHTML =
					`<img class="bkg-photo-big" src="${esc(data.device.photos[Number(node.dataset.photo)])}" alt="">`;
				$("photo-title").textContent = `Device photo ${Number(node.dataset.photo) + 1} of ${
					data.device.photos.length}`;
				$("photo-modal").hidden = false;
			});
		});
	}

	function stripTags(value) {
		const node = document.createElement("div");
		node.innerHTML = value == null ? "" : String(value);
		return node.textContent || "";
	}

	function line(value) {
		return value ? `<div class="inv-line">${esc(value)}</div>` : "";
	}

	function panelBlock(title, body) {
		return `<div class="inv-block"><h3>${title}</h3><div>${body}</div></div>`;
	}

	function workTable(data) {
		const rows = [
			...data.parts.map((row) => ({ ...row, kind: "Part",
				name: row.item_name || row.item_code, note: row.status })),
			...data.labour.map((row) => ({ ...row, kind: "Labour",
				name: row.description || row.item_code, note: row.technician })),
		];

		if (!rows.length) {
			return '<div class="cust-none">No parts or labour on this repair yet — '
				+ 'the technician has not costed it.</div>';
		}

		return `<div class="inv-items-wrap">
			<table class="bill-table inv-items">
				<thead><tr>
					<th>#</th><th>Part / Labour</th><th>Type</th><th>Where it stands</th>
					<th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th>
				</tr></thead>
				<tbody>${rows.map((row, index) => `
					<tr>
						<td class="num">${index + 1}</td>
						<td><b>${esc(row.name)}</b><small>${esc(row.item_code || "")}${
							row.serial_no ? " · " + esc(row.serial_no) : ""}</small></td>
						<td><span class="pill ${row.kind === "Part" ? "pill-sky" : "pill-purple"}">${
							row.kind}</span>${row.warranty
								? ' <span class="pill pill-good">Warranty</span>' : ""}</td>
						<td>${esc(row.note || "—")}</td>
						<td class="num">${row.qty}</td>
						<td class="num">${money(row.rate)}</td>
						<td class="num strong">${money(row.amount)}</td>
					</tr>`).join("")}</tbody>
			</table>
		</div>`;
	}

	function paymentsPanel(data) {
		const rows = data.payments;
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Money</h2>
				<span class="pill ${data.totals.balance > 0 ? "pill-warn" : "pill-good"}">${
					esc(data.totals.payment_status || "Unpaid")}</span></div>
			${rows.length ? `<div class="row-list">${rows.map((row) => `
				<div class="row-line">
					<span class="row-main"><b>${esc(row.name)}</b><small>${esc(row.kind)}</small></span>
					<span class="row-date">${esc(day(row.date))}</span>
					<span class="row-amount">${money(row.amount)}</span>
					<span class="pill pill-sky">${esc(row.mode || "—")}</span>
				</div>`).join("")}</div>`
				: '<div class="cust-none">Nothing has been taken against this repair yet.</div>'}
		</div>`;
	}

	function deliveryPanel(data) {
		const delivery = data.delivery;
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Hand-over</h2>
				<span class="pill ${delivery.otp_verified ? "pill-good" : "pill-sky"}">${
					delivery.otp_verified ? "Collected" : data.status}</span></div>
			<div class="sum-row"><span>How</span><b>${esc(delivery.mode || "Counter Pickup")}</b></div>
			${delivery.ready_on
				? `<div class="sum-row"><span>Ready since</span><b>${esc(stamp(delivery.ready_on))}</b></div>` : ""}
			${delivery.otp_pending
				? '<div class="sum-row"><span>Collection OTP</span><b class="warn-red">not used yet</b></div>' : ""}
			${delivery.receiver
				? `<div class="sum-row"><span>Collected by</span><b>${esc(delivery.receiver)}</b></div>` : ""}
			${delivery.delivered_by
				? `<div class="sum-row"><span>Handed over by</span><b>${esc(delivery.delivered_by)}</b></div>` : ""}
			${data.delivered_on
				? `<div class="sum-row"><span>On</span><b>${esc(stamp(data.delivered_on))}</b></div>` : ""}
			<div class="sum-row"><span>Accessories back</span><b>${
				delivery.accessories_returned ? "yes" : "not yet"}</b></div>
		</div>`;
	}

	function feedbackPanel(feedback) {
		return `<div class="svc-panel">
			<div class="panel-head"><h2>What the customer said</h2>
				<span class="pill pill-sky">${"★".repeat(Math.round((feedback.rating || 0) * 5))}</span></div>
			<div class="cust-note">${esc(feedback.comments || "—")}</div>
		</div>`;
	}

	function timelinePanel(events) {
		return `<div class="svc-panel">
			<div class="panel-head"><h2>Everything that happened</h2>
				<span class="rep-when">${events.length} entries</span></div>
			<ol class="inv-timeline bkg-timeline">${events.map((event) => `
				<li class="tl-${esc(event.kind)}"><span class="dot"></span>
					<span class="tl-label">${esc(event.label)}</span>
					<span class="tl-at">${esc(stamp(event.at))}</span>
					${event.by ? `<span class="tl-by">${esc(event.by)}</span>` : ""}
					${event.note ? `<span class="tl-note">${esc(event.note)}</span>` : ""}
				</li>`).join("")}</ol>
		</div>`;
	}

	// ------------------------------------------------------------- actions
	async function print() {
		try {
			const url = state.data.print_url
				|| await A3.call("a3_retail.api.bookings.print_url", { name: state.name });
			window.open(url, "_blank");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function askPayment() {
		const balance = state.data.totals.balance;
		$("payment-note").textContent = `${state.data.name} · ${
			state.data.customer.customer_name} · ${money(balance)} still owed`;
		$("pay-amount").value = balance.toFixed(2);
		$("pay-amount").max = balance;
		$("pay-msg").textContent = "";
		$("payment-modal").hidden = false;
		$("pay-amount").focus();
	}

	async function takePayment() {
		const amount = Number($("pay-amount").value) || 0;
		if (amount <= 0) {
			$("pay-msg").className = "msg error";
			$("pay-msg").textContent = "How much did the customer hand over?";
			return;
		}
		try {
			const result = await A3.call("a3_retail.api.bookings.collect", {
				name: state.name, amount, mode_of_payment: $("pay-mode").value,
			});
			$("payment-modal").hidden = true;
			toast(`${money(result.advance)} taken in all — ${money(result.balance)} left to pay.`, "ok");
			reload();
		} catch (error) {
			$("pay-msg").className = "msg error";
			$("pay-msg").textContent = error.message;
		}
	}

	function askNote() {
		$("note-text").value = "";
		$("note-msg").textContent = "";
		$("note-modal").hidden = false;
		$("note-text").focus();
	}

	async function saveNote() {
		const text = $("note-text").value.trim();
		if (!text) {
			$("note-msg").className = "msg error";
			$("note-msg").textContent = "Write the note first.";
			return;
		}
		try {
			await A3.call("a3_retail.api.bookings.add_note", { name: state.name, text });
			$("note-modal").hidden = true;
			toast("Noted on the booking.", "ok");
			reload();
		} catch (error) {
			$("note-msg").className = "msg error";
			$("note-msg").textContent = error.message;
		}
	}

	async function send(channel) {
		try {
			const result = await A3.call("a3_retail.api.bookings.notify",
				{ name: state.name, channel });
			toast(result.sent ? channel + " sent." : channel + " was not sent — check messaging "
				+ "settings.", result.sent ? "ok" : "error");
			if (result.sent) reload();
		} catch (error) {
			toast(error.message, "error");
		}
	}

	async function resendOtp() {
		try {
			await A3.call("a3_retail.api.bookings.resend_otp", { name: state.name });
			toast("A new collection OTP is on its way to the customer.", "ok");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function reload() {
		$("top-actions").querySelectorAll("#print-top, .btn-outline").forEach((n) => n.remove());
		load();
	}

	// --------------------------------------------------------------- start
	function start(options) {
		state.name = options.name;
		state.branch = options.branch;
		state.company = options.company;

		if (!state.name) {
			window.location = "/retail/bookings";
			return;
		}

		$("pay-save").addEventListener("click", takePayment);
		$("note-save").addEventListener("click", saveNote);
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
