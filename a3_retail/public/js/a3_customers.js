// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Customer management.
 *
 * One person on the right, everything about them: what they bought, what they
 * left for repair, what they owe, what is still under warranty, every message
 * the shop sent. The list on the left is the branch's own customers unless the
 * counter asks to look wider — someone who bought in Kochi can walk into
 * Kozhikode, and the person behind the desk still has to find them.
 */

window.CUST = (function () {
	const state = {
		branch: "", query: "", page: 1, scope: "branch",
		customer: null, profile: null, tab: "overview", channel: "WhatsApp",
	};
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);
	const moneyShort = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);

	function esc(value) {
		const node = document.createElement("div");
		node.textContent = value == null ? "" : String(value);
		return node.innerHTML;
	}

	function day(value, short) {
		if (!value) return "";
		const date = new Date(String(value).slice(0, 10) + "T00:00:00");
		if (isNaN(date)) return String(value);
		return date.toLocaleDateString("en-IN", short
			? { day: "2-digit", month: "short" }
			: { day: "2-digit", month: "short", year: "numeric" });
	}

	function toast(text, kind) {
		const box = document.createElement("div");
		box.className = "toast" + (kind ? " " + kind : "");
		box.textContent = text;
		document.body.appendChild(box);
		setTimeout(() => box.remove(), 3600);
	}

	// ---------------------------------------------------------------- list
	let searchTimer;
	async function loadList(page) {
		state.page = page || state.page;
		const data = await A3.call("a3_retail.api.customer_desk.list_customers", {
			query: state.query, page: state.page, scope: state.scope,
		});

		$("count").textContent = data.total;
		$("rows").innerHTML = data.rows.length
			? data.rows.map((row) => `
				<li><button class="cust-row ${row.name === state.customer ? "is-active" : ""}"
				            data-name="${esc(row.name)}">
					<span class="cust-ini">${esc(row.initials)}</span>
					<span class="cust-who">
						<span class="cust-name">${esc(row.customer_name)}</span>
						<span class="cust-meta">${esc(row.mobile_no || row.email_id || "")}</span>
						<span class="cust-meta">${esc(row.place || "")}</span>
					</span>
					<span class="pill ${row.active ? "pill-good" : "pill-bad"}">${
						row.active ? "Active" : "Blocked"}</span>
				</button></li>`).join("")
			: '<li class="cust-none">Nobody matches that search.</li>';

		$("showing").textContent = data.total
			? `Showing ${data.showing[0]} to ${data.showing[1]} of ${data.total}`
			: "No customers yet";
		paintPager(data);

		$("rows").querySelectorAll(".cust-row").forEach((node) => {
			node.addEventListener("click", () => open(node.dataset.name));
		});

		if (!state.customer && data.rows.length) open(data.rows[0].name);
	}

	function paintPager(data) {
		const pages = data.pages;
		const here = data.page;
		const numbers = [];
		for (let n = 1; n <= pages; n += 1) {
			if (n <= 3 || n === pages || Math.abs(n - here) <= 1) numbers.push(n);
			else if (numbers[numbers.length - 1] !== "…") numbers.push("…");
		}

		$("pager").innerHTML =
			`<button class="page-btn" data-go="${here - 1}" ${here <= 1 ? "disabled" : ""}>‹</button>`
			+ numbers.map((n) => n === "…"
				? '<span class="page-gap">…</span>'
				: `<button class="page-btn ${n === here ? "is-active" : ""}" data-go="${n}">${n}</button>`).join("")
			+ `<button class="page-btn" data-go="${here + 1}" ${here >= pages ? "disabled" : ""}>›</button>`;

		$("pager").querySelectorAll("[data-go]").forEach((node) => {
			node.addEventListener("click", () => loadList(Number(node.dataset.go)));
		});
	}

	// -------------------------------------------------------------- person
	async function open(customer) {
		state.customer = customer;
		state.tab = "overview";
		$("rows").querySelectorAll(".cust-row").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.name === customer);
		});

		state.profile = await A3.call("a3_retail.api.customer_desk.profile", { customer });
		paintDetail();
		loadTab("overview");
	}

	function paintDetail() {
		const person = state.profile;
		const device = person.primary_device || {};

		$("detail").innerHTML = `
			<section class="svc-panel cust-head">
				<div class="cust-id">
					<div class="cust-avatar">${esc(person.initials)}</div>
					<div>
						<h2>${esc(person.customer_name)}
							<span class="pill ${person.active ? "pill-good" : "pill-bad"}">${
								person.active ? "Active" : "Blocked"}</span></h2>
						<div class="cust-line">${icon("phone")} ${esc(person.mobile_no || "—")}</div>
						<div class="cust-line">${icon("mail")} ${esc(person.email || "—")}</div>
						<div class="cust-line">${icon("pin")} ${esc(person.address || "—")}</div>
					</div>
				</div>

				<div class="cust-device">
					<div class="device-photo">${device.image
						? `<img class="is-photo" src="${esc(device.image)}" alt="">`
						: '<span class="thumb-fallback">?</span>'}</div>
					<div class="cust-device-facts">
						<div class="cust-device-label">Primary Device</div>
						<div class="cust-device-name">${esc(device.item_name || "Nothing on record")}</div>
						${device.imei ? `<div class="cust-line">IMEI: ${esc(device.imei)}</div>` : ""}
						${device.warranty
							? `<div class="cust-line">Warranty:
								<b class="${device.warranty === "Out of Warranty" ? "warn-red" : "warn-good"}">
									${esc(device.warranty)}</b></div>` : ""}
						<button class="btn btn-outline btn-sm" id="all-devices">
							View All Devices (${person.device_count})</button>
					</div>
				</div>

				<dl class="cust-since">
					<div><dt>Customer Since</dt><dd>${esc(day(person.customer_since))}</dd></div>
					<div><dt>Total Bookings</dt><dd>${person.total_bookings}</dd></div>
					<div><dt>Total Spent</dt><dd>${money(person.total_spent)}</dd></div>
				</dl>

				<div class="cust-credit">
					<div class="tr"><span>Customer Type</span>
						<span class="pill pill-sky">${esc(person.customer_group || "—")}</span></div>
					<div class="tr"><span>Credit Limit</span><span>${money(person.credit_limit)}</span></div>
					<div class="tr"><span>Available Credit</span>
						<span class="good">${money(person.available_credit)}</span></div>
					<button class="btn btn-outline btn-block" id="edit-customer">Edit Customer</button>
				</div>
			</section>

			<nav class="cust-tabs" id="tabs">
				${[["overview", "Overview"], ["bookings", "Bookings & Services"],
				   ["invoices", "Invoices"], ["payments", "Payments"], ["warranty", "Warranty"],
				   ["devices", "Devices"], ["communication", "Communication"],
				   ["documents", "Documents"], ["notes", "Notes"]]
					.map(([key, label]) => `<button class="tab ${key === state.tab ? "is-active" : ""}"
						data-tab="${key}">${label}</button>`).join("")}
			</nav>

			<div id="tab-body"></div>

			<section class="cust-actions">
				${[["booking", "New Service Booking", "Create new booking", "wrench"],
				   ["invoice", "Create Invoice", "Generate new invoice", "file"],
				   ["payment", "Collect Payment", "Receive payment", "cash"],
				   ["message", "Send Message", "WhatsApp / SMS", "chat"],
				   ["statement", "Print Statement", "Customer statement", "print"],
				   ["block", person.active ? "Block Customer" : "Unblock Customer",
				    person.active ? "Restrict bookings" : "Allow bookings again", "ban"]]
					.map(([key, label, sub, glyph]) => `
						<button class="quick ${key === "block" ? "quick-danger" : ""}" data-action="${key}">
							<span class="quick-ico">${icon(glyph)}</span>
							<span class="quick-text">
								<span class="quick-label">${label}</span>
								<span class="quick-key">${sub}</span></span>
						</button>`).join("")}
			</section>`;

		$("tabs").addEventListener("click", (event) => {
			const tab = event.target.closest(".tab");
			if (!tab) return;
			state.tab = tab.dataset.tab;
			$("tabs").querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
			tab.classList.add("is-active");
			loadTab(state.tab);
		});
		$("edit-customer").addEventListener("click", () => editCustomer());
		$("all-devices").addEventListener("click", () => showTabAsList("devices", "Devices"));
		$("detail").querySelectorAll(".quick").forEach((node) => {
			node.addEventListener("click", () => act(node.dataset.action));
		});
	}

	/** The icon set is rendered server-side; these are the few this page draws. */
	function icon(name) {
		const paths = {
			phone: '<path d="M5 4h4l2 5-2.5 1.5a12 12 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
			mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
			pin: '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>',
			wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 21H10L4.3 15.3a4 4 0 0 1 5-5z"/><path d="M9 9l6 6"/>',
			file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			chat: '<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	// ----------------------------------------------------------------- tabs
	async function loadTab(name) {
		const body = $("tab-body");
		body.innerHTML = '<div class="pos-loading">Loading…</div>';

		if (name === "overview") return paintOverview(
			await A3.call("a3_retail.api.customer_desk.overview", { customer: state.customer }));

		const rows = await A3.call("a3_retail.api.customer_desk.tab",
			{ customer: state.customer, name });
		body.innerHTML = `<section class="svc-panel">${rowsTable(rows, name)}</section>`;
		if (name === "notes") {
			body.querySelector(".svc-panel").insertAdjacentHTML("beforeend",
				'<button class="btn btn-outline btn-sm" id="add-note">+ Add a note</button>');
			$("add-note").addEventListener("click", askNote);
		}
	}

	/** `compact` is the overview's three-abreast panels, where a full date and a
	 *  long status pill together leave the document number no room. */
	function rowsTable(rows, name, compact) {
		if (!rows.length) return '<div class="cust-none">Nothing here yet.</div>';
		return `<div class="row-list">${rows.map((row) => `
			<div class="row-line">
				<span class="row-main"><b>${esc(row.title)}</b>
					${row.sub ? `<small>${esc(row.sub)}</small>` : ""}</span>
				<span class="row-date">${esc(day(row.date, compact) || row.date || "")}</span>
				<span class="row-amount">${row.amount ? money(row.amount) : ""}</span>
				<span class="pill ${pillTone(row.status)}">${esc(row.status || "")}</span>
			</div>`).join("")}</div>`;
	}

	function pillTone(status) {
		const good = ["Paid", "Completed", "Delivered", "Active", "Receive", "In Warranty", "Sent"];
		const bad = ["Due", "Unpaid", "Out of Warranty", "Failed", "Cancelled", "Blocked"];
		if (good.indexOf(status) !== -1) return "pill-good";
		if (bad.indexOf(status) !== -1) return "pill-bad";
		if (status === "Partial" || status === "Pending") return "pill-warn";
		return "pill-sky";
	}

	function paintOverview(data) {
		const tiles = data.tiles;
		const tile = (key, label, glyph, tone) => {
			const box = tiles[key];
			const value = box.money ? money(box.total) : box.total;
			const sub = box.money ? money(box.sub) : box.sub;
			return `
				<div class="ctile">
					<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
						<span class="ctile-label ${tone === "bad" ? "warn-red" : ""}">${label}</span></div>
					<div class="ctile-value">${value}</div>
					<div class="ctile-sub">Total</div>
					<div class="ctile-foot"><b>${sub}</b><span>${esc(box.sub_label)}</span></div>
				</div>`;
		};

		$("tab-body").innerHTML = `
			<section class="ctiles">
				${tile("bookings", "Bookings", "file", "sky")}
				${tile("services", "Services", "wrench", "good")}
				${tile("invoices", "Invoices", "file", "sky")}
				${tile("payments", "Payments", "cash", "warn")}
				${tile("due", "Due Amount", "ban", "bad")}
				${tile("warranty", "Warranty", "print", "sky")}
			</section>

			<section class="cust-grid">
				<div class="svc-panel">
					<div class="panel-head"><h2>Recent Bookings</h2>
						<button class="linkish" data-open="bookings">View All</button></div>
					${rowsTable(data.recent_bookings.map((row) => ({
						title: row.name, date: row.date, status: row.status })), "bookings", true)}
				</div>

				<div class="svc-panel">
					<div class="panel-head"><h2>Recent Services</h2>
						<button class="linkish" data-open="invoices">View All</button></div>
					${rowsTable(data.recent_services, "invoices", true)}
				</div>

				<div class="cust-side">
					<div class="svc-panel">
						<div class="panel-head"><h2>Payments Summary</h2>
							<button class="linkish" data-open="payments">View All</button></div>
						<div class="sum-row"><span>Total Received</span>
							<b class="good">${money(data.payments_summary.received)}</b></div>
						<div class="sum-row"><span>Advance</span>
							<b class="sky">${money(data.payments_summary.advance)}</b></div>
						<div class="sum-row"><span>Refunds</span>
							<b class="warn-red">${money(data.payments_summary.refunds)}</b></div>
					</div>

					<div class="svc-panel">
						<div class="panel-head"><h2>Warranty &amp; AMC</h2>
							<button class="linkish" data-open="warranty">View All</button></div>
						<div class="sum-row"><span>Active Warranty</span>
							<b>${data.warranty_summary.active}</b></div>
						<div class="sum-row"><span>Out of Warranty</span>
							<b class="warn-red">${data.warranty_summary.expired}</b></div>
						<div class="sum-row"><span>AMC / Plans</span>
							<b>${data.warranty_summary.amc}</b></div>
					</div>
				</div>
			</section>

			<section class="cust-grid two">
				<div class="svc-panel">
					<div class="panel-head"><h2>Customer Notes</h2>
						<button class="linkish" data-open="notes">View All Notes</button></div>
					${data.notes.length
						? data.notes.map((note) => `<p class="note">${esc(note.title)}</p>`).join("")
						: '<div class="cust-none">No notes yet.</div>'}
				</div>
				<div class="svc-panel">
					<div class="panel-head"><h2>Documents</h2>
						<button class="linkish" data-open="documents">View Documents</button></div>
					<div class="cust-none">${data.documents} document(s)</div>
				</div>
			</section>`;

		$("tab-body").querySelectorAll("[data-open]").forEach((node) => {
			node.addEventListener("click", () => {
				const tab = node.dataset.open;
				state.tab = tab;
				$("tabs").querySelectorAll(".tab").forEach((t) =>
					t.classList.toggle("is-active", t.dataset.tab === tab));
				loadTab(tab);
			});
		});
	}

	async function showTabAsList(name, title) {
		const rows = await A3.call("a3_retail.api.customer_desk.tab",
			{ customer: state.customer, name });
		$("list-title").textContent = title;
		$("list-note").textContent = state.profile.customer_name;
		$("list-body").innerHTML = rows.length
			? rows.map((row) => `<li><span><b>${esc(row.title)}</b>
				<small>${esc(row.sub || "")}</small></span>
				<span class="pill ${pillTone(row.status)}">${esc(row.status || "")}</span></li>`).join("")
			: "<li>Nothing here yet.</li>";
		$("list-modal").hidden = false;
	}

	// -------------------------------------------------------------- actions
	function act(action) {
		const person = state.profile;
		if (action === "booking") {
			return window.open("/branch/service?customer=" + encodeURIComponent(person.name), "_self");
		}
		if (action === "invoice") {
			return window.open("/branch/sales?customer=" + encodeURIComponent(person.name), "_self");
		}
		if (action === "payment") {
			return toast("Take the payment on the bill it belongs to — open the invoice from the "
				+ "Invoices tab.", "error");
		}
		if (action === "message") return askMessage();
		if (action === "statement") return printStatement();
		if (action === "block") return toggleBlock();
	}

	function askMessage() {
		$("message-to").textContent = `${state.profile.customer_name} · `
			+ (state.profile.mobile_no || state.profile.email || "");
		$("message-text").value = "";
		$("message-modal").hidden = false;
		$("message-text").focus();
	}

	async function sendMessage() {
		try {
			const result = await A3.call("a3_retail.api.customer_desk.message", {
				customer: state.customer, channel: state.channel, text: $("message-text").value,
			});
			$("message-modal").hidden = true;
			toast(result.sent ? state.channel + " sent." : state.channel + " was not sent — check "
				+ "messaging settings.", result.sent ? "ok" : "error");
			if (state.tab === "communication") loadTab("communication");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function askNote() {
		$("note-text").value = "";
		$("note-modal").hidden = false;
		$("note-text").focus();
	}

	async function saveNote() {
		try {
			await A3.call("a3_retail.api.customer_desk.add_note",
				{ customer: state.customer, text: $("note-text").value });
			$("note-modal").hidden = true;
			toast("Note saved.", "ok");
			loadTab(state.tab);
		} catch (error) {
			toast(error.message, "error");
		}
	}

	async function toggleBlock() {
		const blocking = state.profile.active;
		if (blocking && !window.confirm(
			`Block ${state.profile.customer_name}? No new bookings or bills can be raised for `
			+ "them until they are unblocked. Everything already on record stays.")) return;

		try {
			await A3.call("a3_retail.api.customer_desk.set_blocked",
				{ customer: state.customer, blocked: blocking ? 1 : 0 });
			toast(blocking ? "Customer blocked." : "Customer unblocked.", "ok");
			await open(state.customer);
			loadList();
		} catch (error) {
			toast(error.message, "error");
		}
	}

	/** The statement prints from the browser: a counter has no ledger access. */
	async function printStatement() {
		const data = await A3.call("a3_retail.api.customer_desk.statement",
			{ customer: state.customer });
		const rows = data.lines.map((line) => `
			<tr><td>${esc(day(line.date))}</td><td>${esc(line.particulars)}</td>
				<td class="r">${line.debit ? money(line.debit) : ""}</td>
				<td class="r">${line.credit ? money(line.credit) : ""}</td>
				<td class="r">${money(line.balance)}</td></tr>`).join("");

		const win = window.open("", "_blank");
		win.document.write(`<!doctype html><title>Statement · ${esc(data.customer_name)}</title>
			<style>
				body { font: 13px/1.5 "Plus Jakarta Sans", system-ui, sans-serif; color: #2a3342;
					padding: 28px; }
				h1 { font-size: 19px; margin: 0 0 2px; }
				.meta { color: #6b7688; font-size: 12px; margin-bottom: 18px; }
				table { width: 100%; border-collapse: collapse; }
				th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid #e6e9ef; }
				th { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #6b7688; }
				.r { text-align: right; font-variant-numeric: tabular-nums; }
				tfoot td { font-weight: 700; border-top: 2px solid #2a3342; border-bottom: 0; }
			</style>
			<h1>${esc(data.customer_name)}</h1>
			<div class="meta">${esc(data.mobile_no || "")} · ${esc(data.address || "")}<br>
				Statement as of ${esc(day(data.as_of))}</div>
			<table>
				<thead><tr><th>Date</th><th>Particulars</th><th class="r">Debit</th>
					<th class="r">Credit</th><th class="r">Balance</th></tr></thead>
				<tbody>${rows || '<tr><td colspan="5">Nothing on this account yet.</td></tr>'}</tbody>
				<tfoot><tr><td colspan="4">Closing balance</td>
					<td class="r">${money(data.closing)}</td></tr></tfoot>
			</table>`);
		win.document.close();
		win.focus();
		win.print();
	}

	// ------------------------------------------------------- new / edit
	function newCustomer() {
		state.editing = null;
		$("customer-modal-title").textContent = "New customer";
		["c-mobile", "c-name", "c-email", "c-address", "c-city", "c-pin"]
			.forEach((id) => { $(id).value = ""; });
		$("customer-modal").hidden = false;
		$("c-mobile").focus();
	}

	function editCustomer() {
		state.editing = state.customer;
		$("customer-modal-title").textContent = "Edit " + state.profile.customer_name;
		$("c-mobile").value = state.profile.mobile_no || "";
		$("c-name").value = state.profile.customer_name || "";
		$("c-email").value = state.profile.email || "";
		$("c-address").value = "";
		$("customer-modal").hidden = false;
		$("c-name").focus();
	}

	async function saveCustomer() {
		try {
			const saved = await A3.call("a3_retail.api.pos.save_customer", {
				mobile_no: $("c-mobile").value.trim(),
				customer_name: $("c-name").value.trim(),
				email: $("c-email").value.trim(),
				address_line1: $("c-address").value.trim(),
				city: $("c-city").value.trim(),
				state: $("c-state").value.trim(),
				pincode: $("c-pin").value.trim(),
			});
			$("customer-modal").hidden = true;
			toast("Customer saved.", "ok");
			state.customer = saved.name;
			await loadList(1);
			open(saved.name);
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function exportCsv() {
		A3.call("a3_retail.api.customer_desk.list_customers",
			{ query: state.query, page: 1, page_size: 50, scope: state.scope }).then((data) => {
			const head = "Customer,Mobile,Email,Place,Status\n";
			const body = data.rows.map((row) => [row.customer_name, row.mobile_no || "",
				row.email_id || "", row.place || "", row.active ? "Active" : "Blocked"]
				.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
			const url = URL.createObjectURL(new Blob([head + body], { type: "text/csv" }));
			const link = document.createElement("a");
			link.href = url;
			link.download = "customers.csv";
			link.click();
			URL.revokeObjectURL(url);
		});
	}

	// --------------------------------------------------------------- start
	async function start(options) {
		state.branch = options.branch;

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.query = $("q").value.trim();
				loadList(1);
			}, 220);
		});
		$("scope").addEventListener("click", () => {
			state.scope = state.scope === "branch" ? "all" : "branch";
			$("scope").classList.toggle("is-active", state.scope === "all");
			$("scope").title = state.scope === "all" ? "This branch only" : "Every branch";
			toast(state.scope === "all" ? "Showing customers from every branch."
				: "Showing this branch's customers.");
			loadList(1);
		});

		$("new-customer").addEventListener("click", newCustomer);
		$("c-save").addEventListener("click", saveCustomer);
		$("message-send").addEventListener("click", sendMessage);
		$("note-save").addEventListener("click", saveNote);
		$("export").addEventListener("click", exportCsv);
		$("import").addEventListener("click", () => toast(
			"Bring customers in from the head-office system — the counter adds them one at a time.",
			"error"));

		document.querySelectorAll("#message-channel .seg-btn").forEach((node) => {
			node.addEventListener("click", () => {
				document.querySelectorAll("#message-channel .seg-btn")
					.forEach((b) => b.classList.remove("is-active"));
				node.classList.add("is-active");
				state.channel = node.dataset.value;
			});
		});
		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		await loadList(1);
	}

	return { start, state };
})();
