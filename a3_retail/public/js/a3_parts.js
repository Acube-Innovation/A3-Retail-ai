// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Spare parts and accessories — one page for both shelves.
 *
 * The toggle at the top changes which shelf is open; everything else is the
 * same screen, because a counter treats them the same way. Four things happen
 * to a part and all four are documents somebody can look up later: it goes on a
 * repair, it is sold, it replaces one that failed, or it comes back to the
 * shelf.
 */

window.PARTS = (function () {
	const state = { branch: "", kind: "parts", boot: null, rows: [], tab: "waiting",
	                filters: {}, work: null };
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
			"Healthy": "pill-good", "Issued": "pill-good", "Received": "pill-good",
			"Low Stock": "pill-warn", "Required": "pill-warn", "Awaiting Transfer": "pill-warn",
			"Awaiting Purchase": "pill-warn", "Draft": "pill-sky", "Returned": "pill-sky",
			"Out of Stock": "pill-bad", "Out": "pill-bad", "In": "pill-good",
			"Warranty": "pill-purple", "Dispatched": "pill-sky",
		}[status] || "pill-sky";
	}

	// ------------------------------------------------------------- loading
	async function loadAll() {
		$("title").innerHTML = `${state.kind === "parts" ? "Spare Parts" : "Accessories"}
			<span class="chip">${esc(state.branch)}</span>`;
		$("shelf-title").textContent = state.kind === "parts" ? "Spare Parts" : "Accessories";
		await Promise.all([loadKpis(), loadShelf(), loadTab(state.tab)]);
	}

	async function loadKpis() {
		const kpis = await A3.call("a3_retail.api.parts_desk.kpis", { kind: state.kind });
		$("kpis").innerHTML = Object.keys(kpis).map((key) => {
			const card = kpis[key];
			return `<button class="ctile stk-kpi" data-kpi="${key}">
				<div class="ctile-label">${esc(card.label)}</div>
				<div class="ctile-value ${card.tone === "bad" ? "warn-red"
					: card.tone === "warn" ? "amber" : card.tone === "good" ? "good" : ""}">${
					card.money ? money(card.value) : qty(card.value)}</div>
			</button>`;
		}).join("");

		$("kpis").querySelectorAll("[data-kpi]").forEach((node) => {
			node.addEventListener("click", () => {
				const card = kpis[node.dataset.kpi];
				if (card.filter) {
					state.filters.status = card.filter;
					$("status").value = card.filter;
					loadShelf();
				}
				if (card.tab) {
					$("tabs").querySelectorAll(".tab").forEach((t) =>
						t.classList.toggle("is-active", t.dataset.tab === card.tab));
					loadTab(card.tab);
				}
			});
		});
	}

	async function loadShelf() {
		$("shelf").innerHTML = '<div class="pos-loading">Reading the shelf…</div>';
		state.rows = await A3.call("a3_retail.api.parts_desk.catalogue", {
			kind: state.kind, query: state.filters.query || "", brand: state.filters.brand || "",
			status: state.filters.status || "all",
		});

		$("shelf-note").textContent = `${state.rows.length} lines · store ${
			state.boot.store || "—"} · bench ${state.boot.bench || "—"}`;

		if (!state.rows.length) {
			$("shelf").innerHTML = `<div class="rep-empty"><b>Nothing on this shelf</b>
				<span>Try clearing the filters, or request stock from another branch.</span></div>`;
			return;
		}

		$("shelf").innerHTML = `<table class="bill-table prt-table">
			<thead><tr>
				<th>Part</th><th>Code</th><th>Brand</th><th>Fits</th>
				<th class="num">Store</th><th class="num">Bench</th><th class="num">Reserved</th>
				<th class="num">Reorder</th><th class="num">Price</th><th class="num">Waiting</th>
				<th>Status</th><th>Actions</th>
			</tr></thead>
			<tbody>${state.rows.map((row, index) => `
				<tr>
					<td><b>${esc(row.item_name)}</b>${row.has_serial
						? '<small>Serialised</small>' : ""}</td>
					<td class="nowrap">${esc(row.item_code)}</td>
					<td>${esc(row.brand || "—")}</td>
					<td>${row.fits.length
						? row.fits.map((model) => `<span class="pill pill-sky">${esc(model)}</span>`)
							.join(" ")
						: '<span class="rep-when">Any</span>'}</td>
					<td class="num strong">${qty(row.store_qty)}</td>
					<td class="num">${qty(row.bench_qty)}</td>
					<td class="num">${qty(row.reserved)}</td>
					<td class="num">${qty(row.reorder_level)}</td>
					<td class="num">${money(row.rate)}</td>
					<td class="num ${row.waiting ? "warn-red" : ""}">${row.waiting || "—"}</td>
					<td><span class="pill ${tone(row.status)}">${esc(row.status)}</span></td>
					<td class="bill-actions">
						<button class="btn btn-outline btn-sm" data-assign="${index}">Assign</button>
						<button class="btn btn-quiet btn-sm" data-sell="${index}">Sell</button>
						<button class="linkish" data-log="${index}">Movements</button>
					</td>
				</tr>`).join("")}</tbody>
		</table>`;

		$("shelf").querySelectorAll("[data-assign]").forEach((node) => {
			node.addEventListener("click", () => openAssign(state.rows[Number(node.dataset.assign)]));
		});
		$("shelf").querySelectorAll("[data-sell]").forEach((node) => {
			node.addEventListener("click", async () => {
				const row = state.rows[Number(node.dataset.sell)];
				const url = await A3.call("a3_retail.api.parts_desk.sell_url",
					{ item_code: row.item_code });
				window.location = url;
			});
		});
		$("shelf").querySelectorAll("[data-log]").forEach((node) => {
			node.addEventListener("click", () => showLog(state.rows[Number(node.dataset.log)]));
		});
	}

	// ---------------------------------------------------------------- tabs
	const COLUMNS = {
		waiting: [["item_name", "Part"], ["item_code", "Code"], ["required", "Needed", "num"],
		          ["available", "On the shelf", "num"], ["status", "Status", "pill"],
		          ["job_cards", "Repairs"], ["reference", "Chased on"]],
		issued: [["job_card", "Repair"], ["item_name", "Part"], ["qty", "Qty", "num"],
		         ["rate", "Rate", "money"], ["covered", "Charge"], ["status", "Status", "pill"],
		         ["reference", "Stock entry"]],
		movements: [["date", "Date", "date"], ["kind", "Transaction"], ["item_code", "Part"],
		            ["warehouse", "Warehouse"], ["qty", "Qty", "num"],
		            ["balance", "Balance after", "num"], ["reference", "Reference"],
		            ["status", "In / Out", "pill"]],
		replacements: [["name", "Return"], ["supplier", "Supplier"], ["date", "Dispatched", "date"],
		               ["kind", "Type"], ["items", "Items", "num"], ["value", "Claim", "money"],
		               ["status", "Status", "pill"]],
		returns: [["job_card", "Repair"], ["item_name", "Part"], ["qty", "Qty", "num"],
		          ["status", "Status", "pill"], ["reference", "Stock entry"]],
	};

	function cell(row, [key, , kind]) {
		const value = row[key];
		if (value == null || value === "") return "—";
		if (kind === "money") return money(value);
		if (kind === "num") return qty(value);
		if (kind === "date") return esc(day(value));
		if (kind === "pill") return `<span class="pill ${tone(value)}">${esc(value)}</span>`;
		if (key === "job_cards") {
			const cards = String(value).split(",");
			return `${esc(cards[0])}${cards.length > 1
				? ` <span class="rep-when">+${cards.length - 1} more</span>` : ""}`;
		}
		return esc(value);
	}

	async function loadTab(name) {
		state.tab = name;
		$("tab-body").innerHTML = '<div class="pos-loading">Loading…</div>';
		const data = await A3.call("a3_retail.api.parts_desk.tab",
			{ name, kind: state.kind });
		const rows = data.rows || [];
		const columns = COLUMNS[name] || [];

		$("tab-body").innerHTML = `<section class="svc-panel bill-table-panel">
			<div class="bill-table-wrap">
				${rows.length ? `<table class="bill-table">
					<thead><tr>${columns.map(([, label, kind]) =>
						`<th class="${kind === "num" || kind === "money" ? "num" : ""}">${label}</th>`)
						.join("")}${name === "waiting" ? "<th>Action</th>" : ""}</tr></thead>
					<tbody>${rows.map((row, index) => `<tr>${columns.map((column) =>
						`<td class="${column[2] === "num" || column[2] === "money" ? "num" : ""}">${
							cell(row, column)}</td>`).join("")}${name === "waiting"
						? `<td class="bill-actions"><button class="btn btn-outline btn-sm"
							data-chase="${index}">Request</button></td>` : ""}</tr>`).join("")}</tbody>
				</table>` : `<div class="rep-empty"><b>Nothing here</b>
					<span>This list fills in as parts move.</span></div>`}
			</div>
		</section>`;

		$("tab-body").querySelectorAll("[data-chase]").forEach((node) => {
			node.addEventListener("click", () => {
				const row = rows[Number(node.dataset.chase)];
				window.location = "/branch/stock?item=" + encodeURIComponent(row.item_code);
			});
		});
	}

	async function showLog(row) {
		$("log-title").textContent = row.item_name;
		$("log-note").textContent = `${row.item_code} · store ${qty(row.store_qty)} · bench ${
			qty(row.bench_qty)}${row.fits.length ? " · fits " + row.fits.join(", ") : ""}`;
		$("log-body").innerHTML = '<div class="pos-loading">Reading the ledger…</div>';
		$("log-modal").hidden = false;

		const rows = await A3.call("a3_retail.api.parts_desk.movements_for",
			{ item_code: row.item_code });
		$("log-body").innerHTML = rows.length
			? `<table class="bill-table">
				<thead><tr><th>Date</th><th>Transaction</th><th>Reference</th><th>Warehouse</th>
					<th class="num">Qty</th><th class="num">Balance</th><th>In / Out</th></tr></thead>
				<tbody>${rows.map((entry) => `<tr>
					<td class="nowrap">${esc(day(entry.date))}</td>
					<td>${esc(entry.kind)}</td>
					<td class="nowrap">${esc(entry.reference)}</td>
					<td class="nowrap">${esc(entry.warehouse)}</td>
					<td class="num ${entry.qty < 0 ? "warn-red" : "good"}">${qty(entry.qty)}</td>
					<td class="num">${qty(entry.balance)}</td>
					<td><span class="pill ${tone(entry.status)}">${esc(entry.status)}</span></td>
				</tr>`).join("")}</tbody>
			</table>`
			: '<div class="cust-none">This part has not moved in this branch yet.</div>';
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

	async function jobPicker(selected) {
		const jobs = await A3.call("a3_retail.api.parts_desk.open_jobs", {});
		return `<label class="field"><span>Repair</span>
			<select id="w-job">${jobs.map((job) =>
				`<option value="${esc(job.name)}"${job.name === selected ? " selected" : ""}>${
					esc(job.name)} · ${esc(job.customer_name)} · ${esc(job.device_model || "")}
					</option>`).join("")}</select></label>`;
	}

	async function openAssign(row) {
		const picker = await jobPicker();
		openWork("Assign to a repair",
			row ? `${row.item_name} · ${qty(row.store_qty)} in the store, ${qty(row.bench_qty)} on the bench`
			    : "Put a part on a repair.",
			`${picker}
			<div class="field-grid three">
				<label class="field"><span>Part</span>
					<input id="w-item" value="${esc(row ? row.item_code : "")}"></label>
				<label class="field"><span>Quantity</span>
					<input id="w-qty" type="number" min="1" step="1" value="1"></label>
				<label class="field"><span>Charge</span>
					<select id="w-cover">
						<option value="0">Chargeable to the customer</option>
						<option value="1">Covered by warranty</option>
					</select></label>
			</div>
			<p class="modal-note">On the shelf, it moves to the bench straight away. Not on the
				shelf, and the repair goes to Awaiting Parts while it is chased.</p>`,
			"Assign it",
			async () => {
				const result = await A3.call("a3_retail.api.parts_desk.assign_to_service", {
					job_card: $("w-job").value,
					item_code: $("w-item").value.trim(),
					qty: Number($("w-qty").value) || 1,
					warranty: $("w-cover").value,
				});
				const said = result.status === "Issued"
					? `Issued to ${result.job_card} — ${result.stock_entry}.`
					: result.status === "On the bench"
					? `On ${result.job_card}. ${result.message || "It is already on the bench."}`
					: `Added to ${result.job_card}. ${result.message || "Being chased."}`;
				toast(said, "ok");
				loadAll();
			});
	}

	async function openReplace(row) {
		const picker = await jobPicker();
		openWork("Replace a failed part",
			"A new one goes on the repair at no charge, and the failed one is written down "
			+ "for the supplier to answer for.",
			`${picker}
			<div class="field-grid">
				<label class="field"><span>Replacement part</span>
					<input id="w-item" value="${esc(row ? row.item_code : "")}"></label>
				<label class="field"><span>Quantity</span>
					<input id="w-qty" type="number" min="1" step="1" value="1"></label>
			</div>
			<label class="field"><span>What was wrong with the old one</span>
				<input id="w-defect" placeholder="Backlight failed after two weeks"></label>`,
			"Replace it",
			async () => {
				const result = await A3.call("a3_retail.api.parts_desk.replace_part", {
					job_card: $("w-job").value,
					item_code: $("w-item").value.trim(),
					qty: Number($("w-qty").value) || 1,
					defect: $("w-defect").value.trim(),
				});
				toast(result.oem_return
					? `Replaced — the old one is on ${result.oem_return} for the supplier.`
					: "Replaced on the repair.", "ok");
				loadAll();
			});
	}

	// --------------------------------------------------------------- start
	let searchTimer;
	async function start(options) {
		state.branch = options.branch;
		state.kind = options.kind === "accessories" ? "accessories" : "parts";
		state.boot = await A3.call("a3_retail.api.parts_desk.bootstrap", { kind: state.kind });

		$("kinds").querySelectorAll("[data-kind]").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.kind === state.kind);
			node.addEventListener("click", () => {
				state.kind = node.dataset.kind;
				$("kinds").querySelectorAll("[data-kind]").forEach((other) =>
					other.classList.toggle("is-active", other === node));
				history.replaceState({}, "", state.kind === "accessories"
					? "/branch/parts?kind=accessories" : "/branch/parts");
				loadAll();
			});
		});

		$("brand").innerHTML += state.boot.brands.map((brand) =>
			`<option value="${esc(brand)}">${esc(brand)}</option>`).join("");

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				loadShelf();
			}, 220);
		});
		[["brand", "brand"], ["status", "status"]].forEach(([id, key]) => {
			$(id).addEventListener("change", () => {
				state.filters[key] = $(id).value;
				loadShelf();
			});
		});
		$("clear").addEventListener("click", () => {
			state.filters = {};
			$("q").value = "";
			$("brand").value = "";
			$("status").value = "all";
			loadShelf();
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
				if (node.dataset.do === "assign") return openAssign(null);
				if (node.dataset.do === "replace") return openReplace(null);
				if (node.dataset.do === "request") window.location = "/branch/stock";
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
