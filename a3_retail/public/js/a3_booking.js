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
		// `"` and `'` as well, not just the tag characters: almost every use of
		// this is inside an attribute, and a name like `APPLE IPAD A16 "11"`
		// would otherwise close the attribute at its first inner quote and the
		// rest of the name would be parsed as stray attributes.
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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
	async function loadBench() {
		try {
			state.technicians = await A3.call("a3_retail.api.bookings.technicians");
		} catch (error) {
			state.technicians = [];   // not permitted to list them: the field stays empty
		}
		// Cataloguing a part is not every counter's job, so the button only
		// appears for whoever the permission matrix allows.
		try {
			const line = await A3.call("a3_retail.api.service_pos.line_item_defaults");
			state.lineKinds = line.kinds || [];
			state.canCreateLineItem = !!line.can_create && state.lineKinds.length > 0;
		} catch (error) {
			state.canCreateLineItem = false;
			state.lineKinds = [];
		}
	}

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
			<section class="svc-panel wb" id="wb"></section>
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
						<div class="inv-party-name">${esc(
							deviceTitle(data.device) || data.device.device_type || "—")}</div>
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
						${data.device.lock_code
							? `<div class="lock-line">${esc(data.device.lock_code)}</div>` : ""}
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

		paintWork();

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

	/**
	 * The bench: where a repair is actually worked.
	 *
	 * Everything between booking a device in and handing it back used to need
	 * the desk, which the people doing the work are not meant to open. The steps
	 * offered here are whatever the job card's own state machine allows from
	 * where it stands — the screen never invents a path of its own, it only
	 * shows the ones that exist and says what each one means.
	 */
	const STAGES = ["Booked in", "Being looked at", "Under repair", "Ready", "Handed over"];
	const STAGE_OF = {
		"Draft": 0, "Open": 0,
		"Under Diagnosis": 1, "Estimate Pending": 1, "Estimate Sent": 1,
		"Estimate Approved": 1, "Estimate Rejected": 1,
		"In Progress": 2, "Awaiting Parts": 2, "On Hold": 2, "Repair Completed": 2,
		"QC Failed": 2, "QC Passed": 2, "Not Repairable": 2,
		"Ready for Delivery": 3,
		"Delivered": 4, "Closed": 4, "Cancelled": 4,
	};

	async function paintWork() {
		const host = $("wb");
		if (!host) return;
		host.innerHTML = '<p class="muted">Reading where this repair stands…</p>';

		let work;
		try {
			work = await A3.call("a3_retail.api.bookings.steps", { name: state.name });
		} catch (error) {
			host.innerHTML = `<p class="wb-bad">${esc(error.message || "Could not read the job card.")}</p>`;
			return;
		}
		state.work = work;

		const data = state.data;
		const stage = STAGE_OF[work.status] == null ? 0 : STAGE_OF[work.status];
		const bench = (state.technicians || []).map((row) =>
			`<option value="${esc(row.employee)}"${row.employee === work.technician
				? " selected" : ""}>${esc(row.employee_name)}</option>`).join("");

		host.innerHTML = `
			<div class="wb-head">
				<h2>The repair</h2>
				<span class="pill ${esc(work.tone)}">${esc(work.status)}</span>
			</div>

			<ol class="wb-rail">${STAGES.map((label, index) => `
				<li class="${index < stage ? "is-done" : index === stage ? "is-now" : ""}">
					<span class="dot">${index + 1}</span><span>${label}</span></li>`).join("")}
			</ol>

			${work.can_work ? `
			<div class="wb-bar">
				<label class="field wb-bench"><span>On the bench of</span>
					<div class="wb-pair">
						<select id="wb-tech">${bench || '<option value="">No technicians listed</option>'}</select>
						<button class="btn btn-quiet" id="wb-assign" type="button">Assign</button>
					</div></label>
			</div>

			<div id="wb-lines"></div>

			${work.steps.length ? `
				<div class="wb-steps">${work.steps.map((step) => `
					<button class="wb-step" data-step="${esc(step.status)}"
					        data-reason="${step.needs_reason ? 1 : 0}">
						<b>${esc(step.label)}</b><span>${esc(step.hint)}</span></button>`).join("")}
				</div>`
				: `<p class="muted wb-none">${esc(work.waiting_on
					|| "Nothing more to do here — this job is finished.")}</p>`}

			${work.accessories_out.length ? `
				<div class="wb-acc">
					<span>Still holding the customer's ${work.accessories_out.map(esc).join(", ")}.</span>
					<button class="btn btn-quiet" id="wb-acc-back" type="button">Handed back</button>
				</div>` : ""}

			${(data.can.deliver || data.can.invoice || data.sales_invoice) ? `
				<div class="wb-finish">
					${data.can.invoice
						? `<button class="btn btn-invoice btn-icon" id="wb-invoice">${
							icon("print")} Generate the bill</button>` : ""}
					${data.sales_invoice
						? `<a class="btn btn-outline btn-icon" target="_blank"
						      href="${esc(data.invoice_url || "#")}">${
							icon("print")} Print ${esc(data.sales_invoice)}</a>` : ""}
					${data.can.deliver
						? `<button class="btn btn-primary btn-icon" id="wb-deliver">${
							icon("wrench")} Hand over to the customer</button>` : ""}
					<span class="muted">${data.can.deliver
						? (work.require_otp === false
							? "Check who is collecting."
							: "Needs the code sent to their phone.")
						: "Bill it before it goes out."}</span>
				</div>` : ""}
			` : '<p class="muted wb-none">You can see this repair but not work on it.</p>'}`;

		if ($("wb-assign")) $("wb-assign").addEventListener("click", assignBench);
		if ($("wb-acc-back")) $("wb-acc-back").addEventListener("click", accessoriesBack);
		if ($("wb-deliver")) $("wb-deliver").addEventListener("click", askHandOver);
		if ($("wb-invoice")) $("wb-invoice").addEventListener("click", billNow);
		host.querySelectorAll(".wb-step").forEach((node) => {
			node.addEventListener("click", () => takeStep(node.dataset.step,
			                                             node.dataset.reason === "1"));
		});

		if (work.can_work) paintLines();
	}

	/**
	 * What the repair is being charged for, changed as the work goes.
	 *
	 * What a device needs is not known when it is booked in — the fault is
	 * found at the bench and the part chosen after that. Once the bill is
	 * raised the lines stop being editable: they are what the customer was
	 * charged, and a change then belongs on a credit note.
	 */
	async function paintLines() {
		const host = $("wb-lines");
		if (!host) return;
		let data;
		try {
			data = await A3.call("a3_retail.api.bookings.lines", { name: state.name });
		} catch (error) {
			host.innerHTML = `<p class="wb-bad">${esc(error.message || "Could not read the lines.")}</p>`;
			return;
		}
		state.lines = data;

		host.innerHTML = `
			<div class="wb-lines-head">
				<h3>Parts and work</h3>
				<span class="wb-sum">${data.rows.length
					? `${money(data.totals.parts)} parts · ${money(data.totals.labour)} work`
					: "nothing on it yet"}</span>
			</div>
			${data.rows.length ? `
			<table class="wb-table"><thead><tr>
				<th>What</th><th>Type</th><th class="num">Qty</th>
				<th class="num">Rate</th><th class="num">Amount</th><th></th>
			</tr></thead><tbody>${data.rows.map((row) => `
				<tr>
					<td>${esc(row.item_name)}${row.status
						? ` <span class="pill pill-sky">${esc(row.status)}</span>` : ""}</td>
					<td><span class="pill">${esc(row.kind)}</span></td>
					<td class="num">${data.can_edit
						? `<input class="wb-qty" data-row="${esc(row.row)}" inputmode="decimal"
						          value="${row.qty}">` : row.qty}</td>
					<td class="num">${data.can_edit
						? `<input class="wb-rate" data-row="${esc(row.row)}" inputmode="decimal"
						          value="${row.rate}">` : money(row.rate)}</td>
					<td class="num">${money(row.amount)}</td>
					<td>${data.can_edit
						? `<button class="wb-drop" data-row="${esc(row.row)}"
						           title="Take it off">&times;</button>` : ""}</td>
				</tr>`).join("")}</tbody></table>`
				: '<p class="muted wb-none">Nothing charged on this repair yet.</p>'}
			${data.can_edit ? adderMarkup("wb")
				: data.invoiced
					? '<p class="muted wb-none">Billed — the lines are what the customer was charged.</p>'
					: ""}`;

		wireAdder("wb", findLineItem, reload);
		host.querySelectorAll(".wb-drop").forEach((node) =>
			node.addEventListener("click", () => dropLine(node.dataset.row)));
		// Typing must not redraw the row out from under the caret, so the change
		// is sent when the box is left rather than on every keystroke.
		host.querySelectorAll(".wb-qty, .wb-rate").forEach((node) =>
			node.addEventListener("change", () => editLine(
				node.dataset.row,
				node.classList.contains("wb-qty") ? { qty: Number(node.value) }
				                                  : { rate: Number(node.value) })));
	}

	async function findLineItem(query) {
		const box = $("wb-hits");
		if (!box) return;
		if (query.length < 2) return (box.innerHTML = "");
		let rows = [];
		try {
			rows = await A3.call("a3_retail.api.service_pos.search_items",
			                     { query, limit: 8 });
		} catch (error) {
			box.innerHTML = `<p class="muted">${esc(error.message || "Could not search.")}</p>`;
			return;
		}
		box.innerHTML = rows.length
			? rows.map((row) => `
				<button type="button" class="w-hit" data-code="${esc(row.item_code)}"
				        data-kind="${esc(row.kind)}">
					<span>${esc(row.item_name)} <small>${esc(row.kind)}</small></span>
					<b>${money(row.rate)}</b>
				</button>`).join("")
			: '<p class="muted">Nothing by that name.</p>';
		box.querySelectorAll(".w-hit").forEach((node) =>
			node.addEventListener("mousedown", (event) => {
				event.preventDefault();
				addLineItem(node.dataset.code, node.dataset.kind);
			}));
	}

	// `inDialog` keeps the page still: the step dialog repaints its own list,
	// and reloading the whole booking underneath would close it.
	async function addLineItem(itemCode, kind, inDialog) {
		try {
			await A3.call("a3_retail.api.bookings.add_line",
			              { name: state.name, item_code: itemCode, kind, qty: 1 });
			toast("Added.", "ok");
			if (!inDialog) reload();
		} catch (error) {
			toast(error.message || "Could not add it.", "error");
		}
	}

	async function editLine(row, change, inDialog) {
		try {
			await A3.call("a3_retail.api.bookings.update_line",
			              Object.assign({ name: state.name, row }, change));
			if (!inDialog) reload();
		} catch (error) {
			toast(error.message || "Could not change it.", "error");
			if (!inDialog) paintLines();
		}
	}

	async function dropLine(row, inDialog) {
		try {
			await A3.call("a3_retail.api.bookings.remove_line",
			              { name: state.name, row });
			toast("Taken off.", "ok");
			if (!inDialog) reload();
		} catch (error) {
			toast(error.message || "Could not remove it.", "error");
		}
	}

	async function billNow() {
		const button = $("wb-invoice");
		if (button) button.disabled = true;
		try {
			const made = await A3.call("a3_retail.api.bookings.invoice_now",
			                           { name: state.name });
			toast(made.created === false
				? "Already billed on " + made.sales_invoice
				: "Billed — " + made.sales_invoice, "ok");
			if (made.print_url) window.open(made.print_url, "_blank");
			reload();
		} catch (error) {
			toast(error.message || "Could not bill it.", "error");
		} finally {
			if (button) button.disabled = false;
		}
	}

	/**
	 * Every move the repair makes, asked for in one place.
	 *
	 * A step is rarely just a status: it is a technician finishing a piece of
	 * work and the parts they used on it. Advancing straight off the button
	 * meant the parts were remembered afterwards, or not at all.
	 */
	function takeStep(status, needsReason) {
		const step = ((state.work && state.work.steps) || [])
			.find((s) => s.status === status) || { label: status, hint: "" };
		state.stage = { status, needsReason };

		$("stage-title").textContent = step.label;
		$("stage-note").textContent = step.hint || "";
		$("stage-go").textContent = step.label;

		const bench = (state.technicians || []).map((row) =>
			`<option value="${esc(row.employee)}"${
				row.employee === (state.work && state.work.technician) ? " selected" : ""
			}>${esc(row.employee_name)}</option>`).join("");
		$("stage-tech").innerHTML =
			'<option value="">Nobody in particular</option>' + bench;

		$("stage-reason-label").textContent = needsReason ? "Why" : "Note (optional)";
		$("stage-reason").value = "";
		$("stage-reason").placeholder = needsReason
			? "The reason this is stopping — the customer will be asked"
			: "Anything the next person should know";
		$("stage-msg").textContent = "";
		$("stage-modal").hidden = false;
		paintStageLines();
		$("stage-reason").focus();
	}

	/** The same parts and work, inside the step dialog. */
	async function paintStageLines() {
		const host = $("stage-lines");
		host.innerHTML = '<p class="muted">Reading what is on it…</p>';
		let data;
		try {
			data = await A3.call("a3_retail.api.bookings.lines", { name: state.name });
		} catch (error) {
			host.innerHTML = `<p class="wb-bad">${esc(error.message || "Could not read it.")}</p>`;
			return;
		}
		host.innerHTML = `
			<div class="wb-lines-head">
				<h3>Parts and work</h3>
				<span class="wb-sum">${data.rows.length
					? money(data.totals.parts + data.totals.labour) : "nothing on it yet"}</span>
			</div>
			${data.rows.length ? `
			<table class="wb-table"><thead><tr>
				<th>What</th><th class="num">Qty</th><th class="num">Rate</th>
				<th class="num">Amount</th><th></th>
			</tr></thead><tbody>${data.rows.map((row) => `
				<tr>
					<td>${esc(row.item_name)} <span class="pill">${esc(row.kind)}</span></td>
					<td class="num">${data.can_edit
						? `<input class="sg-qty" data-row="${esc(row.row)}" inputmode="decimal"
						          value="${row.qty}">` : row.qty}</td>
					<td class="num">${data.can_edit
						? `<input class="sg-rate" data-row="${esc(row.row)}" inputmode="decimal"
						          value="${row.rate}">` : money(row.rate)}</td>
					<td class="num">${money(row.amount)}</td>
					<td>${data.can_edit
						? `<button class="wb-drop sg-drop" data-row="${esc(row.row)}"
						           title="Take it off">&times;</button>` : ""}</td>
				</tr>`).join("")}</tbody></table>` : ""}
			${data.can_edit ? adderMarkup("sg") : ""}`;

		wireAdder("sg", findStageItem, paintStageLines);
		host.querySelectorAll(".sg-drop").forEach((node) =>
			node.addEventListener("click", async () => {
				await dropLine(node.dataset.row, true);
				paintStageLines();
			}));
		host.querySelectorAll(".sg-qty, .sg-rate").forEach((node) =>
			node.addEventListener("change", async () => {
				await editLine(node.dataset.row,
					node.classList.contains("sg-qty") ? { qty: Number(node.value) }
					                                  : { rate: Number(node.value) }, true);
				paintStageLines();
			}));
	}

	/** Search for a line, or make one that does not exist yet.
	 *
	 *  A bench meets a connector or a flex the shop has never bought, and a
	 *  charge nobody wrote down. Sending someone to the stock screen to name it
	 *  and back here to add it is how the line ends up in the notes instead.
	 */
	function adderMarkup(prefix) {
		return `
			<div class="wb-add">
				<input id="${prefix}-find" placeholder="Add a part, a charge or an accessory…"
				       autocomplete="off">
				<div class="w-hits" id="${prefix}-hits"></div>
				${state.canCreateLineItem ? `
				<button class="link wb-newline" id="${prefix}-new" type="button"
					>+ Create a new part or service</button>
				<div class="wb-newform" id="${prefix}-form" hidden>
					<div class="field-grid three">
						<label class="field"><span>What is it</span>
							<input id="${prefix}-name" placeholder="ex: Display Flex Cable"></label>
						<label class="field"><span>Kind</span>
							<select id="${prefix}-kind">${(state.lineKinds || []).map((k) =>
								`<option value="${esc(k)}">${esc(k)}</option>`).join("")}</select></label>
						<label class="field"><span>Price</span>
							<input id="${prefix}-rate" inputmode="decimal" placeholder="0.00"></label>
					</div>
					<label class="field"><span>HSN / SAC code</span>
						<input id="${prefix}-hsn"
						       placeholder="85177090 for a part, 998716 for repair work"></label>
					<div class="msg" id="${prefix}-msg"></div>
					<div class="modal-actions">
						<button class="btn btn-quiet" id="${prefix}-back" type="button">Back</button>
						<button class="btn btn-primary" id="${prefix}-save" type="button"
							>Add it to the repair</button>
					</div>
				</div>` : ""}
			</div>`;
	}

	/** Wire one of those blocks. `after` is what to redraw when it succeeds. */
	function wireAdder(prefix, search, after) {
		const find = $(prefix + "-find");
		if (find) {
			let timer = null;
			find.addEventListener("input", () => {
				clearTimeout(timer);
				timer = setTimeout(() => search(find.value.trim()), 220);
			});
		}
		const open = $(prefix + "-new");
		if (!open) return;
		const form = $(prefix + "-form");
		open.addEventListener("click", () => {
			form.hidden = false;
			open.hidden = true;
			$(prefix + "-name").value = find ? find.value.trim() : "";
			$(prefix + "-msg").textContent = "";
			$(prefix + "-name").focus();
		});
		$(prefix + "-back").addEventListener("click", () => {
			form.hidden = true;
			open.hidden = false;
		});
		$(prefix + "-save").addEventListener("click", async () => {
			const name = $(prefix + "-name").value.trim();
			const msg = $(prefix + "-msg");
			if (!name) {
				msg.textContent = "Give it a name.";
				msg.className = "msg error";
				return;
			}
			$(prefix + "-save").disabled = true;
			msg.textContent = "Saving…";
			msg.className = "msg";
			try {
				const made = await A3.call("a3_retail.api.service_pos.create_line_item", {
					item_name: name,
					kind: $(prefix + "-kind").value,
					rate: Number($(prefix + "-rate").value) || 0,
					hsn_code: $(prefix + "-hsn").value.trim(),
				});
				await A3.call("a3_retail.api.bookings.add_line", {
					name: state.name, item_code: made.item_code,
					kind: made.kind, qty: 1, rate: made.rate,
				});
				toast(name + " added to the catalogue and to this repair.", "ok");
				after();
			} catch (error) {
				msg.textContent = error.message || "Could not add it.";
				msg.className = "msg error";
			} finally {
				$(prefix + "-save").disabled = false;
			}
		});
	}

	async function findStageItem(query) {
		const box = $("sg-hits");
		if (!box) return;
		if (query.length < 2) return (box.innerHTML = "");
		let rows = [];
		try {
			rows = await A3.call("a3_retail.api.service_pos.search_items",
			                     { query, limit: 8 });
		} catch (error) {
			box.innerHTML = `<p class="muted">${esc(error.message || "Could not search.")}</p>`;
			return;
		}
		box.innerHTML = rows.length
			? rows.map((row) => `
				<button type="button" class="w-hit" data-code="${esc(row.item_code)}"
				        data-kind="${esc(row.kind)}">
					<span>${esc(row.item_name)} <small>${esc(row.kind)}</small></span>
					<b>${money(row.rate)}</b>
				</button>`).join("")
			: '<p class="muted">Nothing by that name.</p>';
		box.querySelectorAll(".w-hit").forEach((node) =>
			node.addEventListener("mousedown", async (event) => {
				event.preventDefault();
				await addLineItem(node.dataset.code, node.dataset.kind, true);
				$("sg-find").value = "";
				paintStageLines();
			}));
	}

	async function confirmStage() {
		const { status, needsReason } = state.stage || {};
		const remarks = $("stage-reason").value.trim();
		if (needsReason && !remarks) {
			$("stage-msg").textContent = "Say why — whoever picks this up next will ask.";
			$("stage-msg").className = "msg error";
			return;
		}
		$("stage-go").disabled = true;
		try {
			// Whoever did the work goes on the card before the step is taken, so
			// the history reads in the right order.
			const who = $("stage-tech").value;
			if (who && who !== (state.work && state.work.technician)) {
				await A3.call("a3_retail.api.bookings.assign",
				              { name: state.name, technician: who });
			}
			await A3.call("a3_retail.api.bookings.advance",
			              { name: state.name, status, remarks: remarks || null });
			$("stage-modal").hidden = true;
			toast(`Moved to ${status}.`, "ok");
			reload();
		} catch (error) {
			$("stage-msg").textContent = error.message || "Could not move it.";
			$("stage-msg").className = "msg error";
		} finally {
			$("stage-go").disabled = false;
		}
	}

	async function assignBench() {
		const technician = $("wb-tech").value;
		if (!technician) return toast("Pick who is doing the work.", "error");
		try {
			await A3.call("a3_retail.api.bookings.assign",
			              { name: state.name, technician });
			toast("On the bench.", "ok");
			reload();
		} catch (error) {
			toast(error.message || "Could not assign it.", "error");
		}
	}

	async function accessoriesBack() {
		try {
			const done = await A3.call("a3_retail.api.bookings.return_accessories",
			                           { name: state.name });
			toast(`${done.returned} handed back.`, "ok");
			reload();
		} catch (error) {
			toast(error.message || "Could not record that.", "error");
		}
	}

	function askHandOver() {
		// Where the shop does not use a collection code, asking for one and then
		// ignoring whatever is typed is worse than not asking.
		const wanted = !state.work || state.work.require_otp !== false;
		$("hand-otp-field").hidden = !wanted;
		$("hand-modal").querySelector(".modal-note").textContent = wanted
			? "Ask the customer for the code sent to their phone."
			: "Check who is collecting, then hand it over.";

		// The customer collects their own device far more often than anybody
		// else does, so their name is the first thing offered rather than an
		// empty box to retype it into.
		const owner = (state.data && state.data.customer.customer_name) || "";
		$("hand-who").innerHTML =
			`<option value="owner">${esc(owner)} (the customer)</option>`
			+ '<option value="other">Somebody else</option>';
		$("hand-other-field").hidden = true;
		$("hand-receiver").value = "";
		$("hand-modal").hidden = false;
		$("hand-otp").value = "";
		$("hand-msg").textContent = "";
		(wanted ? $("hand-otp") : $("hand-who")).focus();
	}

	async function confirmHandOver() {
		try {
			await A3.call("a3_retail.api.bookings.hand_over", {
				name: state.name,
				otp: $("hand-otp").value.trim(),
				receiver: $("hand-who").value === "other"
					? ($("hand-receiver").value.trim() || null)
					: ((state.data && state.data.customer.customer_name) || null),
			});
			$("hand-modal").hidden = true;
			toast("Handed over. The job is closed.", "ok");
			reload();
		} catch (error) {
			$("hand-msg").textContent = error.message || "Could not complete the hand over.";
			$("hand-msg").className = "msg error";
		}
	}

	/** Brand and model, without saying the brand twice.
	 *
	 *  Some products carry the maker's name — "Apple Watch SE 3", "Galaxy Tab" —
	 *  so pasting the brand in front of every model gave "Apple Apple Watch SE 3"
	 *  on the face of the booking.
	 */
	function deviceTitle(device) {
		const brand = (device.brand || "").trim();
		const model = (device.model || "").trim();
		if (!model) return brand;
		if (!brand) return model;
		return model.toLowerCase().startsWith(brand.toLowerCase())
			? model : `${brand} ${model}`;
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
		$("hand-go").addEventListener("click", confirmHandOver);
		$("stage-go").addEventListener("click", confirmStage);
		$("hand-who").addEventListener("change", () => {
			const other = $("hand-who").value === "other";
			$("hand-other-field").hidden = !other;
			if (other) $("hand-receiver").focus();
		});
		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		// What the bench may offer has to be known before the page paints, or
		// the buttons that depend on it are drawn and then never redrawn.
		loadBench().then(load, load);
	}

	return { start, state };
})();
