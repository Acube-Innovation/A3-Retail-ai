// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Branch Stock Control — one screen for a branch's shelves.
 *
 * Everything on it is read from ERPNext, and every action writes an ERPNext
 * document: a Stock Request to ask another branch, its own dispatch and receive
 * for the two legs of a transfer, a Stock Entry to move stock inside the branch,
 * a Stock Reconciliation to correct a count, a Material Request to ask head
 * office to buy. Nothing here edits a quantity directly, and nothing navigates
 * away — the work happens in modals over the same page.
 */

window.STOCK = (function () {
	const state = {
		branch: "", boot: null, filters: {}, page: 1, tab: "overview", sub: "incoming",
		rows: [], work: null,
	};
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);
	const qty = (value) => new Intl.NumberFormat("en-IN",
		{ maximumFractionDigits: 2 }).format(value || 0);

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

	function toast(text, kind) {
		const box = document.createElement("div");
		box.className = "toast" + (kind ? " " + kind : "");
		box.textContent = text;
		document.body.appendChild(box);
		setTimeout(() => box.remove(), 4200);
	}

	function tone(status) {
		return {
			"Healthy": "pill-good", "Available": "pill-good", "Received": "pill-good",
			"Approved": "pill-good", "Submitted": "pill-good", "In Warranty": "pill-good",
			"Low Stock": "pill-warn", "Low": "pill-warn", "Pending Approval": "pill-warn",
			"In Transit": "pill-warn", "Partially Received": "pill-warn",
			"Out of Stock": "pill-bad", "Rejected": "pill-bad", "Cancelled": "pill-bad",
			"Incoming": "pill-purple", "Reserved": "pill-sky", "Draft": "pill-sky",
		}[status] || "pill-sky";
	}

	function icon(name) {
		const paths = {
			box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
			truck: '<rect x="2" y="7" width="12" height="9" rx="2"/><path d="M14 10h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>',
			alert: '<path d="M12 3 22 20H2z"/><path d="M12 10v4M12 17h.01"/>',
			check: '<path d="M20 6 9 17l-5-5"/>',
			clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	/** One print route for every stock document — the application's own. */
	async function print(doctype, name) {
		const url = await A3.call("a3_retail.api.stock_control.print_url", { doctype, name });
		window.open(url, "_blank");
	}

	// ------------------------------------------------------------- loading
	async function loadAll() {
		await Promise.all([loadKpis(), loadStock(1), loadTab(state.tab), loadSide()]);
		$("as-of").textContent = "Updated " + new Date().toLocaleTimeString("en-IN",
			{ hour: "2-digit", minute: "2-digit" });
	}

	async function loadKpis() {
		const kpis = await A3.call("a3_retail.api.stock_control.kpis", { filters: state.filters });
		$("kpis").innerHTML = Object.keys(kpis).map((key) => {
			const card = kpis[key];
			return `<button class="ctile stk-kpi" data-kpi="${key}">
				<div class="ctile-label">${esc(card.label)}</div>
				<div class="ctile-value ${card.tone === "bad" ? "warn-red"
					: card.tone === "warn" ? "amber" : ""}">${
					card.money ? money(card.value) : qty(card.value)}</div>
			</button>`;
		}).join("");

		$("kpis").querySelectorAll("[data-kpi]").forEach((node) => {
			node.addEventListener("click", () => {
				const card = kpis[node.dataset.kpi];
				if (card.filter) {
					Object.assign(state.filters, card.filter);
					$("status").value = card.filter.status || "all";
					loadStock(1);
					toast("Showing " + (card.filter.status || "everything").toLowerCase() + ".");
				}
				if (card.tab) {
					state.tab = card.tab;
					state.sub = card.sub || state.sub;
					$("tabs").querySelectorAll(".tab").forEach((t) =>
						t.classList.toggle("is-active", t.dataset.tab === card.tab));
					loadTab(card.tab);
					$("tab-body").scrollIntoView({ block: "start" });
				}
			});
		});
	}

	async function loadStock(page) {
		state.page = page || state.page;
		$("stock-wrap").innerHTML = '<div class="pos-loading">Reading the shelf…</div>';

		const data = await A3.call("a3_retail.api.stock_control.live_stock",
			{ filters: state.filters, page: state.page, page_size: 25 });
		state.rows = data.rows;

		if (!data.rows.length) {
			$("stock-wrap").innerHTML = `<div class="rep-empty"><b>No stock matches that</b>
				<span>Try clearing the filters, or ask another branch.</span></div>`;
			$("showing").textContent = "";
			$("pager").innerHTML = "";
			return;
		}

		$("stock-wrap").innerHTML = `<table class="bill-table stk-table">
			<thead><tr>
				<th>Item</th><th>SKU</th><th>Group</th><th>Brand</th><th>Warehouse</th>
				<th class="num">Available</th><th class="num">Reserved</th><th class="num">Incoming</th>
				<th class="num">Reorder</th><th>Status</th><th>Network</th><th>Actions</th>
			</tr></thead>
			<tbody>${data.rows.map((row, index) => `
				<tr>
					<td><b>${esc(row.item_name)}</b>${row.has_serial
						? '<small>Serialised — moves by IMEI</small>' : ""}</td>
					<td class="nowrap">${esc(row.item_code)}</td>
					<td>${esc(row.item_group || "—")}</td>
					<td>${esc(row.brand || "—")}</td>
					<td class="nowrap">${esc(row.warehouse)}</td>
					<td class="num strong">${qty(row.available)}</td>
					<td class="num">${qty(row.reserved_qty)}</td>
					<td class="num">${qty(row.incoming)}</td>
					<td class="num">${qty(row.reorder_level)}</td>
					<td><span class="pill ${tone(row.status)}">${esc(row.status)}</span></td>
					<td><button class="linkish" data-network="${index}">${
						row.branches ? row.branches + " branches" : "Only here"}</button></td>
					<td class="bill-actions">
						<button class="btn btn-outline btn-sm" data-ask="${index}">Request</button>
						<button class="btn btn-quiet btn-sm" data-edit="${index}">Edit</button>
					</td>
				</tr>`).join("")}</tbody>
		</table>`;

		$("showing").textContent = `Showing ${data.showing[0]}–${data.showing[1]} of ${data.total}`;
		paintPager(data);

		$("stock-wrap").querySelectorAll("[data-network]").forEach((node) => {
			node.addEventListener("click", () => showNetwork(state.rows[Number(node.dataset.network)]));
		});
		$("stock-wrap").querySelectorAll("[data-ask]").forEach((node) => {
			node.addEventListener("click", () => openRequest(state.rows[Number(node.dataset.ask)]));
		});
		$("stock-wrap").querySelectorAll("[data-edit]").forEach((node) => {
			node.addEventListener("click", () => openItem(state.rows[Number(node.dataset.edit)]));
		});
	}

	/** Correct an item from the shop floor. A typo in a name, a missing HSN or a
	 *  barcode that never got scanned in are all things the branch finds and head
	 *  office does not. What decides how existing stock is valued or counted —
	 *  the code, the unit, whether it is serialised — is shown but not editable. */
	async function openItem(row) {
		const details = await A3.call("a3_retail.api.stock.item_details",
		                              { item_code: row.item_code });
		state.editing = details.item_code;
		$("item-code").textContent = details.item_code;
		$("item-fixed").textContent = details.stock_uom
			+ (details.has_serial_no ? " · serialised, moves by IMEI" : "");
		$("item-name").value = details.item_name || "";
		$("item-brand").value = details.brand || "";
		$("item-hsn").value = details.gst_hsn_code || "";
		$("item-rate").value = details.selling_rate || "";
		$("item-barcode").value = (details.barcodes || [])[0] || "";
		$("item-barcodes").textContent = (details.barcodes || []).length > 1
			? "also scans as " + details.barcodes.slice(1).join(", ") : "";
		$("item-disabled").checked = !!details.disabled;
		$("item-note").textContent = "";
		$("item-modal").hidden = false;
		$("item-name").focus();
	}

	async function saveItem() {
		const name = $("item-name").value.trim();
		if (!name) { $("item-note").textContent = "The item needs a name."; return; }
		$("item-save").disabled = true;
		try {
			await A3.call("a3_retail.api.stock.save_item", {
				item_code: state.editing,
				item_name: name,
				brand: $("item-brand").value.trim(),
				gst_hsn_code: $("item-hsn").value.trim(),
				barcode: $("item-barcode").value.trim(),
				selling_rate: $("item-rate").value.trim(),
				disabled: $("item-disabled").checked ? 1 : 0,
			});
			$("item-modal").hidden = true;
			toast(name + " saved.", "ok");
			await loadStock(state.page || 1);
		} catch (error) {
			$("item-note").textContent = error.message || "Could not save that item.";
		} finally {
			$("item-save").disabled = false;
		}
	}

	function paintPager(data) {
		const here = data.page;
		$("pager").innerHTML =
			`<button class="page-btn" data-go="${here - 1}" ${here <= 1 ? "disabled" : ""}>Previous</button>`
			+ `<span class="page-gap">${here} / ${data.pages}</span>`
			+ `<button class="page-btn" data-go="${here + 1}" ${
				here >= data.pages ? "disabled" : ""}>Next</button>`;
		$("pager").querySelectorAll("[data-go]").forEach((node) => {
			node.addEventListener("click", () => loadStock(Number(node.dataset.go)));
		});
	}

	async function loadSide() {
		const [alerts, activity] = await Promise.all([
			A3.call("a3_retail.api.stock_control.alerts", {}),
			A3.call("a3_retail.api.stock_control.activity", {}),
		]);

		$("alerts").innerHTML = alerts.length
			? alerts.map((alert, index) => `
				<button class="stk-alert" data-alert="${index}">
					<span class="dot ${alert.tone}"></span>${esc(alert.text)}</button>`).join("")
			: '<div class="cust-none">Nothing needs attention.</div>';

		$("alerts").querySelectorAll("[data-alert]").forEach((node) => {
			node.addEventListener("click", () => {
				const alert = alerts[Number(node.dataset.alert)];
				if (alert.filter) {
					Object.assign(state.filters, alert.filter);
					$("status").value = alert.filter.status || "all";
					loadStock(1);
				}
				if (alert.tab) {
					state.tab = alert.tab;
					$("tabs").querySelectorAll(".tab").forEach((t) =>
						t.classList.toggle("is-active", t.dataset.tab === alert.tab));
					loadTab(alert.tab);
				}
			});
		});

		$("activity").innerHTML = activity.length
			? activity.map((row) => `
				<div class="stk-act">
					<span class="stk-act-at">${esc(row.at)}</span>
					<span class="stk-act-main"><b>${esc(row.kind)}</b>
						<small>${esc(row.text)}</small></span>
					<button class="linkish" data-open-doc="${esc(row.kind)}|${esc(row.reference)}">${
						esc(row.reference)}</button>
				</div>`).join("")
			: '<div class="cust-none">Nothing has moved yet today.</div>';

		$("activity").querySelectorAll("[data-open-doc]").forEach((node) => {
			node.addEventListener("click", () => {
				const [doctype, name] = node.dataset.openDoc.split("|");
				print(doctype, name);
			});
		});
	}

	// ---------------------------------------------------------------- tabs
	async function loadTab(name) {
		state.tab = name;
		$("tab-body").innerHTML = '<div class="pos-loading">Loading…</div>';
		const data = await A3.call("a3_retail.api.stock_control.tab",
			{ name, sub: state.sub });

		if (name === "overview") return paintOverview(data.panels || []);
		if (name === "requests") return paintRequests(data);
		if (name === "transfers") return paintTransfers(data);
		if (name === "receipts") return paintReceipts(data);
		if (name === "service" || name === "devices") return paintCards(name, data);
		return paintRows(name, data.rows || []);
	}

	function paintOverview(panels) {
		$("tab-body").innerHTML = `<section class="stk-overview">${panels.map((panel) => `
			<div class="svc-panel">
				<div class="panel-head"><h2>${esc(panel.title)}</h2></div>
				${panel.rows.length ? `<div class="row-list">${panel.rows.map((row) => `
					<div class="row-line">
						<span class="row-main"><b>${esc(row.title)}</b>
							<small>${esc(row.sub || "")}</small></span>
						<span class="row-amount">${esc(row.value)}</span>
					</div>`).join("")}</div>`
					: '<div class="cust-none">Nothing here.</div>'}
			</div>`).join("")}</section>`;
	}

	const COLUMNS = {
		purchases: [["name", "Purchase Order"], ["party", "Supplier"], ["date", "Date", "date"],
		            ["items", "Items", "num"], ["amount", "Amount", "money"],
		            ["expected", "Expected", "date"], ["status", "Status", "pill"]],
		movements: [["date", "Date", "date"], ["kind", "Transaction"], ["item", "Item"],
		            ["warehouse", "Warehouse"], ["qty", "Qty", "num"], ["serial", "Serial"],
		            ["user", "By"], ["reference", "Reference"], ["status", "In / Out", "pill"]],
		adjustments: [["name", "Adjustment"], ["date", "Date", "date"], ["warehouse", "Warehouse"],
		              ["reason", "Reason"], ["items", "Items", "num"],
		              ["amount", "Value", "money"], ["user", "By"], ["status", "Status", "pill"]],
		reservations: [["item", "Item"], ["warehouse", "Warehouse"],
		               ["reserved", "Reserved", "num"], ["available", "Available", "num"],
		               ["status", "Status", "pill"]],
		service: [["item_name", "Part"], ["item_code", "Part No."], ["available", "Available", "num"],
		          ["reserved", "Reserved", "num"], ["reorder_level", "Reorder", "num"],
		          ["status", "Status", "pill"]],
		devices: [["job_card", "Booking"], ["customer", "Customer"], ["device", "Device"],
		          ["imei", "IMEI"], ["received", "Received"], ["promised", "Promised"],
		          ["status", "Service status", "pill"]],
	};

	function cell(row, [key, , kind]) {
		const value = row[key];
		if (value == null || value === "") return "—";
		if (kind === "money") return money(value);
		if (kind === "num") return qty(value);
		if (kind === "date") return esc(day(value));
		if (kind === "pill") return `<span class="pill ${tone(value)}">${esc(value)}</span>`;
		return esc(value);
	}

	function paintRows(name, rows, extra) {
		const columns = COLUMNS[name] || [];
		$("tab-body").innerHTML = `<section class="svc-panel bill-table-panel">
			${extra || ""}
			<div class="bill-table-wrap">
				${rows.length ? `<table class="bill-table">
					<thead><tr>${columns.map(([, label, kind]) =>
						`<th class="${kind === "num" || kind === "money" ? "num" : ""}">${label}</th>`)
						.join("")}</tr></thead>
					<tbody>${rows.map((row) => `<tr>${columns.map((column) =>
						`<td class="${column[2] === "num" || column[2] === "money" ? "num" : ""}">${
							cell(row, column)}</td>`).join("")}</tr>`).join("")}</tbody>
				</table>` : `<div class="rep-empty"><b>Nothing here yet</b>
					<span>This list fills in as the branch works.</span></div>`}
			</div>
		</section>`;
	}

	function paintCards(name, data) {
		const cards = (data.cards || []).map((card) => `
			<div class="ctile"><div class="ctile-label">${esc(card.label)}</div>
				<div class="ctile-value">${qty(card.value)}</div></div>`).join("");
		paintRows(name, data.rows || [],
			cards ? `<section class="ctiles stk-subcards">${cards}</section>` : "");
	}

	function paintRequests(data) {
		const inbox = data.inbox || [];
		const rows = data.rows || [];

		$("tab-body").innerHTML = `
			${inbox.length ? `<section class="svc-panel stk-inbox">
				<div class="panel-head"><h2>Requests requiring your action</h2>
					<span class="pill pill-warn">${inbox.length}</span></div>
				${inbox.map((request, index) => `
					<div class="stk-inbox-row">
						<span class="row-main"><b>${esc(request.name)}</b>
							<small>${esc(request.party)} · ${request.items.map((item) =>
								`${qty(item.qty)} × ${esc(item.item_name || item.item_code)}`)
								.join(", ")}</small></span>
						<span class="pill ${tone(request.priority)}">${esc(request.priority || "Normal")}</span>
						<button class="btn btn-outline btn-sm" data-approve="${index}">Approve</button>
						<button class="btn btn-quiet btn-sm" data-reject="${index}">Reject</button>
					</div>`).join("")}
			</section>` : ""}

			<section class="svc-panel bill-table-panel">
				<div class="bill-table-wrap">
					${rows.length ? `<table class="bill-table">
						<thead><tr><th>Request</th><th>Date</th><th>Requested from</th>
							<th class="num">Items</th><th>Priority</th><th>Required by</th>
							<th>Status</th><th>Actions</th></tr></thead>
						<tbody>${rows.map((row) => `<tr>
							<td><b>${esc(row.name)}</b></td>
							<td class="nowrap">${esc(day(row.date))}</td>
							<td>${esc(row.party)}</td>
							<td class="num">${row.items}</td>
							<td>${esc(row.priority || "Normal")}</td>
							<td class="nowrap">${esc(day(row.required))}</td>
							<td><span class="pill ${tone(row.status)}">${esc(row.status)}</span></td>
							<td class="bill-actions">
								<button class="icon-btn plain" data-print="Stock Request|${esc(row.name)}"
								        title="Print">${icon("print")}</button>
							</td></tr>`).join("")}</tbody>
					</table>` : `<div class="rep-empty"><b>No requests yet</b>
						<span>Ask another branch when the shelf runs short.</span></div>`}
				</div>
			</section>`;

		wireInbox(inbox);
		wirePrint();
	}

	function wireInbox(inbox) {
		document.querySelectorAll("[data-approve]").forEach((node) => {
			node.addEventListener("click", () => approve(inbox[Number(node.dataset.approve)]));
		});
		document.querySelectorAll("[data-reject]").forEach((node) => {
			node.addEventListener("click", () => reject(inbox[Number(node.dataset.reject)]));
		});
	}

	function wirePrint() {
		document.querySelectorAll("[data-print]").forEach((node) => {
			node.addEventListener("click", () => {
				const [doctype, name] = node.dataset.print.split("|");
				print(doctype, name);
			});
		});
	}

	function paintTransfers(data) {
		const rows = data.rows || [];
		$("tab-body").innerHTML = `
			<div class="seg stk-subtabs">
				${["incoming", "outgoing"].map((key) =>
					`<button class="seg-btn ${key === state.sub ? "is-active" : ""}"
					        data-sub="${key}">${key === "incoming" ? "Incoming" : "Outgoing"}</button>`)
					.join("")}
			</div>
			<section class="svc-panel bill-table-panel">
				<div class="bill-table-wrap">
					${rows.length ? `<table class="bill-table">
						<thead><tr><th>Transfer</th><th>Date</th><th>From</th><th>To</th>
							<th class="num">Items</th><th class="num">Qty</th><th>Status</th>
							<th>Dispatched</th><th>Actions</th></tr></thead>
						<tbody>${rows.map((row) => `<tr>
							<td><b>${esc(row.name)}</b></td>
							<td class="nowrap">${esc(day(row.date))}</td>
							<td>${esc(row.from)}</td><td>${esc(row.to)}</td>
							<td class="num">${row.items}</td><td class="num">${qty(row.qty)}</td>
							<td><span class="pill ${tone(row.status)}">${esc(row.status)}</span></td>
							<td class="nowrap">${esc(row.dispatched || "—")}</td>
							<td class="bill-actions">
								${state.sub === "outgoing" && row.status === "Approved"
									? `<button class="btn btn-orange btn-sm"
									     data-dispatch="${esc(row.name)}">Dispatch</button>` : ""}
								${state.sub === "incoming" && row.status === "In Transit"
									? `<button class="btn btn-save btn-sm"
									     data-receive="${esc(row.name)}">Receive</button>` : ""}
								<button class="icon-btn plain" data-print="Stock Request|${esc(row.name)}"
								        title="Print">${icon("print")}</button>
							</td></tr>`).join("")}</tbody>
					</table>` : `<div class="rep-empty"><b>No ${state.sub} transfers</b>
						<span>Approved requests appear here on their way.</span></div>`}
				</div>
			</section>`;

		document.querySelectorAll("[data-sub]").forEach((node) => {
			node.addEventListener("click", () => { state.sub = node.dataset.sub; loadTab("transfers"); });
		});
		document.querySelectorAll("[data-dispatch]").forEach((node) => {
			node.addEventListener("click", () => dispatch(node.dataset.dispatch));
		});
		document.querySelectorAll("[data-receive]").forEach((node) => {
			node.addEventListener("click", () => openReceive(node.dataset.receive));
		});
		wirePrint();
	}

	function paintReceipts(data) {
		const rows = data.rows || [];
		$("tab-body").innerHTML = `<section class="svc-panel bill-table-panel">
			<div class="bill-table-wrap">
				${rows.length ? `<table class="bill-table">
					<thead><tr><th>Transfer</th><th>From</th><th>Dispatched</th>
						<th class="num">Items</th><th>Status</th><th>Actions</th></tr></thead>
					<tbody>${rows.map((row) => `<tr>
						<td><b>${esc(row.name)}</b></td>
						<td>${esc(row.party)}</td>
						<td class="nowrap">${esc(row.date || "—")}</td>
						<td class="num">${row.items.length}</td>
						<td><span class="pill ${tone(row.status)}">${esc(row.status)}</span></td>
						<td class="bill-actions">
							<button class="btn btn-save btn-sm" data-receive="${esc(row.name)}">
								Acknowledge receipt</button>
							<button class="icon-btn plain" data-print="Stock Request|${esc(row.name)}"
							        title="Print">${icon("print")}</button>
						</td></tr>`).join("")}</tbody>
				</table>` : `<div class="rep-empty"><b>Nothing waiting to be received</b>
					<span>Transfers on their way here show up in this list.</span></div>`}
			</div>
		</section>`;

		document.querySelectorAll("[data-receive]").forEach((node) => {
			node.addEventListener("click", () => openReceive(node.dataset.receive));
		});
		wirePrint();
	}

	// ------------------------------------------------------------- network
	async function showNetwork(row) {
		$("network-body").innerHTML = '<div class="pos-loading">Looking across the branches…</div>';
		$("network-modal").hidden = false;

		const data = await A3.call("a3_retail.api.stock_control.network",
			{ item_code: row.item_code });
		$("network-note").textContent =
			`${data.item_name} · ${data.item_code} · ${qty(data.network_qty)} across the network`;

		$("network-body").innerHTML = `
			<div class="stk-reco">${esc(data.recommendation)}</div>
			<table class="bill-table">
				<thead><tr><th>Branch</th><th>Warehouse</th><th class="num">Available</th>
					<th class="num">Reserved</th><th class="num">Incoming</th><th>Status</th>
					<th>Action</th></tr></thead>
				<tbody>${data.branches.map((branch, index) => `<tr>
					<td><b>${esc(branch.branch)}</b>${branch.is_mine
						? ' <span class="pill pill-sky">This branch</span>' : ""}</td>
					<td class="nowrap">${esc(branch.warehouse)}</td>
					<td class="num strong">${qty(branch.available)}</td>
					<td class="num">${qty(branch.reserved)}</td>
					<td class="num">${qty(branch.incoming)}</td>
					<td><span class="pill ${tone(branch.status)}">${esc(branch.status)}</span></td>
					<td>${branch.is_mine ? "—"
						: `<button class="btn btn-outline btn-sm" data-from="${index}">Request</button>`}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		$("network-body").querySelectorAll("[data-from]").forEach((node) => {
			node.addEventListener("click", () => {
				const branch = data.branches[Number(node.dataset.from)];
				$("network-modal").hidden = true;
				openRequest(row, branch.branch);
			});
		});
	}

	// --------------------------------------------------------------- work
	function openWork(title, note, body, action, go) {
		$("work-title").textContent = title;
		$("work-note").textContent = note;
		$("work-body").innerHTML = body;
		$("work-go").textContent = action;
		$("work-msg").textContent = "";
		$("work-modal").hidden = false;
		state.work = go;
	}

	function say(text, kind) {
		$("work-msg").textContent = text || "";
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	async function openRequest(row, source) {
		const branches = state.boot.branches;
		startLines(row);
		openWork("Request stock",
			`${row ? row.item_name + " · " : ""}Ask another branch to send stock here.`,
			`<div class="field-grid three">
				<label class="field"><span>Request from</span>
					<select id="w-source">${branches.map((branch) =>
						`<option value="${esc(branch)}"${branch === source ? " selected" : ""}>${
							esc(branch)}</option>`).join("")}</select></label>
				<label class="field"><span>Priority</span>
					<select id="w-priority"><option>Normal</option><option>Urgent</option></select></label>
				<label class="field"><span>Required by</span>
					<input id="w-required" type="date"></label>
			</div>
			${linesMarkup()}
			<label class="field"><span>Purpose</span>
				<select id="w-purpose">
					<option>Stock Balancing</option><option>Customer Sale</option>
					<option>Service Job Card</option></select></label>`,
			"Send request",
			async () => {
				const result = await A3.call("a3_retail.api.stock_control.create_request", {
					payload: {
						source_branch: $("w-source").value,
						priority: $("w-priority").value,
						required_by: $("w-required").value || null,
						purpose: $("w-purpose").value,
						items: linesPayload(),
					},
				});
				toast(`${result.request} sent to ${$("w-source").value}.`, "ok");
				loadTab("requests");
				loadKpis();
			});
	}

	function openProcure(row) {
		openWork("Request procurement",
			"Nothing in the network — ask head office to buy it. This raises a Material Request.",
			`<div class="field-grid">
				<label class="field"><span>Item</span>
					<input id="w-item" value="${esc(row ? row.item_code : "")}"
					       placeholder="Item code"></label>
				<label class="field"><span>Quantity</span>
					<input id="w-qty" type="number" min="1" step="1" value="1"></label>
			</div>
			<div class="field-grid">
				<label class="field"><span>Required by</span><input id="w-required" type="date"></label>
				<label class="field"><span>Reason</span>
					<input id="w-reason" placeholder="Why this is needed"></label>
			</div>`,
			"Raise request",
			async () => {
				const result = await A3.call("a3_retail.api.stock_control.request_procurement", {
					payload: {
						required_by: $("w-required").value || null,
						reason: $("w-reason").value.trim(),
						items: linesPayload(),
					},
				});
				toast(`${result.material_request} raised.`, "ok");
				loadTab("purchases");
			});
	}

	/**
	 * Lines a move or a request carries.
	 *
	 * The counter is usually shifting a handful of things at once — three
	 * chargers and a phone — and raising four documents for that was the reason
	 * nobody used the screen. Kept here so the move and the request behave the
	 * same way.
	 */
	let workLines = [];

	function linesMarkup() {
		return `<div class="work-lines" id="w-lines"></div>
			<button class="btn btn-quiet btn-block" id="w-add" type="button">
				+ Add another item</button>`;
	}

	function paintLines() {
		const host = $("w-lines");
		if (!host) return;
		host.innerHTML = workLines.map((line, index) => `
			<div class="field-grid work-line">
				<label class="field"><span>${index ? "" : "Item"}</span>
					<input class="w-code" data-i="${index}" value="${esc(line.item_code)}"
					       placeholder="Type the item name or scan it" autocomplete="off"></label>
				<label class="field"><span>${index ? "" : "Quantity"}</span>
					<input class="w-num" data-i="${index}" inputmode="numeric"
					       value="${line.qty || ""}"
					       ${line.serials ? "readonly title='Counted from the IMEIs'" : ""}></label>
				<button class="btn btn-quiet work-drop" data-i="${index}" type="button"
				        ${workLines.length > 1 ? "" : "disabled"}>×</button>
			</div>
			<div class="w-hits" data-i="${index}"></div>
			${line.serials ? imeiMarkup(line, index) : ""}`).join("");

		// Typing must not redraw the row — replacing an input mid-keystroke takes
		// the focus with it.
		host.querySelectorAll(".w-code").forEach((n) => {
			let timer = null;
			n.addEventListener("input", () => {
				const i = Number(n.dataset.i);
				workLines[i].item_code = n.value.trim();
				clearTimeout(timer);
				timer = setTimeout(() => suggest(i, n.value.trim()), 200);
			});
			// Leaving the box is the moment to find out whether this one is a
			// handset, and if it is, which handsets are on that shelf — but only
			// when the item has actually changed. Repainting every line on every
			// blur is what used to wipe the suggestion the cursor was heading
			// for.
			n.addEventListener("change", () => {
				const i = Number(n.dataset.i);
				if (workLines[i].item_code !== workLines[i].loaded_for) loadSerials(i);
			});
		});
		host.querySelectorAll(".w-num").forEach((n) => n.addEventListener("input", () => {
			workLines[Number(n.dataset.i)].qty = Number(n.value) || 0;
		}));
		host.querySelectorAll(".work-drop").forEach((n) => n.addEventListener("click", () => {
			workLines.splice(Number(n.dataset.i), 1);
			paintLines();
		}));
		// The gun sends the digits then Enter, so this runs once per handset.
		host.querySelectorAll(".w-scan").forEach((n) => n.addEventListener("keydown", (event) => {
			if (event.key !== "Enter") return;
			event.preventDefault();
			scanSerial(Number(n.dataset.i), n.value);
			n.value = "";
		}));
		host.querySelectorAll(".w-imei").forEach((n) => n.addEventListener("change", () => {
			const line = workLines[Number(n.dataset.i)];
			const imei = n.value;
			if (n.checked) line.picked.push(imei);
			else line.picked = line.picked.filter((s) => s !== imei);
			line.qty = line.picked.length;
			const count = host.querySelector(`.w-imei-count[data-i="${n.dataset.i}"]`);
			if (count) count.textContent = line.picked.length + "/" + line.serials.length;
			const qty = host.querySelector(`.w-num[data-i="${n.dataset.i}"]`);
			if (qty) qty.value = line.qty || "";
		}));
	}

	/** What is on the shelf the stock is leaving. Offering the whole catalogue
	 *  here is how somebody picks a line that then fails on submit for want of
	 *  stock, so only what that warehouse actually holds is listed. */
	async function suggest(index, query) {
		const host = $("w-lines");
		const box = host && host.querySelector(`.w-hits[data-i="${index}"]`);
		if (!box) return;
		await fillHits(box, query, $("w-source") ? $("w-source").value : null, (code) => {
			workLines[index].item_code = code;
			const input = host.querySelector(`.w-code[data-i="${index}"]`);
			if (input) input.value = code;
			loadSerials(index);
		});
	}

	/** The same list for any dialog that needs one: by element id rather than by
	 *  line, because the adjustment screen counts one item, not a basket. */
	async function suggestInto(boxId, query, warehouse, pick) {
		const box = $(boxId);
		if (box) await fillHits(box, query, warehouse, pick);
	}

	async function fillHits(box, query, warehouse, pick) {
		if (!warehouse || query.length < 2) { box.innerHTML = ""; return; }
		let rows = [];
		try {
			rows = await A3.call("a3_retail.api.stock_control.search_stock",
			                     { query, warehouse, limit: 8 });
		} catch (error) {
			box.innerHTML = `<p class="muted">${esc(error.message || "Could not search.")}</p>`;
			return;
		}
		if (!rows.length) {
			box.innerHTML = `<p class="muted">Nothing by that name in ${esc(warehouse)}.</p>`;
			return;
		}
		box.innerHTML = rows.map((r) => `
			<button type="button" class="w-hit" data-code="${esc(r.item_code)}">
				<span>${esc(r.item_name)}${r.has_serial ? " <small>IMEI</small>" : ""}</span>
				<b>${qty(r.available)} ${esc(r.stock_uom || "")}</b>
			</button>`).join("");
		// `mousedown`, not `click`, and the default suppressed with it. Clicking
		// one of these takes focus off the box above, which fires its `change`
		// and repaints the lines — and the repaint replaced this button before
		// the click could land on it. The pick silently did nothing and the
		// typed text stayed behind, so the move was attempted against whatever
		// had been half-typed.
		box.querySelectorAll(".w-hit").forEach((node) => {
			node.addEventListener("mousedown", (event) => {
				event.preventDefault();
				box.innerHTML = "";
				pick(node.dataset.code);
			});
		});
	}

	/** A serialised item moves by IMEI: the shop is not moving "two phones", it
	 *  is moving these two. The list is what is actually on the source shelf, so
	 *  a number that has already gone cannot be picked by mistake. */
	function imeiMarkup(line, index) {
		if (!line.serials.length) {
			return `<p class="muted w-imei-none">No IMEIs of that item in this warehouse.</p>`;
		}
		// Scanned rather than hunted for. A shelf can hold forty of the same
		// handset, and finding one number in that list by eye is slower than
		// reading the box — so the gun goes to the top, as it does on a
		// purchase, and the list below is there to check the tally and to
		// correct a mis-scan.
		return `<div class="w-imei-box">
			<div class="imei-scan-row">
				<span class="scan-glyph" aria-hidden="true"></span>
				<input class="w-scan" data-i="${index}" autocomplete="off" inputmode="numeric"
				       placeholder="Scan the IMEI on the box, or type it and press Enter">
				<span class="imei-tally w-imei-count" data-i="${index}"
				      >${line.picked.length}/${line.serials.length}</span>
			</div>
			<div class="imei-flash w-flash" data-i="${index}" hidden></div>
			<div class="w-imei-head">On this shelf
				<b>${line.picked.length ? line.picked.length + " going" : "none picked yet"}</b></div>
			<ul class="imei-list">${line.serials.map((imei) => `
				<li><label><input type="checkbox" class="w-imei" data-i="${index}"
				        value="${esc(imei)}" ${line.picked.includes(imei) ? "checked" : ""}>
					<span>${esc(imei)}</span></label></li>`).join("")}</ul>
		</div>`;
	}

	/** One scan, against the handsets actually on the shelf being emptied. */
	function scanSerial(index, raw) {
		const line = workLines[index];
		const imei = (raw || "").trim();
		if (!line || !line.serials || !imei) return;
		const flash = (text, kind) => {
			const node = $("w-lines").querySelector(`.w-flash[data-i="${index}"]`);
			if (!node) return;
			node.textContent = text;
			node.className = "imei-flash w-flash" + (kind ? " " + kind : "");
			node.hidden = !text;
		};
		// Matched loosely, because a scanner reads the whole label and a person
		// types the digits — but only against this shelf, so a handset that has
		// already gone cannot be sent twice.
		const found = line.serials.find(
			(s) => s === imei || s.replace(/\s/g, "") === imei.replace(/\s/g, ""));
		if (!found) {
			flash(`${imei} is not on this shelf.`, "warn");
			return;
		}
		if (line.picked.includes(found)) {
			flash(`${found} is already going.`, "warn");
			return;
		}
		line.picked.push(found);
		line.qty = line.picked.length;
		flash(`${found} added`, "ok");
		const host = $("w-lines");
		const box = host.querySelector(
			`.w-imei[data-i="${index}"][value="${found.replace(/"/g, "&quot;")}"]`);
		if (box) box.checked = true;
		const tally = host.querySelector(`.w-imei-count[data-i="${index}"]`);
		if (tally) tally.textContent = `${line.picked.length}/${line.serials.length}`;
		const qty = host.querySelector(`.w-num[data-i="${index}"]`);
		if (qty) qty.value = line.qty || "";
	}

	async function loadSerials(index) {
		const line = workLines[index];
		const source = $("w-source") ? $("w-source").value : null;
		if (!line.item_code || !source) return;
		let rows = [];
		try {
			rows = await A3.call("a3_retail.api.stock.serial_list",
			                     { item_code: line.item_code, warehouse: source, limit: 200 });
		} catch (error) {
			rows = [];
		}
		// No serials in stock means the item is not tracked that way, and the
		// plain quantity box is the right thing to leave in place.
		line.serials = rows.length ? rows.map((r) => r.serial_no || r.name) : null;
		line.picked = [];
		line.loaded_for = line.item_code;
		if (line.serials) line.qty = 0;
		paintLines();
		// Straight on to the next thing the person has to do: the number on the
		// box if this is a handset, otherwise how many are going.
		const host = $("w-lines");
		const next = host && host.querySelector(
			line.serials ? `.w-scan[data-i="${index}"]` : `.w-num[data-i="${index}"]`);
		if (next) next.focus();
	}

	function startLines(row) {
		workLines = [{ item_code: row ? row.item_code : "", qty: 1,
		               serials: null, picked: [] }];
		setTimeout(() => {
			paintLines();
			if (workLines[0].item_code) loadSerials(0);
			const add = $("w-add");
			if (add) add.addEventListener("click", () => {
				workLines.push({ item_code: "", qty: 1, serials: null, picked: [] });
				paintLines();
			});
			// Changing where the stock comes from changes which handsets are on
			// offer, so every line has to be asked again.
			const source = $("w-source");
			if (source) source.addEventListener("change", () => {
				workLines.forEach((_, i) => loadSerials(i));
			});
		}, 0);
	}

	const linesPayload = () => workLines
		.filter((l) => l.item_code && l.qty > 0)
		.map((l) => ({ item_code: l.item_code, qty: l.qty,
		               serials: l.serials ? l.picked : [] }));

	function openMove() {
		const options = (state.network || []).map((w) =>
			`<option value="${esc(w.warehouse)}">${esc(w.label)}</option>`).join("");

		startLines(null);
		openWork("Move stock",
			"Any warehouse in the chain to any other. Creates a Stock Entry — Material Transfer.",
			`<div class="field-grid">
				<label class="field"><span>From</span><select id="w-source">${options}</select></label>
				<label class="field"><span>To</span><select id="w-target">${options}</select></label>
			</div>
			${linesMarkup()}
			<label class="field"><span>Remarks</span><input id="w-remarks"></label>`,
			"Move it",
			async () => {
				const short = workLines.find((l) => l.item_code && l.serials
				                                    && l.picked.length === 0);
				if (short) throw new Error(
					short.item_code + " moves by IMEI — pick which handsets are going.");
				const result = await A3.call("a3_retail.api.stock_control.move_stock", {
					payload: {
						source: $("w-source").value, target: $("w-target").value,
						remarks: $("w-remarks").value.trim(),
						items: linesPayload(),
					},
				});
				toast(`Moved — ${result.stock_entry}.`, "ok");
				loadStock();
				loadKpis();
				loadSide();
			});

		// The list is every warehouse in the chain, in branch order, so without
		// this it opened on whichever branch sorts first — and the item search,
		// which only offers what is actually on the shelf it is pointed at,
		// then found nothing for stock the counter can see in front of them.
		// Stock moves out of your own shop far more often than into it.
		const mine = (state.boot.warehouses || [])[0];
		if (mine) $("w-source").value = mine;
		const elsewhere = (state.network || []).find(
			(w) => w.warehouse !== $("w-source").value);
		if (elsewhere) $("w-target").value = elsewhere.warehouse;
	}

	function openAdjust() {
		const options = state.boot.warehouses.map((warehouse) =>
			`<option value="${esc(warehouse)}">${esc(warehouse)}</option>`).join("");

		openWork("Stock adjustment",
			"Correct the system against what is actually on the shelf. Creates a Stock "
			+ "Reconciliation — the count you enter becomes the new quantity.",
			`<div class="field-grid">
				<label class="field"><span>Warehouse</span>
					<select id="w-warehouse">${options}</select></label>
				<label class="field"><span>Item</span>
					<input id="w-item" placeholder="Type the item name or scan it"
					       autocomplete="off"></label>
			</div>
			<div class="w-hits" id="w-item-hits"></div>
			<div class="field-grid">
				<label class="field"><span>Counted quantity</span>
					<input id="w-qty" type="number" min="0" step="1" value="0"></label>
				<label class="field"><span>Reason</span>
					<input id="w-reason" placeholder="Why the count differs"></label>
			</div>`,
			"Submit adjustment",
			async () => {
				if (!$("w-item").value.trim()) throw new Error("Pick the item being counted.");
				const result = await A3.call("a3_retail.api.stock_control.adjust_stock", {
					payload: {
						warehouse: $("w-warehouse").value, reason: $("w-reason").value.trim(),
						items: [{ item_code: $("w-item").value.trim(),
						          counted: Number($("w-qty").value) || 0 }],
					},
				});
				toast(`${result.adjustment} submitted (${money(result.difference)}).`, "ok");
				loadStock();
				loadKpis();
				loadTab("adjustments");
			});

		// The same search as Move stock, against the shelf being counted. A
		// reconciliation sets a figure, so picking an item the warehouse does not
		// hold is how stock gets conjured out of a typo.
		setTimeout(() => {
			const field = $("w-item");
			if (!field) return;
			let timer = null;
			const run = () => suggestInto("w-item-hits", field.value.trim(),
			                              $("w-warehouse").value, (code) => {
				field.value = code;
			});
			field.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 200); });
			$("w-warehouse").addEventListener("change", run);
		}, 0);
	}

	/** Add something new to the catalogue, and optionally what is already on the shelf. */
	function openNewItem() {
		const groups = (state.boot.item_groups || []).map((group) =>
			`<option value="${esc(group)}">${esc(group)}</option>`).join("");
		const brands = `<option value="">—</option>` + (state.boot.brands || []).map((brand) =>
			`<option value="${esc(brand)}">${esc(brand)}</option>`).join("");
		const uoms = (state.boot.uoms || ["Nos"]).map((uom) =>
			`<option value="${esc(uom)}"${uom === "Nos" ? " selected" : ""}>${esc(uom)}</option>`)
			.join("");
		const warehouses = (state.boot.warehouses || []).map((warehouse) =>
			`<option value="${esc(warehouse)}">${esc(warehouse)}</option>`).join("");

		openWork("New item",
			"Adds to the catalogue for every branch, so check it is not already there. "
			+ "Leave the opening quantity at zero if the stock has not arrived yet.",
			`<div class="field-grid">
				<label class="field"><span>Item name</span>
					<input id="w-name" placeholder="What it is called on the shelf"></label>
				<label class="field"><span>Item code</span>
					<input id="w-code" placeholder="Left blank, the name is used"></label>
			</div>
			<div class="field-grid three">
				<label class="field"><span>Item group</span>
					<select id="w-group">${groups}</select></label>
				<label class="field"><span>Brand</span>
					<select id="w-brand">${brands}</select></label>
				<label class="field"><span>Unit</span>
					<select id="w-uom">${uoms}</select></label>
			</div>
			<div class="field-grid three">
				<label class="field"><span>HSN code</span>
					<input id="w-hsn" placeholder="Ask accounts"></label>
				<label class="field"><span>Selling price</span>
					<input id="w-sell" type="number" min="0" step="1" placeholder="0"></label>
				<label class="field"><span>Cost per piece</span>
					<input id="w-cost" type="number" min="0" step="1" placeholder="0"></label>
			</div>
			<div class="field-grid three">
				<label class="field"><span>Opening quantity</span>
					<input id="w-qty" type="number" min="0" step="1" value="0"></label>
				<label class="field"><span>Into warehouse</span>
					<select id="w-warehouse">${warehouses}</select></label>
				<label class="field"><span>Barcode</span>
					<input id="w-barcode" placeholder="Optional"></label>
			</div>
			<label class="field check">
				<input id="w-serial" type="checkbox">
				<span>Track each piece by IMEI or serial number</span></label>`,
			"Add item",
			async () => {
				const name = $("w-name").value.trim();
				if (!name) throw new Error("Give the item a name.");
				const qty = Number($("w-qty").value) || 0;
				const cost = Number($("w-cost").value) || 0;
				const sell = Number($("w-sell").value) || 0;
				if (qty > 0 && !cost && !sell) {
					throw new Error("Opening stock needs a cost per piece, so the stock has a value.");
				}

				const result = await A3.call("a3_retail.api.stock_control.create_item", {
					payload: {
						item_name: name,
						item_code: $("w-code").value.trim(),
						item_group: $("w-group").value,
						brand: $("w-brand").value,
						uom: $("w-uom").value,
						hsn_code: $("w-hsn").value.trim(),
						selling_rate: sell,
						purchase_rate: cost,
						opening_qty: qty,
						warehouse: $("w-warehouse").value,
						barcode: $("w-barcode").value.trim(),
						has_serial: $("w-serial").checked ? 1 : 0,
					},
				});
				toast(result.opening_qty
					? `${result.item_code} added with ${result.opening_qty} in stock.`
					: `${result.item_code} added to the catalogue.`, "ok");
				loadStock();
				loadKpis();
			});
	}

	async function openReceive(request) {
		const data = await A3.call("a3_retail.api.stock_control.tab", { name: "receipts" });
		const row = (data.rows || []).find((entry) => entry.name === request);
		if (!row) return toast("That transfer is no longer waiting to be received.", "error");

		openWork("Receive stock",
			`${row.name} from ${row.party} · dispatched ${row.date || "—"}`,
			`<table class="bill-table">
				<thead><tr><th>Item</th><th class="num">Sent</th><th class="num">Received</th></tr></thead>
				<tbody>${row.items.map((item, index) => `<tr>
					<td>${esc(item.item_name || item.item_code)}
						<small>${esc(item.item_code)}</small></td>
					<td class="num">${qty(item.qty)}</td>
					<td class="num"><input class="rate" type="number" min="0" step="1"
						data-item="${esc(item.item_code)}" value="${item.qty}"></td>
				</tr>`).join("")}</tbody>
			</table>
			<label class="field"><span>Reason, if anything is short</span>
				<input id="w-reason" placeholder="Damaged in transit, short packed…"></label>`,
			"Confirm receipt",
			async () => {
				const received = {};
				document.querySelectorAll("#work-body [data-item]").forEach((node) => {
					received[node.dataset.item] = Number(node.value) || 0;
				});
				const result = await A3.call("a3_retail.api.stock_control.receive_request", {
					request, received, reason: $("w-reason").value.trim() || null,
				});
				toast(result.short.length
					? `Received short — ${result.stock_entry} posted for what arrived.`
					: `Received — ${result.stock_entry} posted.`, "ok");
				loadTab("receipts");
				loadStock();
				loadKpis();
				loadSide();
			});
	}

	async function approve(request) {
		openWork(`Approve ${request.name}`,
			`${request.party} asked for these. The quantities you approve are what will move.`,
			`<table class="bill-table">
				<thead><tr><th>Item</th><th class="num">Asked</th><th class="num">Here</th>
					<th class="num">Approve</th></tr></thead>
				<tbody>${request.items.map((item) => `<tr>
					<td>${esc(item.item_name || item.item_code)}</td>
					<td class="num">${qty(item.qty)}</td>
					<td class="num ${item.available < item.qty ? "warn-red" : ""}">${
						qty(item.available)}</td>
					<td class="num"><input class="rate" type="number" min="0" step="1"
						data-item="${esc(item.item_code)}"
						value="${Math.min(item.qty, item.available)}"></td>
				</tr>`).join("")}</tbody>
			</table>`,
			"Approve",
			async () => {
				const quantities = {};
				document.querySelectorAll("#work-body [data-item]").forEach((node) => {
					quantities[node.dataset.item] = Number(node.value) || 0;
				});
				await A3.call("a3_retail.api.stock_control.approve_request",
					{ request: request.name, qty_by_item: quantities });
				toast(`${request.name} approved — dispatch it from Transfers.`, "ok");
				loadTab("requests");
				loadKpis();
			});
	}

	function reject(request) {
		openWork(`Reject ${request.name}`,
			`${request.party} asked for stock this branch cannot spare. Say why.`,
			'<label class="field"><span>Reason</span><input id="w-reason"></label>',
			"Reject",
			async () => {
				await A3.call("a3_retail.api.stock_control.reject_request",
					{ request: request.name, reason: $("w-reason").value.trim() });
				toast(`${request.name} rejected.`, "ok");
				loadTab("requests");
				loadKpis();
			});
	}

	async function dispatch(request) {
		try {
			const result = await A3.call("a3_retail.api.stock_control.dispatch_request", { request });
			toast(`Dispatched — ${result.stock_entry} posted to transit.`, "ok");
			loadTab("transfers");
			loadStock();
			loadKpis();
		} catch (error) {
			toast(error.message, "error");
		}
	}

	// --------------------------------------------------------------- start
	let searchTimer;
	async function start(options) {
		state.branch = options.branch;
		state.boot = await A3.call("a3_retail.api.stock_control.bootstrap", {});
		// Every warehouse in the chain, so a move or a request can name any of
		// them rather than only this branch's own shelves.
		state.network = await A3.call("a3_retail.api.stock_control.network_warehouses", {})
			.catch(() => (state.boot.warehouses || []).map((w) => ({ warehouse: w, label: w })));

		$("item-group").innerHTML += state.boot.item_groups.map((group) =>
			`<option value="${esc(group)}">${esc(group)}</option>`).join("");
		$("brand").innerHTML += state.boot.brands.map((brand) =>
			`<option value="${esc(brand)}">${esc(brand)}</option>`).join("");
		$("warehouse").innerHTML += state.boot.warehouses.map((warehouse) =>
			`<option value="${esc(warehouse)}">${esc(warehouse)}</option>`).join("");

		// Not every counter does every one of these, and the matrix in
		// `setup/permissions.py` decides which. A button that is going to be
		// refused is worse than no button: it is offered, the dialog is filled
		// in, and the refusal lands after the work — so each one is shown only
		// to whoever can actually finish it.
		const can = state.boot.can || {};
		const ALLOWED = {
			"new-item": "create_item", "request": "request", "procure": "procure",
			"move": "transfer", "adjust": "adjust",
		};
		document.querySelectorAll("[data-do]").forEach((node) => {
			const needs = ALLOWED[node.dataset.do];
			if (needs) node.hidden = !can[needs];
		});

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				loadStock(1);
				loadKpis();
			}, 220);
		});
		[["item-group", "item_group"], ["brand", "brand"], ["warehouse", "warehouse"],
		 ["status", "status"], ["kind", "kind"]].forEach(([id, key]) => {
			$(id).addEventListener("change", () => {
				state.filters[key] = $(id).value;
				loadStock(1);
				loadKpis();
			});
		});
		$("clear").addEventListener("click", () => {
			state.filters = {};
			["q", "item-group", "brand", "warehouse"].forEach((id) => { $(id).value = ""; });
			$("status").value = "all";
			$("kind").value = "all";
			loadStock(1);
			loadKpis();
		});

		$("tabs").addEventListener("click", (event) => {
			const tab = event.target.closest(".tab");
			if (!tab) return;
			$("tabs").querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
			tab.classList.add("is-active");
			loadTab(tab.dataset.tab);
		});

		document.querySelectorAll("[data-do]").forEach((node) => {
			node.addEventListener("click", () => {
				const what = node.dataset.do;
				if (what === "request") return openRequest(null);
				if (what === "procure") return openProcure(null);
				if (what === "move") return openMove();
				if (what === "adjust") return openAdjust();
				if (what === "new-item") return openNewItem();
				if (what === "receive") {
					state.tab = "receipts";
					$("tabs").querySelectorAll(".tab").forEach((t) =>
						t.classList.toggle("is-active", t.dataset.tab === "receipts"));
					return loadTab("receipts");
				}
			});
		});

		$("work-go").addEventListener("click", async () => {
			if (!state.work) return;
			$("work-go").disabled = true;
			say("Working…");
			try {
				await state.work();
				$("work-modal").hidden = true;
			} catch (error) {
				say(error.message, "error");
			} finally {
				$("work-go").disabled = false;
			}
		});
		$("refresh").addEventListener("click", () => { loadAll(); toast("Refreshed."); });

		$("item-save").addEventListener("click", saveItem);
		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		loadAll();
	}

	return { start, state };
})();
