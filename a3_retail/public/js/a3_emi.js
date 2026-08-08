// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * EMI Management — the branch's financing desk.
 *
 * One page for everything a counter does with finance: the partners, the
 * schemes they publish, the applications customers make, the paperwork those
 * need, the sales that went out on finance, and the money the financiers still
 * owe. Every operation happens in a popup, so nobody leaves the list they were
 * reading.
 *
 * Nothing here decides a loan. The instalments this page shows are the shop's
 * own arithmetic off its own scheme configuration, labelled indicative; what
 * the financier answers is what gets recorded against the application.
 */

window.EMI = (function () {
	const state = {
		branch: "", company: "", boot: null, tab: "overview", page: 1, pageSize: 20,
		rows: [], filters: {}, wizard: null, view: null,
	};
	const $ = (id) => document.getElementById(id);

	const BLANK = {
		query: "", from_date: "", to_date: "", partner: "", scheme: "", status: "all",
		branch: "current", sales_person: "", item_group: "", document_status: "all",
		settlement_status: "all", scheme_status: "all",
	};

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);
	const money2 = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);
	const lakh = (value) => {
		const number = Number(value) || 0;
		if (number >= 10000000) return "₹" + (number / 10000000).toFixed(2) + "Cr";
		if (number >= 100000) return "₹" + (number / 100000).toFixed(1) + "L";
		return money(number);
	};

	function esc(value) {
		const node = document.createElement("div");
		node.textContent = value == null ? "" : String(value);
		return node.innerHTML;
	}

	function day(value) {
		if (!value) return "—";
		const date = new Date(String(value).slice(0, 10) + "T00:00:00");
		return isNaN(date) ? String(value)
			: date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
	}

	function stamp(value) {
		if (!value) return "";
		const date = new Date(String(value).replace(" ", "T"));
		return isNaN(date) ? String(value)
			: date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit",
			                                 minute: "2-digit" });
	}

	function toast(text, kind, title) {
		return A3.toast(text, kind, title);
	}

	function fail(error, where) {
		toast(error.message || "That did not work.", "error", error.title || where || "");
	}

	function icon(name) {
		const paths = {
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
			clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
			check: '<path d="M20 6 9 17l-5-5"/>',
			ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
			bank: '<path d="M3 10h18L12 4z"/><path d="M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/>',
			chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
			percent: '<path d="M19 5 5 19"/><circle cx="7.5" cy="7.5" r="2.5"/><circle cx="16.5" cy="16.5" r="2.5"/>',
			eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
			pencil: '<path d="M4 20h4L20 8l-4-4L4 16z"/><path d="M14 6l4 4"/>',
			upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 17v3h16v-3"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	function pill(text, tone) {
		return `<span class="pill ${tone || "pill-sky"}">${esc(text)}</span>`;
	}

	// ==================================================================== load
	async function load() {
		await Promise.all([loadHead(), loadTab()]);
	}

	async function loadHead() {
		try {
			const [cards, partners] = await Promise.all([
				A3.call("a3_retail.api.emi.kpis", { filters: state.filters }),
				A3.call("a3_retail.api.emi.financiers_summary", { filters: state.filters }),
			]);
			paintKpis(cards);
			paintPartners(partners);
		} catch (error) {
			fail(error, "The figures would not load");
		}
	}

	const KPI_CARDS = [
		["sales_today", "EMI Sales Today", "sky", "cash"],
		["active", "Active Applications", "sky", "file"],
		["pending", "Pending Approval", "warn", "clock"],
		["approved_today", "Approved Today", "good", "check"],
		["rejected", "Rejected", "bad", "ban"],
		["pending_settlement", "Pending Settlement", "bad", "bank"],
		["month_sales", "This Month EMI Sales", "good", "chart"],
		["commission", "Financier Cost", "warn", "percent"],
	];

	function paintKpis(cards) {
		$("kpis").innerHTML = KPI_CARDS.map(([key, label, tone, glyph]) => {
			const box = cards[key];
			if (!box) return "";
			const value = box.money ? lakh(box.value) : Number(box.value).toLocaleString("en-IN");
			const sub = box.money && box.count != null
				? `${box.count} ${box.count === 1 ? "application" : "applications"}`
				: (box.count != null ? "" : "");
			return `<div class="ctile emi-kpi is-clickable" data-kpi="${key}">
				<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
					<span class="ctile-label">${label}</span></div>
				<div class="ctile-value">${value}</div>
				<div class="ctile-sub">${sub}</div>
			</div>`;
		}).join("");

		$("kpis").querySelectorAll("[data-kpi]").forEach((node) => {
			node.addEventListener("click", () => {
				const go = cards[node.dataset.kpi] && cards[node.dataset.kpi].go;
				if (!go) return;
				if (go.status) {
					state.filters.status = go.status;
					$("status").value = optionExists("status", go.status) ? go.status : "all";
				}
				setTab(go.tab || "applications");
			});
		});
	}

	function optionExists(id, value) {
		return [...$(id).options].some((option) => option.value === value);
	}

	function paintPartners(rows) {
		if (!rows.length) {
			$("partner-strip").innerHTML =
				'<div class="cust-none">No applications with any financier in this period.</div>';
			$("partner-note").textContent = "";
			return;
		}

		const top = rows.reduce((sum, row) => sum + Number(row.financed || 0), 0);
		$("partner-note").textContent = `${lakh(top)} financed across ${rows.length} `
			+ (rows.length === 1 ? "partner" : "partners");

		$("partner-strip").innerHTML = rows.map((row) => `
			<button class="emi-partner" data-partner="${esc(row.finance_partner)}">
				<span class="emi-partner-name">${esc(row.finance_partner)}</span>
				<span class="emi-partner-value">${lakh(row.financed)}</span>
				<span class="emi-partner-sub">${row.applications} ${
					row.applications === 1 ? "application" : "applications"}${
					row.pending ? ` · ${row.pending} waiting` : ""}</span>
			</button>`).join("");

		$("partner-strip").querySelectorAll("[data-partner]").forEach((node) => {
			node.addEventListener("click", () => {
				state.filters.partner = node.dataset.partner;
				$("partner").value = node.dataset.partner;
				setTab(state.tab === "overview" ? "applications" : state.tab);
			});
		});
	}

	// The filter bar means different things on different tabs.
	const FILTERS_FOR = {
		overview: ["from-date", "to-date", "partner", "branch"],
		applications: ["q", "from-date", "to-date", "partner", "scheme", "status", "branch",
		               "sales-person", "item-group"],
		schemes: ["partner"],
		financiers: [],
		sales: ["q", "from-date", "to-date", "partner", "branch"],
		settlements: ["partner"],
		documents: ["q", "partner", "branch"],
		reconciliation: ["q", "from-date", "to-date", "partner", "branch"],
	};

	function setTab(name) {
		state.tab = name;
		state.page = 1;
		document.querySelectorAll("#tabs .tab").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.tab === name);
		});

		const wanted = FILTERS_FOR[name] || [];
		$("filter-panel").hidden = !wanted.length;
		$("filter-row").querySelectorAll(".field").forEach((field) => {
			const control = field.querySelector("input, select");
			field.hidden = !control || !wanted.includes(control.id);
		});

		const url = new URL(window.location);
		url.searchParams.set("tab", name);
		window.history.replaceState({}, "", url);
		loadTab();
	}

	async function loadTab() {
		$("tab-body").innerHTML = '<div class="pos-loading">Loading…</div>';
		try {
			const data = await A3.call("a3_retail.api.emi.tab", {
				name: state.tab, filters: state.filters,
				page: state.page, page_size: state.pageSize,
			});
			state.rows = data.rows || [];
			PAINT[state.tab](data);
		} catch (error) {
			$("tab-body").innerHTML = `<section class="svc-panel rep-empty">
				<b>${esc(error.title || "This tab would not load")}</b>
				<span>${esc(error.message)}</span></section>`;
		}
	}

	// ================================================================= tables
	function table(columns, rows, empty, rowAttrs) {
		if (!rows.length) {
			return `<section class="svc-panel rep-empty"><b>${esc(empty)}</b>
				<span>Try a different search, or change the filters above.</span></section>`;
		}
		return `<section class="svc-panel bill-table-panel">
			<div class="bill-table-wrap"><table class="bill-table emi-table">
				<thead><tr>${columns.map((column) =>
					`<th class="${column.num ? "num" : ""}">${esc(column.label)}</th>`).join("")}</tr></thead>
				<tbody>${rows.map((row, index) => `<tr ${rowAttrs ? rowAttrs(row, index) : ""}>${
					columns.map((column) =>
						`<td class="${column.num ? "num" : ""}">${column.cell(row, index)}</td>`).join("")
				}</tr>`).join("")}</tbody>
			</table></div>
		</section>`;
	}

	function pager(data) {
		if (!data || data.pages <= 1) {
			return data && data.total
				? `<div class="bill-foot"><span>Showing all ${data.total} rows</span></div>` : "";
		}
		const numbers = [];
		for (let n = 1; n <= data.pages; n += 1) {
			if (n <= 2 || n === data.pages || Math.abs(n - data.page) <= 1) numbers.push(n);
			else if (numbers[numbers.length - 1] !== "…") numbers.push("…");
		}
		return `<div class="bill-foot">
			<span>Showing ${data.showing[0]}–${data.showing[1]} of ${
				data.total.toLocaleString("en-IN")}</span>
			<div class="pager">
				<button class="page-btn" data-go="${data.page - 1}" ${
					data.page <= 1 ? "disabled" : ""}>Previous</button>
				${numbers.map((n) => n === "…" ? '<span class="page-gap">…</span>'
					: `<button class="page-btn ${n === data.page ? "is-active" : ""}" data-go="${n}">${n}</button>`).join("")}
				<button class="page-btn" data-go="${data.page + 1}" ${
					data.page >= data.pages ? "disabled" : ""}>Next</button>
			</div></div>`;
	}

	function wirePager() {
		$("tab-body").querySelectorAll("[data-go]").forEach((node) => {
			node.addEventListener("click", () => {
				state.page = Number(node.dataset.go);
				loadTab();
			});
		});
	}

	function wireOpeners() {
		$("tab-body").querySelectorAll("[data-open]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.preventDefault();
				openApplication(node.dataset.open);
			});
		});
	}

	// ================================================================ tab 1
	const PAINT = {};

	PAINT.overview = function (data) {
		const list = (title, rows, render, empty, action) => `
			<section class="svc-panel emi-card">
				<div class="panel-head"><h2>${title}</h2>
					${action ? `<button class="linkish" data-go-tab="${action}">See all</button>` : ""}</div>
				${rows.length ? `<div class="row-list">${rows.map(render).join("")}</div>`
					: `<div class="cust-none">${empty}</div>`}
			</section>`;

		const applicationRow = (row) => `
			<div class="row-line">
				<span class="row-main"><b><a href="#" data-open="${esc(row.name)}">${esc(row.name)}</a></b>
					<small>${esc(row.customer_name || "")} · ${esc(row.finance_partner || "")}</small></span>
				<span class="row-date">${esc(day(row.application_date))}</span>
				<span class="row-amount">${money(row.loan_amount)}</span>
				${pill(row.status, row.tone)}
			</div>`;

		$("tab-body").innerHTML = `<div class="emi-overview">
			${list("Waiting on the financier", data.pending, (row) => `
				<div class="row-line">
					<span class="row-main"><b><a href="#" data-open="${esc(row.name)}">${esc(row.name)}</a></b>
						<small>${esc(row.customer_name || "")} · ${esc(row.finance_partner || "")}</small></span>
					<span class="row-date">${row.waiting_days ? row.waiting_days + " days" : "today"}</span>
					<span class="row-amount">${money(row.loan_amount)}</span>
					${pill(row.status, row.tone)}
				</div>`, "Nothing is sitting with a financier.", "applications")}

			${list("Recent approvals", data.approvals, applicationRow,
				"No approvals yet in this period.", "applications")}

			${list("Recent EMI sales", data.sales, applicationRow,
				"No sale has gone out on finance yet.", "sales")}

			${list("Money the financiers owe", data.owed, (row) => `
				<div class="row-line">
					<span class="row-main"><b>${esc(row.finance_partner)}</b>
						<small>oldest ${esc(day(row.oldest))}</small></span>
					<span class="row-date">${row.applications} sales</span>
					<span class="row-amount warn-red">${money(row.amount)}</span>
					<button class="linkish" data-settle="${esc(row.finance_partner)}">Settle</button>
				</div>`, "Every financier has settled.", "settlements")}

			${list("Settlements in progress", data.settlements, (row) => `
				<div class="row-line">
					<span class="row-main"><b><a href="#" data-settlement="${esc(row.name)}">${
						esc(row.name)}</a></b>
						<small>${esc(row.finance_partner)} · ${esc(day(row.from_date))} – ${
							esc(day(row.to_date))}</small></span>
					<span class="row-amount">${money(row.net_expected)}</span>
					${pill(row.status, row.tone)}
				</div>`, "No settlement is open.", "settlements")}

			${list("Schemes about to lapse", data.expiring, (row) => `
				<div class="row-line">
					<span class="row-main"><b>${esc(row.scheme_name)}</b>
						<small>${esc(row.finance_partner)} · ${row.tenure_months}M</small></span>
					<span class="row-date warn-red">until ${esc(day(row.valid_upto))}</span>
				</div>`, "No scheme lapses in the next month.", "schemes")}

			${list("Rejected", data.rejected, (row) => `
				<div class="row-line">
					<span class="row-main"><b><a href="#" data-open="${esc(row.name)}">${esc(row.name)}</a></b>
						<small>${esc(row.customer_name || "")} · ${
							esc(row.rejection_reason || "no reason recorded")}</small></span>
					<span class="row-amount">${money(row.loan_amount)}</span>
				</div>`, "Nothing was turned down.", "applications")}
		</div>`;

		wireOpeners();
		$("tab-body").querySelectorAll("[data-settle]").forEach((node) => {
			node.addEventListener("click", () => askSettlement(node.dataset.settle));
		});
		$("tab-body").querySelectorAll("[data-settlement]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.preventDefault();
				openSettlement(node.dataset.settlement);
			});
		});
	};

	// ================================================================ tab 2
	PAINT.applications = function (data) {
		const columns = [
			{ label: "Application", cell: (row) =>
				`<a class="bill-no" href="#" data-open="${esc(row.name)}">${esc(row.name)}</a>` },
			{ label: "Date", cell: (row) => esc(day(row.application_date)) },
			{ label: "Customer", cell: (row) =>
				`${esc(row.customer_name || row.customer)}<small>${esc(row.customer_mobile || "")}</small>` },
			{ label: "Product", cell: (row) => esc((row.products || "—").slice(0, 42)) },
			{ label: "Invoice", cell: (row) => row.sales_invoice
				? `<a href="/branch/invoice?name=${encodeURIComponent(row.sales_invoice)}">${
					esc(row.sales_invoice)}</a>` : "—" },
			{ label: "Financier", cell: (row) => esc(row.finance_partner || "—") },
			{ label: "Scheme", cell: (row) => esc(row.emi_scheme || "—") },
			{ label: "Loan", num: true, cell: (row) => money(row.loan_amount) },
			{ label: "Down pmt", num: true, cell: (row) => money(row.down_payment) },
			{ label: "EMI", num: true, cell: (row) => `<b>${money(row.emi_amount)}</b>` },
			{ label: "Tenure", num: true, cell: (row) => `${row.tenure_months || 0}M` },
			{ label: "Status", cell: (row) => pill(row.status, row.tone)
				+ (row.documents_ok ? "" : '<small class="warn-red">documents pending</small>') },
			{ label: "Branch", cell: (row) => esc(row.branch || "") },
			{ label: "Sales person", cell: (row) => esc(row.sales_person || "—") },
			{ label: "", cell: (row) => `
				<span class="bill-actions">
					<button class="icon-btn plain" data-open="${esc(row.name)}" title="Open">${icon("eye")}</button>
					<button class="icon-btn plain" data-print="${esc(row.name)}" title="Print">${icon("print")}</button>
					<button class="icon-btn plain" data-more="${esc(row.name)}" title="More">${icon("more")}</button>
				</span>` },
		];

		$("tab-body").innerHTML = table(columns, data.rows, "No applications found") + pager(data);
		wirePager();
		wireOpeners();
		$("tab-body").querySelectorAll("[data-print]").forEach((node) => {
			node.addEventListener("click", () => printApplication(node.dataset.print));
		});
		$("tab-body").querySelectorAll("[data-more]").forEach((node) => {
			node.addEventListener("click", () => moreFor(node.dataset.more));
		});
	};

	// ================================================================ tab 3
	PAINT.schemes = function (data) {
		const columns = [
			{ label: "Scheme", cell: (row) =>
				`<b>${esc(row.scheme_name)}</b><small>${esc(row.scheme_code || "")}</small>` },
			{ label: "Financier", cell: (row) => esc(row.finance_partner) },
			{ label: "Category", cell: (row) => esc((row.item_groups || []).join(", ") || "Any") },
			{ label: "Brands", cell: (row) => esc((row.brands || []).join(", ") || "Any") },
			{ label: "Tenure", num: true, cell: (row) => `${row.tenure_months}M` },
			{ label: "Interest", num: true, cell: (row) => row.is_no_cost_emi
				? '<span class="good">No cost</span>'
				: `${row.interest_rate}%<small>${esc(row.interest_type || "Flat")}</small>` },
			{ label: "Down pmt", num: true, cell: (row) => row.down_payment_percent
				? `${row.down_payment_percent}%` : money(row.min_down_payment) },
			{ label: "Fees", num: true, cell: (row) =>
				`${row.processing_fee_type === "Percentage"
					? row.processing_fee + "%" : money(row.processing_fee)}${
					row.documentation_fee ? " + " + money(row.documentation_fee) : ""}` },
			{ label: "Merchant subv.", num: true, cell: (row) => `${row.subvention_percent || 0}%` },
			{ label: "Customer subv.", num: true, cell: (row) =>
				`${row.customer_subvention_percent || 0}%` },
			{ label: "Valid", cell: (row) =>
				`${esc(day(row.valid_from))}<small>to ${esc(day(row.valid_upto))}</small>` },
			{ label: "Branches", cell: (row) => esc((row.branches || []).length
				? row.branches.join(", ") : "All") },
			{ label: "Used", num: true, cell: (row) => row.applications },
			{ label: "Status", cell: (row) => pill(row.state, row.tone) },
			{ label: "", cell: (row) => `
				<span class="bill-actions">
					<button class="icon-btn plain" data-scheme="${esc(row.name)}" title="View">${icon("eye")}</button>
					${state.boot.can.scheme ? `
					<button class="icon-btn plain" data-edit-scheme="${esc(row.name)}" title="Edit">${
						icon("pencil")}</button>
					<button class="icon-btn plain" data-toggle-scheme="${esc(row.name)}"
					        title="${row.is_active ? "Deactivate" : "Activate"}">${icon("ban")}</button>` : ""}
				</span>` },
		];

		$("tab-body").innerHTML = table(columns, data.rows, "No schemes configured yet");
		$("tab-body").querySelectorAll("[data-scheme]").forEach((node) => {
			node.addEventListener("click", () => showScheme(node.dataset.scheme));
		});
		$("tab-body").querySelectorAll("[data-edit-scheme]").forEach((node) => {
			node.addEventListener("click", () => schemeForm(node.dataset.editScheme));
		});
		$("tab-body").querySelectorAll("[data-toggle-scheme]").forEach((node) => {
			node.addEventListener("click", () => toggleScheme(node.dataset.toggleScheme));
		});
	};

	// ================================================================ tab 4
	PAINT.financiers = function (data) {
		const columns = [
			{ label: "Financier", cell: (row) =>
				`<b>${esc(row.partner_name || row.name)}</b><small>${esc(row.legal_name || "")}</small>` },
			{ label: "Type", cell: (row) => esc(row.partner_type || "—") },
			{ label: "Contact", cell: (row) =>
				`${esc(row.support_contact || "—")}<small>${esc(row.support_email || "")}</small>` },
			{ label: "Branch codes", cell: (row) => (row.branch_codes || []).length
				? `${row.branch_codes.length} branches<small>${esc(
					row.branch_codes.slice(0, 2).map((code) => code.branch).join(", "))}</small>`
				: esc(row.merchant_id || "—") },
			{ label: "Submission", cell: (row) => pill(row.integration,
				row.integration === "REST API" ? "pill-purple" : "pill-sky") },
			{ label: "Schemes", num: true, cell: (row) => row.schemes },
			{ label: "Applications", num: true, cell: (row) => row.applications },
			{ label: "Approved", num: true, cell: (row) => row.approved },
			{ label: "Pending settlement", num: true, cell: (row) =>
				`<span class="${row.pending_settlement ? "warn-red" : ""}">${
					money(row.pending_settlement)}</span>` },
			{ label: "Settles in", num: true, cell: (row) =>
				row.settlement_tat_days ? `T+${row.settlement_tat_days}` : "—" },
			{ label: "Status", cell: (row) => pill(row.is_active ? "Active" : "Inactive", row.tone) },
			{ label: "", cell: (row) => `
				<span class="bill-actions">
					<button class="icon-btn plain" data-partner-view="${esc(row.name)}"
					        title="View">${icon("eye")}</button>
					${state.boot.can.partner ? `<button class="icon-btn plain"
						data-edit-partner="${esc(row.name)}" title="Edit">${icon("pencil")}</button>` : ""}
					${state.boot.can.settle ? `<button class="icon-btn plain"
						data-settle="${esc(row.name)}" title="Settle">${icon("bank")}</button>` : ""}
				</span>` },
		];

		$("tab-body").innerHTML = table(columns, data.rows, "No financing partners configured");
		$("tab-body").querySelectorAll("[data-partner-view]").forEach((node) => {
			node.addEventListener("click", () => showPartner(node.dataset.partnerView));
		});
		$("tab-body").querySelectorAll("[data-edit-partner]").forEach((node) => {
			node.addEventListener("click", () => partnerForm(node.dataset.editPartner));
		});
		$("tab-body").querySelectorAll("[data-settle]").forEach((node) => {
			node.addEventListener("click", () => askSettlement(node.dataset.settle));
		});
	};

	// ================================================================ tab 5
	PAINT.sales = function (data) {
		const columns = [
			{ label: "Invoice", cell: (row) => row.sales_invoice
				? `<a class="bill-no" href="/branch/invoice?name=${
					encodeURIComponent(row.sales_invoice)}">${esc(row.sales_invoice)}</a>`
				: '<span class="faint">not linked</span>' },
			{ label: "Date", cell: (row) => esc(day(row.disbursement_date || row.posting_date)) },
			{ label: "Application", cell: (row) =>
				`<a href="#" data-open="${esc(row.name)}">${esc(row.name)}</a>` },
			{ label: "Customer", cell: (row) => esc(row.customer_name || row.customer) },
			{ label: "Product", cell: (row) => esc((row.products || "—").slice(0, 36)) },
			{ label: "IMEI", cell: (row) => esc(row.imei || "—") },
			{ label: "Financier", cell: (row) => esc(row.finance_partner) },
			{ label: "Scheme", cell: (row) => esc(row.emi_scheme || "—") },
			{ label: "Gross sale", num: true, cell: (row) => money(row.invoice_total) },
			{ label: "Down pmt", num: true, cell: (row) => money(row.down_payment) },
			{ label: "Financed", num: true, cell: (row) => `<b>${money(row.loan_amount)}</b>` },
			{ label: "Customer paid", num: true, cell: (row) => money(row.customer_paid) },
			{ label: "Settlement due", num: true, cell: (row) => money(row.expected) },
			{ label: "Received", num: true, cell: (row) =>
				`<span class="${row.received ? "good" : ""}">${money(row.received)}</span>` },
			{ label: "Status", cell: (row) => pill(row.settlement_state, row.tone) },
		];

		$("tab-body").innerHTML = table(columns, data.rows, "No sale has gone out on finance")
			+ pager(data);
		wirePager();
		wireOpeners();
	};

	// ================================================================ tab 6
	PAINT.settlements = function (data) {
		const cards = data.cards;
		const strip = `<section class="ctiles emi-settle-cards">
			${[["Expected settlement", cards.expected, "sky", "bank"],
			   ["Received", cards.received, "good", "check"],
			   ["Still pending", cards.pending, "warn", "clock"],
			   ["Under query", cards.disputed, "bad", "ban"]].map(([label, value, tone, glyph]) => `
				<div class="ctile emi-kpi">
					<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
						<span class="ctile-label">${label}</span></div>
					<div class="ctile-value">${lakh(value)}</div></div>`).join("")}
		</section>`;

		const columns = [
			{ label: "Settlement", cell: (row) =>
				`<a class="bill-no" href="#" data-settlement="${esc(row.name)}">${esc(row.name)}</a>` },
			{ label: "Financier", cell: (row) => esc(row.finance_partner) },
			{ label: "Period", cell: (row) =>
				`${esc(day(row.from_date))}<small>to ${esc(day(row.to_date))}</small>` },
			{ label: "Sales", num: true, cell: (row) => row.applications },
			{ label: "Gross", num: true, cell: (row) => money(row.gross_amount) },
			{ label: "MDR + subvention", num: true, cell: (row) =>
				money(Number(row.mdr_amount || 0) + Number(row.subvention_amount || 0)) },
			{ label: "Expected", num: true, cell: (row) => `<b>${money(row.net_expected)}</b>` },
			{ label: "Received", num: true, cell: (row) => money(row.net_received) },
			{ label: "Difference", num: true, cell: (row) =>
				`<span class="${Math.abs(row.variance) > 1 ? "warn-red" : "good"}">${
					money(row.variance)}</span>` },
			{ label: "Bank reference", cell: (row) => esc(row.utr_reference || "—") },
			{ label: "Status", cell: (row) => pill(row.status, row.tone) },
			{ label: "", cell: (row) => `
				<span class="bill-actions">
					<button class="icon-btn plain" data-settlement="${esc(row.name)}"
					        title="Open">${icon("eye")}</button>
				</span>` },
		];

		$("tab-body").innerHTML = strip
			+ (state.boot.can.settle
				? `<div class="emi-tab-actions"><button class="btn btn-orange" id="new-settlement">
					${icon("bank")} Record a settlement</button></div>` : "")
			+ table(columns, data.rows, "No settlement has been opened yet");

		if ($("new-settlement")) $("new-settlement").addEventListener("click", () => askSettlement());
		$("tab-body").querySelectorAll("[data-settlement]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.preventDefault();
				openSettlement(node.dataset.settlement);
			});
		});
	};

	// ================================================================ tab 7
	PAINT.documents = function (data) {
		const filters = `<section class="svc-panel emi-inline-filters">
			<label class="field"><span>Verification</span>
				<select id="doc-state">
					${[["all", "Everything"], ["missing", "Still missing"],
					   ["uploaded", "Uploaded, not verified"], ["verified", "Verified"]]
						.map(([value, label]) => `<option value="${value}" ${
							state.filters.document_status === value ? "selected" : ""}>${label}</option>`).join("")}
				</select></label>
			<label class="field"><span>Document</span>
				<select id="doc-type"><option value="">Any</option>
					${state.boot.document_types.map((type) => `<option value="${esc(type.name)}" ${
						state.filters.document_type === type.name ? "selected" : ""}>${
						esc(type.document_name)}</option>`).join("")}
				</select></label>
		</section>`;

		const columns = [
			{ label: "Application", cell: (row) =>
				`<a href="#" data-open="${esc(row.application)}">${esc(row.application)}</a>` },
			{ label: "Customer", cell: (row) => esc(row.customer_name || "") },
			{ label: "Financier", cell: (row) => esc(row.finance_partner || "") },
			{ label: "Document", cell: (row) =>
				`<b>${esc(row.document_type)}</b><small>${esc(row.category || "")}</small>` },
			{ label: "Required", cell: (row) => row.is_mandatory ? "Mandatory" : "Optional" },
			{ label: "Reference", cell: (row) => esc(row.document_number || "—") },
			{ label: "Expires", cell: (row) => esc(row.expiry_date ? day(row.expiry_date) : "—") },
			{ label: "Verified by", cell: (row) => esc(row.verified_by || "—") },
			{ label: "Status", cell: (row) => pill(row.state, row.tone) },
			{ label: "", cell: (row) => `
				<span class="bill-actions">
					<button class="icon-btn plain" data-open="${esc(row.application)}"
					        title="Open the application">${icon("eye")}</button>
				</span>` },
		];

		$("tab-body").innerHTML = filters
			+ table(columns, data.rows, "No documents on file") + pager(data);
		wirePager();
		wireOpeners();
		$("doc-state").addEventListener("change", () => {
			state.filters.document_status = $("doc-state").value;
			state.page = 1;
			loadTab();
		});
		$("doc-type").addEventListener("change", () => {
			state.filters.document_type = $("doc-type").value;
			state.page = 1;
			loadTab();
		});
	};

	// ================================================================ tab 8
	PAINT.reconciliation = function (data) {
		const columns = [
			{ label: "Invoice", cell: (row) => row.sales_invoice
				? `<a href="/branch/invoice?name=${encodeURIComponent(row.sales_invoice)}">${
					esc(row.sales_invoice)}</a>` : '<span class="faint">not linked</span>' },
			{ label: "Application", cell: (row) =>
				`<a href="#" data-open="${esc(row.name)}">${esc(row.name)}</a>` },
			{ label: "Customer", cell: (row) => esc(row.customer_name || "") },
			{ label: "Financier", cell: (row) => esc(row.finance_partner) },
			{ label: "Sale value", num: true, cell: (row) => money(row.grand_total) },
			{ label: "Financed", num: true, cell: (row) => money(row.loan_amount) },
			{ label: "Expected settlement", num: true, cell: (row) => money(row.expected) },
			{ label: "Actual settlement", num: true, cell: (row) => money(row.actual) },
			{ label: "Difference", num: true, cell: (row) => row.difference == null
				? '<span class="faint">—</span>'
				: `<b class="${row.state === "Matched" ? "good" : "warn-red"}">${
					money(row.difference)}</b>` },
			{ label: "Settlement", cell: (row) => row.settlement
				? `<a href="#" data-settlement="${esc(row.settlement)}">${esc(row.settlement)}</a>`
				: "—" },
			{ label: "Status", cell: (row) => pill(row.state, row.tone) },
		];

		$("tab-body").innerHTML = table(columns, data.rows, "Nothing to reconcile yet")
			+ pager(data);
		wirePager();
		wireOpeners();
		$("tab-body").querySelectorAll("[data-settlement]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.preventDefault();
				openSettlement(node.dataset.settlement);
			});
		});
	};

	// ============================================================ one modal
	function openWork(title, note, body, goLabel, onGo) {
		$("work-title").textContent = title;
		$("work-note").textContent = note || "";
		$("work-body").innerHTML = body;
		$("work-msg").textContent = "";
		$("work-msg").className = "msg";
		$("work-go").hidden = !goLabel;
		$("work-go").textContent = goLabel || "";
		$("work-go").onclick = onGo || null;
		$("work-modal").hidden = false;
	}

	function workMessage(text, kind) {
		$("work-msg").textContent = A3.plain(text);
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	function field(label, id, attrs, value) {
		return `<label class="field"><span>${label}</span>
			<input id="${id}" ${attrs || ""} value="${value == null ? "" : esc(value)}"></label>`;
	}

	function select(label, id, options, chosen, attrs) {
		return `<label class="field"><span>${label}</span>
			<select id="${id}" ${attrs || ""}>${options.map((option) => {
				const [value, text] = Array.isArray(option) ? option : [option, option];
				return `<option value="${esc(value)}" ${value === chosen ? "selected" : ""}>${
					esc(text)}</option>`;
			}).join("")}</select></label>`;
	}

	// ====================================================== the application
	async function openApplication(name) {
		try {
			const data = await A3.call("a3_retail.api.emi.application", { name });
			state.view = data;
			paintApplication(data);
			$("view-modal").hidden = false;
		} catch (error) {
			fail(error, "That application would not open");
		}
	}

	function paintApplication(data) {
		const loan = data.loan;
		$("view-title").textContent = data.name;
		$("view-badges").innerHTML = pill(data.status, data.tone)
			+ pill(data.progress.kyc === "Complete" ? "KYC complete" : "KYC pending",
				data.progress.kyc === "Complete" ? "pill-good" : "pill-warn")
			+ (data.finance.submission_mode === "REST API"
				? pill("API partner", "pill-purple") : pill("Manual submission", "pill-sky"));

		const block = (title, rows) => `<div class="emi-block"><h4>${title}</h4>
			${rows.filter(Boolean).map(([label, value]) =>
				`<div class="sum-row"><span>${label}</span><b>${value}</b></div>`).join("")}</div>`;

		$("view-body").innerHTML = `
			<div class="emi-view-grid">
				${block("Customer", [
					["Name", esc(data.customer.customer_name || data.customer.name)],
					["Mobile", esc(data.customer.mobile_no || "—")],
					data.customer.email && ["Email", esc(data.customer.email)],
					["PAN", esc(data.customer.pan || "not recorded")],
					data.customer.aadhaar && ["Aadhaar", esc(data.customer.aadhaar)],
					["Employment", esc(data.customer.employment_type || "—")],
					["KYC", esc(data.progress.kyc)],
				])}
				${block("Purchase", [
					["Invoice", data.purchase.invoice
						? `<a href="/branch/invoice?name=${encodeURIComponent(data.purchase.invoice)}">${
							esc(data.purchase.invoice)}</a>` : "not raised yet"],
					["Products", esc(data.items.map((row) => row.item_name).join(", ") || "—")],
					["IMEI", esc(data.items.map((row) => row.serial_no).filter(Boolean).join(", ") || "—")],
					["Invoice total", money2(data.purchase.invoice_total)],
				])}
				${block("Financier", [
					["Partner", esc(data.finance.partner)],
					["Scheme", esc(data.finance.scheme_name || data.finance.scheme || "—")],
					["Merchant code", esc(data.finance.merchant_id || "—")],
					["Application ref", esc(data.finance.partner_application_no || "not received")],
					["Loan account", esc(data.finance.loan_account_number || "not received")],
					["Submitted as", esc(data.finance.submission_mode)],
				])}
				${block("Loan", [
					["Product total", money2(loan.invoice_total)],
					["Down payment", money2(loan.down_payment)],
					["Financed", `<span class="strong">${money2(loan.loan_amount)}</span>`],
					loan.approved_loan_amount && ["Approved for", money2(loan.approved_loan_amount)],
					["Processing fee", money2(loan.processing_fee)],
					loan.documentation_fee && ["Documentation fee", money2(loan.documentation_fee)],
					["Customer paid today", money2(loan.customer_payable_today)],
					["EMI", `<span class="strong">${money2(loan.emi_amount)} × ${
						loan.tenure_months}M</span>`],
					["First EMI", esc(day(loan.first_emi_date))],
					["Last EMI", esc(day(loan.last_emi_date))],
					["Total repayment", money2(loan.total_repayment) + " <small>indicative</small>"],
				])}
				${data.cost ? block("What it costs the shop", [
					["MDR", money2(data.cost.mdr)],
					["Merchant subvention", money2(data.cost.merchant_subvention)],
					["Net realisable", `<span class="strong">${money2(data.cost.net_realisable)}</span>`],
					["Settled so far", money2(data.cost.amount_received)],
				]) : ""}
				${block("Where it stands", [
					["Application", esc(data.status)],
					["Approval", esc(data.progress.approval)],
					data.progress.approval_date && ["Approved on", esc(day(data.progress.approval_date))],
					data.progress.cibil && ["CIBIL", data.progress.cibil],
					data.progress.rejection_reason && ["Rejected for", esc(data.progress.rejection_reason)],
					["Disbursed", esc(data.progress.disbursement ? day(data.progress.disbursement) : "no")],
					["Settlement", data.progress.settlement
						? `<a href="#" data-settlement="${esc(data.progress.settlement)}">${
							esc(data.progress.settlement)}</a>` : "not settled"],
				])}
			</div>

			<div class="emi-view-lower">
				<div class="svc-panel emi-card">
					<div class="panel-head"><h2>Documents</h2>
						<span class="rep-when">${data.documents.filter((row) => row.verified).length}
							of ${data.documents.length} verified</span></div>
					<div class="bill-table-wrap"><table class="bill-table emi-table">
						<thead><tr><th>Document</th><th>Required</th><th>Uploaded</th><th>Verified</th>
							<th>Status</th><th></th></tr></thead>
						<tbody>${data.documents.map((row) => `
							<tr>
								<td><b>${esc(row.document_type)}</b><small>${esc(row.category || "")}</small></td>
								<td>${row.is_mandatory ? "Mandatory" : "Optional"}</td>
								<td>${row.is_received ? "yes" : "—"}</td>
								<td>${row.verified ? esc(row.verified_by || "yes") : "—"}</td>
								<td>${pill(row.state, row.tone || (row.state === "Verified" ? "pill-good"
									: row.state === "Uploaded" ? "pill-warn"
									: row.state === "Required" ? "pill-bad" : "pill-sky"))}</td>
								<td class="bill-actions">
									${data.can.upload ? `<button class="linkish" data-upload="${esc(row.row)}">${
										row.is_received ? "Replace" : "Upload"}</button>` : ""}
									${row.has_file ? `<a class="linkish" href="${esc(row.file_url)}"
										target="_blank" rel="noopener">Preview</a>` : ""}
									${data.can.verify && row.is_received && !row.verified
										? `<button class="linkish" data-verify="${esc(row.row)}">Verify</button>` : ""}
								</td>
							</tr>`).join("")}</tbody>
					</table></div>
				</div>

				<div class="svc-panel emi-card">
					<div class="panel-head"><h2>Timeline</h2>
						<span class="rep-when">${data.timeline.length} entries</span></div>
					<ol class="inv-timeline emi-timeline">${data.timeline.map((event) => `
						<li class="tl-${esc(event.kind)}"><span class="dot"></span>
							<span class="tl-label">${esc(event.label)}</span>
							<span class="tl-at">${esc(stamp(event.at))}</span>
							${event.by ? `<span class="tl-by">${esc(event.by)}</span>` : ""}
							${event.note ? `<span class="tl-note">${esc(event.note)}</span>` : ""}
						</li>`).join("")}</ol>
				</div>
			</div>`;

		$("view-actions").innerHTML = `
			<button class="btn btn-quiet" data-close>Close</button>
			<span class="emi-wizard-spacer"></span>
			<button class="btn btn-quiet btn-icon" id="view-print">${icon("print")} Print</button>
			<button class="btn btn-quiet" id="view-checklist">Checklist</button>
			${data.can.submit_to_financier
				? '<button class="btn btn-primary" id="view-submit">Submit to financier</button>' : ""}
			${data.can.decide
				? '<button class="btn btn-orange" id="view-decision">Record the decision</button>' : ""}
			${data.can.cancel
				? '<button class="btn btn-quiet" id="view-cancel">Cancel application</button>' : ""}
			${data.can.edit
				? '<button class="btn btn-outline" id="view-edit">Edit</button>' : ""}`;

		wireApplicationActions(data);
	}

	function wireApplicationActions(data) {
		$("view-print").addEventListener("click", () => window.open(data.print_url, "_blank"));
		$("view-checklist").addEventListener("click", () =>
			window.open(data.checklist_url, "_blank"));
		if ($("view-submit")) $("view-submit").addEventListener("click", () => askSubmit(data));
		if ($("view-decision")) $("view-decision").addEventListener("click", () => askDecision(data));
		if ($("view-cancel")) $("view-cancel").addEventListener("click", () => askCancel(data));
		if ($("view-edit")) $("view-edit").addEventListener("click", () => {
			$("view-modal").hidden = true;
			openWizard(data);
		});

		$("view-body").querySelectorAll("[data-upload]").forEach((node) => {
			node.addEventListener("click", () => askUpload(data.name, node.dataset.upload));
		});
		$("view-body").querySelectorAll("[data-verify]").forEach((node) => {
			node.addEventListener("click", () => verifyDocument(data.name, node.dataset.verify));
		});
		$("view-body").querySelectorAll("[data-settlement]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.preventDefault();
				$("view-modal").hidden = true;
				openSettlement(node.dataset.settlement);
			});
		});
	}

	function askSubmit(data) {
		openWork("Submit to " + data.finance.partner,
			"Send it the way this partner takes applications, then record the reference it "
			+ "gives back. The financier decides; this only records what it answered.",
			`<div class="field-grid">
				${field("Financier application reference (if you have it)", "w-ref",
					'placeholder="Portal or API reference"', data.finance.partner_application_no)}
			</div>
			<p class="emi-hint">${data.finance.submission_mode === "REST API"
				? "This partner has an API configured — a system administrator sets the credentials "
				  + "on the partner record; nothing is entered here."
				: "This partner is submitted through its own portal or over the counter."}</p>`,
			"Mark as submitted", async () => {
				try {
					await A3.call("a3_retail.api.emi.submit_application", {
						name: data.name, partner_application_no: $("w-ref").value.trim() || null });
					$("work-modal").hidden = true;
					toast(`${data.name} is with ${data.finance.partner}.`, "ok");
					refreshAfterChange(data.name);
				} catch (error) {
					workMessage(error.message, "error");
				}
			});
	}

	function askDecision(data) {
		openWork("What did " + data.finance.partner + " answer?",
			"Approved or rejected — with the reference the financier gave, so the sale and the "
			+ "settlement can be traced back to it.",
			`<div class="field-grid">
				${select("Decision", "w-decision", [["Approved", "Approved"], ["Rejected", "Rejected"]],
					"Approved")}
				${field("Financier application no.", "w-ref", "", data.finance.partner_application_no)}
			</div>
			<div id="w-approved">
				<div class="field-grid">
					${field("Approved loan amount", "w-amount", 'type="number" step="1"',
						data.loan.loan_amount)}
					${field("Loan account number", "w-account", "", data.finance.loan_account_number)}
					${field("CIBIL score (optional)", "w-cibil", 'type="number" step="1"',
						data.progress.cibil)}
				</div>
			</div>
			<div id="w-rejected" hidden>
				<div class="field-grid">
					${select("Reason", "w-reason", state.boot.rejection_reasons, "")}
				</div>
				${field("Remarks", "w-remarks", 'placeholder="What the financier said"', "")}
			</div>`,
			"Record it", async () => {
				const decision = $("w-decision").value;
				try {
					await A3.call("a3_retail.api.emi.decide", {
						name: data.name,
						decision,
						partner_application_no: $("w-ref").value.trim() || null,
						approved_loan_amount: decision === "Approved"
							? Number($("w-amount").value) || 0 : null,
						loan_account_number: decision === "Approved"
							? $("w-account").value.trim() : null,
						cibil_score: decision === "Approved" ? Number($("w-cibil").value) || 0 : null,
						rejection_reason: decision === "Rejected" ? $("w-reason").value : null,
						remarks: decision === "Rejected" ? $("w-remarks").value.trim() : null,
					});
					$("work-modal").hidden = true;
					toast(`${data.name} is ${decision.toLowerCase()}.`,
						decision === "Approved" ? "ok" : "error");
					refreshAfterChange(data.name);
				} catch (error) {
					workMessage(error.message, "error");
				}
			});

		$("w-decision").addEventListener("change", () => {
			const approved = $("w-decision").value === "Approved";
			$("w-approved").hidden = !approved;
			$("w-rejected").hidden = approved;
		});
	}

	function askCancel(data) {
		openWork("Cancel " + data.name,
			"The application stays on the record, cancelled — nothing is deleted.",
			field("Why is it being cancelled?", "w-reason",
				'placeholder="Customer withdrew, financier declined, sale abandoned…"', ""),
			"Cancel the application", async () => {
				try {
					await A3.call("a3_retail.api.emi.cancel_application", {
						name: data.name, reason: $("w-reason").value.trim() });
					$("work-modal").hidden = true;
					toast(`${data.name} is cancelled.`, "ok");
					refreshAfterChange(data.name);
				} catch (error) {
					workMessage(error.message, "error");
				}
			});
	}

	/** Upload goes through Frappe's own file endpoint, attached to the
	 *  application, so the file inherits its permissions and its audit trail. */
	function askUpload(application, row) {
		openWork("Upload a document", "It is attached to the application itself.",
			`<label class="field"><span>File</span>
				<input id="w-file" type="file" accept="image/*,application/pdf"></label>
			<div class="field-grid">
				${field("Reference number (optional)", "w-number", 'placeholder="Last digits only"', "")}
				${field("Expires on (optional)", "w-expiry", 'type="date"', "")}
			</div>`,
			"Upload", async () => {
				const picker = $("w-file");
				if (!picker.files.length) return workMessage("Pick the file first.", "error");
				workMessage("Uploading…");

				const form = new FormData();
				form.append("file", picker.files[0]);
				form.append("doctype", "EMI Application");
				form.append("docname", application);
				form.append("is_private", 1);

				try {
					const response = await fetch("/api/method/upload_file", {
						method: "POST",
						headers: { "X-Frappe-CSRF-Token": A3.csrfToken() },
						body: form,
					});
					const payload = await response.json();
					if (!response.ok) throw new Error(A3.plain(payload.exception || "Upload failed"));

					await A3.call("a3_retail.api.emi.attach_document", {
						name: application, row,
						file_url: payload.message.file_url,
						document_number: $("w-number").value.trim() || null,
						expiry_date: $("w-expiry").value || null,
					});
					$("work-modal").hidden = true;
					toast("Document on file.", "ok");
					openApplication(application);
				} catch (error) {
					workMessage(error.message, "error");
				}
			});
	}

	async function verifyDocument(application, row) {
		try {
			await A3.call("a3_retail.api.emi.verify_document", { name: application, row });
			toast("Verified.", "ok");
			openApplication(application);
		} catch (error) {
			fail(error, "That could not be verified");
		}
	}

	function refreshAfterChange(name) {
		loadHead();
		loadTab();
		if (name) openApplication(name);
	}

	async function printApplication(name) {
		try {
			const url = await A3.call("a3_retail.api.emi.print_url", { name });
			window.open(url, "_blank");
		} catch (error) {
			fail(error, "That would not print");
		}
	}

	function moreFor(name) {
		openWork(name, "What else this application can do.",
			`<ul class="simple-list">
				<li><button class="linkish" data-do="open">Open the application</button></li>
				<li><button class="linkish" data-do="print">Print the application form</button></li>
				<li><button class="linkish" data-do="checklist">Print the document checklist</button></li>
				<li><button class="linkish" data-do="calc">Open the EMI calculator</button></li>
			</ul>`);

		$("work-body").querySelectorAll("[data-do]").forEach((node) => {
			node.addEventListener("click", async () => {
				$("work-modal").hidden = true;
				if (node.dataset.do === "open") return openApplication(name);
				if (node.dataset.do === "calc") return calculator();
				const format = node.dataset.do === "checklist"
					? "EMI Document Checklist" : "EMI Application Form";
				const url = await A3.call("a3_retail.api.emi.print_url", { name, print_format: format });
				window.open(url, "_blank");
			});
		});
	}

	// ================================================== schemes and partners
	function showScheme(name) {
		const scheme = state.rows.find((row) => row.name === name);
		if (!scheme) return;

		openWork(scheme.scheme_name, `${scheme.finance_partner} · ${scheme.tenure_months} months`,
			`<div class="emi-view-grid two">
				<div class="emi-block"><h4>Commercials</h4>
					${[["Interest", scheme.is_no_cost_emi ? "No cost EMI"
						: `${scheme.interest_rate}% ${scheme.interest_type || "Flat"}`],
					   ["Processing fee", scheme.processing_fee_type === "Percentage"
						? scheme.processing_fee + "%" : money(scheme.processing_fee)],
					   ["Documentation fee", money(scheme.documentation_fee)],
					   ["Down payment", scheme.down_payment_percent
						? scheme.down_payment_percent + "%" : money(scheme.min_down_payment)],
					   ["Merchant subvention", (scheme.subvention_percent || 0) + "%"],
					   ["Customer subvention", (scheme.customer_subvention_percent || 0) + "%"],
					   ["Cashback", money(scheme.cashback_amount)],
					   ["Ticket size", `${money(scheme.min_invoice_amount)} – ${
						scheme.max_invoice_amount ? money(scheme.max_invoice_amount) : "no ceiling"}`]]
						.map(([label, value]) =>
							`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
				</div>
				<div class="emi-block"><h4>Where it applies</h4>
					${[["Brands", (scheme.brands || []).join(", ") || "Any"],
					   ["Categories", (scheme.item_groups || []).join(", ") || "Any"],
					   ["Branches", (scheme.branches || []).join(", ") || "All branches"],
					   ["Valid", `${day(scheme.valid_from)} – ${day(scheme.valid_upto)}`],
					   ["Applications", scheme.applications],
					   ["Status", scheme.state]]
						.map(([label, value]) =>
							`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
				</div>
			</div>
			<div class="emi-block"><h4>Documents this scheme needs</h4>
				${(scheme.documents || []).length
					? `<div class="emi-chips">${scheme.documents.map((row) =>
						`<span class="pill ${row.is_mandatory ? "pill-warn" : "pill-sky"}">${
							esc(row.document_type)}</span>`).join("")}</div>`
					: '<p class="emi-hint">Nothing scheme-specific — the financier\'s own list applies.</p>'}
			</div>
			${scheme.description ? `<p class="emi-hint">${esc(scheme.description)}</p>` : ""}`);
	}

	function schemeForm(name) {
		const scheme = name ? state.rows.find((row) => row.name === name) : {};
		const boot = state.boot;

		openWork(name ? "Edit " + name : "Add an EMI scheme",
			"The shop's own commercial configuration. The financier still decides the final "
			+ "terms on every application.",
			`<div class="field-grid three">
				${field("Scheme name", "s-name", name ? "disabled" : "", scheme.scheme_name)}
				${select("Financier", "s-partner", boot.partners.map((row) => row.name),
					scheme.finance_partner)}
				${field("Scheme code", "s-code", "", scheme.scheme_code)}
			</div>
			<div class="field-grid three">
				${field("Tenure (months)", "s-tenure", 'type="number" min="1" step="1"',
					scheme.tenure_months || 12)}
				${select("Interest", "s-nocost", [["1", "No cost EMI"], ["0", "Interest bearing"]],
					String(scheme.is_no_cost_emi == null ? 1 : (scheme.is_no_cost_emi ? 1 : 0)))}
				${field("Interest rate (%)", "s-rate", 'type="number" step="0.01"',
					scheme.interest_rate)}
			</div>
			<div class="field-grid three">
				${select("Interest type", "s-itype", ["Flat", "Reducing Balance"],
					scheme.interest_type || "Flat")}
				${field("Processing fee", "s-fee", 'type="number" step="1"', scheme.processing_fee)}
				${select("Fee type", "s-feetype", ["Fixed", "Percentage"],
					scheme.processing_fee_type || "Fixed")}
			</div>
			<div class="field-grid three">
				${field("Documentation fee", "s-docfee", 'type="number" step="1"',
					scheme.documentation_fee)}
				${field("Down payment (%)", "s-dp", 'type="number" step="0.01"',
					scheme.down_payment_percent)}
				${field("Minimum down payment", "s-mindp", 'type="number" step="1"',
					scheme.min_down_payment)}
			</div>
			<div class="field-grid three">
				${field("Maximum down payment", "s-maxdp", 'type="number" step="1"',
					scheme.max_down_payment)}
				${field("Merchant subvention (%)", "s-subv", 'type="number" step="0.01"',
					scheme.subvention_percent)}
				${field("Customer subvention (%)", "s-csubv", 'type="number" step="0.01"',
					scheme.customer_subvention_percent)}
			</div>
			<div class="field-grid three">
				${field("Minimum invoice", "s-min", 'type="number" step="1"', scheme.min_invoice_amount)}
				${field("Maximum invoice", "s-max", 'type="number" step="1"', scheme.max_invoice_amount)}
				${field("Cashback", "s-cashback", 'type="number" step="1"', scheme.cashback_amount)}
			</div>
			<div class="field-grid three">
				${field("Valid from", "s-from", 'type="date"', scheme.valid_from)}
				${field("Valid to", "s-to", 'type="date"', scheme.valid_upto)}
				${select("Status", "s-active", [["1", "Active"], ["0", "Inactive"]],
					String(scheme.is_active == null ? 1 : (scheme.is_active ? 1 : 0)))}
			</div>
			<div class="field-grid">
				${multi("Eligible brands", "s-brands", boot.brands, scheme.brands || [])}
				${multi("Eligible categories", "s-groups", boot.item_groups, scheme.item_groups || [])}
				${multi("Branches (none = all)", "s-branches", boot.branches, scheme.branches || [])}
			</div>
			<div class="emi-block"><h4>Documents this scheme needs</h4>
				<p class="emi-hint">Tick only what this scheme actually asks for — a pre-approved
					offer needs far less than a fresh loan. Left empty, the financier's own list applies.</p>
				<div class="emi-chips">${boot.document_types.map((type) => {
					const chosen = (scheme.documents || []).find((row) =>
						row.document_type === type.name);
					return `<label class="emi-chip"><input type="checkbox" data-doc="${esc(type.name)}"
						${chosen ? "checked" : ""}> ${esc(type.document_name)}</label>`;
				}).join("")}</div>
			</div>
			${field("Description", "s-desc", 'placeholder="What the counter should tell a customer"',
				scheme.description)}`,
			name ? "Save the scheme" : "Create the scheme", async () => {
				try {
					const payload = {
						name: name || null,
						scheme_name: $("s-name").value.trim(),
						finance_partner: $("s-partner").value,
						scheme_code: $("s-code").value.trim(),
						tenure_months: Number($("s-tenure").value) || 0,
						is_no_cost_emi: Number($("s-nocost").value),
						interest_rate: Number($("s-rate").value) || 0,
						interest_type: $("s-itype").value,
						processing_fee: Number($("s-fee").value) || 0,
						processing_fee_type: $("s-feetype").value,
						documentation_fee: Number($("s-docfee").value) || 0,
						down_payment_percent: Number($("s-dp").value) || 0,
						min_down_payment: Number($("s-mindp").value) || 0,
						max_down_payment: Number($("s-maxdp").value) || 0,
						subvention_percent: Number($("s-subv").value) || 0,
						customer_subvention_percent: Number($("s-csubv").value) || 0,
						min_invoice_amount: Number($("s-min").value) || 0,
						max_invoice_amount: Number($("s-max").value) || 0,
						cashback_amount: Number($("s-cashback").value) || 0,
						valid_from: $("s-from").value || null,
						valid_upto: $("s-to").value || null,
						is_active: Number($("s-active").value),
						brands: chosenValues("s-brands"),
						item_groups: chosenValues("s-groups"),
						branches: chosenValues("s-branches"),
						description: $("s-desc").value.trim(),
						documents: [...$("work-body").querySelectorAll("[data-doc]:checked")]
							.map((node) => ({ document_type: node.dataset.doc, is_mandatory: 1 })),
					};
					const result = await A3.call("a3_retail.api.emi.save_scheme", { payload });
					$("work-modal").hidden = true;
					toast(`${result.scheme} saved.`, "ok");
					await refreshBoot();
					loadTab();
				} catch (error) {
					workMessage(error.message, "error");
				}
			});
	}

	function multi(label, id, options, chosen) {
		return `<label class="field"><span>${label}</span>
			<select id="${id}" multiple size="4">${options.map((option) =>
				`<option value="${esc(option)}" ${chosen.includes(option) ? "selected" : ""}>${
					esc(option)}</option>`).join("")}</select></label>`;
	}

	function chosenValues(id) {
		return [...$(id).selectedOptions].map((option) => option.value);
	}

	async function toggleScheme(name) {
		const scheme = state.rows.find((row) => row.name === name);
		try {
			const result = await A3.call("a3_retail.api.emi.set_scheme_active", {
				name, active: scheme.is_active ? 0 : 1 });
			toast(`${name} is ${result.is_active ? "active" : "inactive"}.`, "ok");
			loadTab();
		} catch (error) {
			fail(error, "That scheme would not change");
		}
	}

	function showPartner(name) {
		const partner = state.rows.find((row) => row.name === name);
		if (!partner) return;

		openWork(partner.partner_name || partner.name,
			`${partner.partner_type || ""} · ${partner.integration}`,
			`<div class="emi-view-grid two">
				<div class="emi-block"><h4>The partner</h4>
					${[["Legal name", partner.legal_name || "—"],
					   ["Merchant ID", partner.merchant_id || "—"],
					   ["Mode of payment", partner.mode_of_payment || "—"],
					   ["Settles in", partner.settlement_tat_days ? "T+" + partner.settlement_tat_days : "—"],
					   ["Ticket size", `${money(partner.min_ticket_size)} – ${
						partner.max_ticket_size ? money(partner.max_ticket_size) : "no ceiling"}`],
					   ["Subvention borne by", partner.subvention_borne_by || "—"],
					   ["Support", partner.support_contact || "—"],
					   partner.mdr_percent != null ? ["MDR", partner.mdr_percent + "%"] : null]
						.filter(Boolean).map(([label, value]) =>
							`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
				</div>
				<div class="emi-block"><h4>Right now</h4>
					${[["Active schemes", partner.schemes],
					   ["Applications", partner.applications],
					   ["Approved", partner.approved],
					   ["Pending settlement", money(partner.pending_settlement)],
					   ["Submission", partner.integration]]
						.map(([label, value]) =>
							`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
				</div>
			</div>
			<div class="emi-block"><h4>Branch configuration</h4>
				${(partner.branch_codes || []).length ? `<table class="bill-table emi-table">
					<thead><tr><th>Branch</th><th>Merchant ID</th><th>Terminal</th><th>Dealer code</th>
						<th>Settlement account</th><th>Status</th></tr></thead>
					<tbody>${partner.branch_codes.map((code) => `<tr>
						<td>${esc(code.branch)}</td><td>${esc(code.merchant_id || "—")}</td>
						<td>${esc(code.terminal_id || "—")}</td><td>${esc(code.dealer_code || "—")}</td>
						<td>${esc(code.settlement_account || "partner default")}</td>
						<td>${pill(code.is_active ? "Active" : "Off",
							code.is_active ? "pill-good" : "pill-bad")}</td></tr>`).join("")}</tbody>
				</table>` : '<p class="emi-hint">No branch-specific codes — the partner merchant ID '
					+ 'applies everywhere.</p>'}
			</div>
			<p class="emi-hint">API credentials are stored on the partner record server-side and are
				never shown or set from this screen.</p>`);
	}

	function partnerForm(name) {
		const partner = name ? state.rows.find((row) => row.name === name) : {};
		const boot = state.boot;

		openWork(name ? "Edit " + name : "Add a financing partner",
			"Everything the shop needs to sell this partner's finance — including a merchant "
			+ "code per branch, which is how most of them are set up.",
			`<div class="field-grid three">
				${field("Financier name", "p-name", name ? "disabled" : "",
					partner.partner_name || partner.name)}
				${select("Type", "p-type", boot.partner_types, partner.partner_type)}
				${field("Legal name", "p-legal", "", partner.legal_name)}
			</div>
			<div class="field-grid three">
				${field("Merchant ID", "p-merchant", "", partner.merchant_id)}
				${select("Mode of payment", "p-mode",
					[""].concat(boot.payment_modes || []), partner.mode_of_payment)}
				${field("Settlement cycle (days)", "p-tat", 'type="number" step="1"',
					partner.settlement_tat_days)}
			</div>
			<div class="field-grid three">
				${field("Support contact", "p-contact", "", partner.support_contact)}
				${field("Support email", "p-email", 'type="email"', partner.support_email)}
				${select("Status", "p-active", [["1", "Active"], ["0", "Inactive"]],
					String(partner.is_active == null ? 1 : (partner.is_active ? 1 : 0)))}
			</div>
			<div class="field-grid three">
				${field("Minimum ticket", "p-min", 'type="number" step="1"', partner.min_ticket_size)}
				${field("Maximum ticket", "p-max", 'type="number" step="1"', partner.max_ticket_size)}
				${select("Integration", "p-api", [["0", "Manual / portal"], ["1", "REST API"]],
					String(partner.api_integration_enabled ? 1 : 0))}
			</div>
			${field("API base URL", "p-url", 'placeholder="https://…"', partner.api_base_url)}
			<p class="emi-hint">Credentials are never entered here. A system administrator stores the
				key on the partner record, where it is encrypted and only read server-side.</p>
			<div class="emi-block"><h4>Branch configuration</h4>
				<div id="p-branches">${(partner.branch_codes || []).length
					? partner.branch_codes.map(branchCodeRow).join("")
					: branchCodeRow({ branch: state.branch, is_active: 1 })}</div>
				<button class="linkish" id="p-add-branch">+ Another branch</button>
			</div>`,
			name ? "Save the partner" : "Create the partner", async () => {
				try {
					const payload = {
						name: name || null,
						partner_name: $("p-name").value.trim(),
						partner_type: $("p-type").value,
						legal_name: $("p-legal").value.trim(),
						merchant_id: $("p-merchant").value.trim(),
						mode_of_payment: $("p-mode").value || null,
						settlement_tat_days: Number($("p-tat").value) || 0,
						support_contact: $("p-contact").value.trim(),
						support_email: $("p-email").value.trim(),
						is_active: Number($("p-active").value),
						min_ticket_size: Number($("p-min").value) || 0,
						max_ticket_size: Number($("p-max").value) || 0,
						api_integration_enabled: Number($("p-api").value),
						api_base_url: $("p-url").value.trim(),
						branch_codes: [...$("p-branches").querySelectorAll(".emi-branch-row")]
							.map((row) => ({
								branch: row.querySelector("[data-branch]").value,
								merchant_id: row.querySelector("[data-merchant]").value.trim(),
								terminal_id: row.querySelector("[data-terminal]").value.trim(),
								dealer_code: row.querySelector("[data-dealer]").value.trim(),
								is_active: row.querySelector("[data-active]").checked ? 1 : 0,
							})).filter((row) => row.branch),
					};
					const result = await A3.call("a3_retail.api.emi.save_partner", { payload });
					$("work-modal").hidden = true;
					toast(`${result.partner} saved.`, "ok");
					await refreshBoot();
					loadTab();
				} catch (error) {
					workMessage(error.message, "error");
				}
			});

		$("p-add-branch").addEventListener("click", () => {
			$("p-branches").insertAdjacentHTML("beforeend",
				branchCodeRow({ branch: state.branch, is_active: 1 }));
		});
	}

	function branchCodeRow(code) {
		const branches = state.boot.branches.length ? state.boot.branches : [state.branch];
		return `<div class="emi-branch-row">
			<select data-branch>${branches.map((branch) =>
				`<option value="${esc(branch)}" ${branch === code.branch ? "selected" : ""}>${
					esc(branch)}</option>`).join("")}</select>
			<input data-merchant placeholder="Merchant ID" value="${esc(code.merchant_id || "")}">
			<input data-terminal placeholder="Terminal ID" value="${esc(code.terminal_id || "")}">
			<input data-dealer placeholder="Dealer code" value="${esc(code.dealer_code || "")}">
			<label class="tickbox"><input type="checkbox" data-active ${
				code.is_active ? "checked" : ""}><span>Active</span></label>
		</div>`;
	}

	// ============================================================ settlement
	function askSettlement(partner) {
		const today = new Date().toISOString().slice(0, 10);
		const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

		openWork("Open a settlement",
			"Pull in everything this financier has disbursed but not paid for, then key in what "
			+ "the bank actually credited.",
			`<div class="field-grid three">
				${select("Financier", "t-partner", state.boot.partners.map((row) => row.name),
					partner || "")}
				${field("From", "t-from", 'type="date"', monthAgo)}
				${field("To", "t-to", 'type="date"', today)}
			</div>
			${select("Credited to", "t-bank", [""].concat(state.boot.accounts), "")}`,
			"Pull the applications", async () => {
				try {
					workMessage("Pulling…");
					const result = await A3.call("a3_retail.api.emi.draft_settlement", {
						partner: $("t-partner").value,
						from_date: $("t-from").value,
						to_date: $("t-to").value,
						bank_account: $("t-bank").value || null,
					});
					$("work-modal").hidden = true;
					toast(`${result.settlement}: ${result.applications} sales, ${
						money(result.expected)} expected.`, "ok");
					openSettlement(result.settlement);
				} catch (error) {
					workMessage(error.message, "error");
				}
			});
	}

	async function openSettlement(name) {
		try {
			const data = await A3.call("a3_retail.api.emi.settlement", { name });
			const totals = data.totals;

			openWork(`Settlement ${data.name}`,
				`${data.partner} · ${day(data.from_date)} – ${day(data.to_date)}`,
				`<div class="emi-view-grid two">
					<div class="emi-block"><h4>What the financier owes</h4>
						${[["Gross financed", money2(totals.gross)],
						   ["MDR", "- " + money2(totals.mdr)],
						   ["Merchant subvention", "- " + money2(totals.subvention)],
						   ["GST on MDR", "- " + money2(totals.gst_on_mdr)],
						   ["TDS", "- " + money2(totals.tds)],
						   ["Other deductions", "- " + money2(totals.other)],
						   ["Net expected", `<span class="strong">${money2(totals.expected)}</span>`]]
							.map(([label, value]) =>
								`<div class="sum-row"><span>${label}</span><b>${value}</b></div>`).join("")}
					</div>
					<div class="emi-block"><h4>What arrived</h4>
						${[["Received", money2(totals.received)],
						   ["Difference", `<span class="${Math.abs(totals.variance) > 1
							? "warn-red" : "good"}">${money2(totals.variance)}</span>`],
						   ["Bank reference", esc(data.utr_reference || "—")],
						   ["Account", esc(data.bank_account || "—")],
						   ["Status", data.status],
						   data.journal_entry && ["Journal entry", esc(data.journal_entry)]]
							.filter(Boolean).map(([label, value]) =>
								`<div class="sum-row"><span>${label}</span><b>${value}</b></div>`).join("")}
					</div>
				</div>

				${data.can.record ? `<div class="emi-block"><h4>Record the credit</h4>
					<div class="field-grid three">
						${field("Amount received", "t-received", 'type="number" step="0.01"',
							totals.received || totals.expected)}
						${field("Bank reference / UTR", "t-utr", "", data.utr_reference)}
						${select("Credited to", "t-account", [""].concat(state.boot.accounts),
							data.bank_account)}
					</div>
					<div class="emi-settle-actions">
						<button class="btn btn-primary" id="t-post">Mark received and post</button>
						<button class="btn btn-quiet" id="t-dispute">Query the difference</button>
					</div>
					<p class="emi-hint">Posting writes one Journal Entry: the bank credit, the MDR and
						subvention as expense, the GST as input credit, and the partner's receivable
						cleared in full.</p>
				</div>` : ""}

				<div class="emi-block"><h4>Sales in this settlement</h4>
					<div class="bill-table-wrap"><table class="bill-table emi-table">
						<thead><tr><th>Application</th><th>Invoice</th><th>Customer</th>
							<th class="num">Financed</th><th class="num">MDR</th>
							<th class="num">Subvention</th><th class="num">Net</th></tr></thead>
						<tbody>${data.rows.map((row) => `<tr>
							<td>${esc(row.application)}</td>
							<td>${row.invoice ? esc(row.invoice) : "—"}</td>
							<td>${esc(row.customer || "")}</td>
							<td class="num">${money(row.loan_amount)}</td>
							<td class="num">${money(row.mdr)}</td>
							<td class="num">${money(row.subvention)}</td>
							<td class="num strong">${money(row.net_amount)}</td></tr>`).join("")}</tbody>
					</table></div>
				</div>`);

			$("work-go").hidden = false;
			$("work-go").textContent = "Print statement";
			$("work-go").onclick = () => window.open(data.print_url, "_blank");

			if ($("t-post")) {
				$("t-post").addEventListener("click", async () => {
					try {
						workMessage("Posting…");
						const result = await A3.call("a3_retail.api.emi.record_settlement", {
							name: data.name,
							net_received: Number($("t-received").value) || 0,
							utr_reference: $("t-utr").value.trim() || null,
							bank_account: $("t-account").value || null,
						});
						$("work-modal").hidden = true;
						toast(`${result.settlement} posted — ${result.journal_entry || "no entry"}, `
							+ `difference ${money(result.variance)}.`, "ok");
						loadHead();
						loadTab();
					} catch (error) {
						workMessage(error.message, "error");
					}
				});
			}
			if ($("t-dispute")) {
				$("t-dispute").addEventListener("click", async () => {
					const remarks = window.prompt("What is being queried with the financier?");
					if (!remarks) return;
					try {
						await A3.call("a3_retail.api.emi.raise_dispute", { name: data.name, remarks });
						$("work-modal").hidden = true;
						toast("Raised with the financier.", "ok");
						loadTab();
					} catch (error) {
						fail(error, "That query would not save");
					}
				});
			}
		} catch (error) {
			fail(error, "That settlement would not open");
		}
	}

	// ============================================================ calculator
	function calculator() {
		openWork("EMI calculator",
			"Indicative only. It quotes nobody and approves nothing — the financier's own portal "
			+ "decides the instalment a customer is actually offered.",
			`<div class="field-grid three">
				${field("Product price", "c-price", 'type="number" step="1"', 79999)}
				${field("Down payment", "c-down", 'type="number" step="1"', 10000)}
				${field("Tenure (months)", "c-tenure", 'type="number" step="1"', 12)}
			</div>
			<div class="field-grid three">
				${field("Interest rate (%)", "c-rate", 'type="number" step="0.01"', 0)}
				${select("Interest type", "c-type", ["Flat", "Reducing Balance"], "Flat")}
				${field("Processing fee", "c-fee", 'type="number" step="1"', 999)}
			</div>
			<div class="emi-summary" id="c-out"></div>`,
			"Close", () => { $("work-modal").hidden = true; });

		const recalc = async () => {
			try {
				const result = await A3.call("a3_retail.api.emi.calculate", {
					price: Number($("c-price").value) || 0,
					down_payment: Number($("c-down").value) || 0,
					interest_rate: Number($("c-rate").value) || 0,
					tenure_months: Number($("c-tenure").value) || 0,
					interest_type: $("c-type").value,
					processing_fee: Number($("c-fee").value) || 0,
				});
				$("c-out").innerHTML = `
					<div class="emi-summary-grid">
						${[["Financed amount", money2(result.loan_amount)],
						   ["EMI", `<span class="emi-big">${money2(result.emi_amount)}</span>`],
						   ["Tenure", result.tenure_months + " months"],
						   ["Total interest", money2(result.total_interest)],
						   ["Total repayment", money2(result.total_repayment)],
						   ["Customer pays today", `<span class="emi-big">${
							money2(result.customer_payable_today)}</span>`],
						   ["Total cost of the purchase", money2(result.total_cost)]]
							.map(([label, value]) =>
								`<div class="sum-row"><span>${label}</span><b>${value}</b></div>`).join("")}
					</div>
					<p class="emi-hint">Indicative — not an offer of finance.</p>`;
			} catch (error) {
				workMessage(error.message, "error");
			}
		};

		["c-price", "c-down", "c-tenure", "c-rate", "c-fee"].forEach((id) => {
			$(id).addEventListener("input", recalc);
		});
		$("c-type").addEventListener("change", recalc);
		recalc();
	}

	// =========================================================== the wizard
	const STEPS = ["Customer", "Purchase", "Financier", "Scheme", "Contribution", "Documents",
	               "Review"];

	function openWizard(existing) {
		state.wizard = {
			step: 0,
			name: existing ? existing.name : null,
			customer: existing ? existing.customer.name : null,
			customer_name: existing ? existing.customer.customer_name : "",
			mobile: existing ? existing.customer.mobile_no : "",
			email: existing ? existing.customer.email : "",
			employment: existing ? existing.customer.employment_type : "",
			income: existing ? existing.customer.monthly_income : 0,
			pan: "",
			aadhaar: "",
			invoice: existing ? existing.purchase.invoice : (state.opening.invoice || null),
			items: existing ? existing.items : [],
			total: existing ? existing.purchase.invoice_total : 0,
			partner: existing ? existing.finance.partner : null,
			scheme: existing ? existing.finance.scheme : null,
			quote: null,
			down_payment: existing ? existing.loan.down_payment : 0,
			schemes: [],
			documents: existing ? existing.documents : [],
		};

		$("wizard-title").textContent = existing
			? "Edit application " + existing.name : "New EMI Application";
		$("wizard-modal").hidden = false;
		paintWizard();

		if (state.opening.invoice && !existing) loadInvoiceIntoWizard(state.opening.invoice);
		if (state.opening.customer && !existing) {
			state.wizard.customer = state.opening.customer;
			paintWizard();
		}
	}

	function paintWizard() {
		const wizard = state.wizard;
		document.querySelectorAll("#wizard-steps li").forEach((node, index) => {
			node.classList.toggle("is-active", index === wizard.step);
			node.classList.toggle("is-done", index < wizard.step);
		});
		$("wizard-msg").textContent = "";
		$("wizard-back").hidden = wizard.step === 0;
		$("wizard-next").textContent = wizard.step === STEPS.length - 1
			? "Submit application" : "Continue";
		$("wizard-body").innerHTML = WIZARD[wizard.step]();
		if (WIRE[wizard.step]) WIRE[wizard.step]();
	}

	const WIZARD = [];
	const WIRE = [];

	// -- 1 customer
	WIZARD[0] = () => {
		const wizard = state.wizard;
		return `<p class="emi-hint">Find the customer by mobile number — the shop's own record
			fills in the rest. Only the last four digits of an Aadhaar are ever stored.</p>
		<div class="field-grid three">
			${field("Mobile", "z-mobile", 'maxlength="10" inputmode="numeric"', wizard.mobile)}
			${field("Customer name", "z-name", "", wizard.customer_name)}
			${field("Email", "z-email", 'type="email"', wizard.email)}
		</div>
		<div class="field-grid three">
			${select("Employment", "z-employment", [""].concat(state.boot.employment_types),
				wizard.employment)}
			${field("Monthly income", "z-income", 'type="number" step="1"', wizard.income)}
			${field("Date of birth", "z-dob", 'type="date"', wizard.dob)}
		</div>
		<div class="field-grid three">
			${field("PAN", "z-pan", 'maxlength="10" placeholder="ABCDE1234F"', wizard.pan)}
			${field("Aadhaar — last 4 only", "z-aadhaar", 'maxlength="4" inputmode="numeric"',
				wizard.aadhaar)}
			${field("Existing loan account with this partner", "z-existing", "", wizard.existing)}
		</div>
		<div class="msg" id="z-customer-msg">${wizard.customer
			? "Using the existing customer record " + esc(wizard.customer) : ""}</div>`;
	};

	WIRE[0] = () => {
		$("z-mobile").addEventListener("change", async () => {
			const mobile = $("z-mobile").value.trim();
			if (mobile.length !== 10) return;
			try {
				const found = await A3.call("a3_retail.api.pos.search_customers", { query: mobile });
				if (found.length) {
					state.wizard.customer = found[0].name;
					$("z-name").value = found[0].customer_name || "";
					$("z-customer-msg").textContent =
						`Found ${found[0].customer_name} — their record will be used.`;
					$("z-customer-msg").className = "msg ok";
				} else {
					state.wizard.customer = null;
					$("z-customer-msg").textContent = "New to the shop — a customer record will be "
						+ "created when the application is saved.";
					$("z-customer-msg").className = "msg";
				}
			} catch (error) {
				/* the lookup is a convenience; typing the name still works */
			}
		});
	};

	// -- 2 purchase
	WIZARD[1] = () => {
		const wizard = state.wizard;
		return `<p class="emi-hint">Attach the sale this loan pays for. An invoice already raised
			at the counter is pulled in as it stands — nothing is re-priced here, and no second
			sale is created.</p>
		<div class="field-grid">
			${field("Sales invoice", "z-invoice", 'placeholder="SINV-…"', wizard.invoice)}
			<button class="btn btn-outline" id="z-load-invoice">Load the invoice</button>
		</div>
		<div id="z-items">${itemsTable(wizard)}</div>
		<div class="field-grid">
			${field("Invoice total", "z-total", 'type="number" step="0.01"', wizard.total)}
		</div>`;
	};

	function itemsTable(wizard) {
		if (!wizard.items.length) {
			return '<div class="cust-none">No products on this application yet. Load an invoice, '
				+ 'or type the total below for a pre-approval.</div>';
		}
		return `<div class="bill-table-wrap"><table class="bill-table emi-table">
			<thead><tr><th>Product</th><th>SKU</th><th>IMEI</th><th class="num">Qty</th>
				<th class="num">Rate</th><th class="num">Amount</th></tr></thead>
			<tbody>${wizard.items.map((row) => `<tr>
				<td>${esc(row.item_name)}</td><td>${esc(row.item_code)}</td>
				<td>${esc(row.serial_no || "—")}</td>
				<td class="num">${row.qty}</td><td class="num">${money2(row.rate)}</td>
				<td class="num strong">${money2(row.amount || row.rate * row.qty)}</td></tr>`).join("")}</tbody>
		</table></div>`;
	}

	WIRE[1] = () => {
		$("z-load-invoice").addEventListener("click", () =>
			loadInvoiceIntoWizard($("z-invoice").value.trim()));
	};

	async function loadInvoiceIntoWizard(invoice) {
		if (!invoice) return;
		try {
			const bill = await A3.call("a3_retail.api.bills.invoice", { name: invoice });
			state.wizard.invoice = bill.name;
			state.wizard.customer = bill.customer.name;
			state.wizard.customer_name = bill.customer.customer_name;
			state.wizard.mobile = bill.customer.mobile_no || state.wizard.mobile;
			state.wizard.total = bill.totals.payable;
			state.wizard.items = bill.items.map((row) => ({
				item_code: row.item_code, item_name: row.item_name, qty: row.qty,
				rate: row.rate, amount: row.amount, serial_no: (row.serials || [])[0] || null,
			}));
			paintWizard();
			wizardMessage(`Loaded ${bill.name} — ${money2(bill.totals.payable)}.`, "ok");
		} catch (error) {
			wizardMessage(error.message, "error");
		}
	}

	// -- 3 financier
	WIZARD[2] = () => {
		const partners = state.boot.partners;
		return `<p class="emi-hint">Which financier is the customer applying to? Only partners this
			branch is set up with are offered.</p>
		<div class="emi-partner-picker">${partners.map((row) => `
			<button class="emi-pick ${state.wizard.partner === row.name ? "is-active" : ""}"
			        data-pick-partner="${esc(row.name)}">
				<span class="emi-pick-name">${esc(row.partner_name || row.name)}</span>
				<span class="emi-pick-sub">${esc(row.partner_type || "")}${
					row.settlement_tat_days ? " · settles T+" + row.settlement_tat_days : ""}</span>
			</button>`).join("")}</div>`;
	};

	WIRE[2] = () => {
		$("wizard-body").querySelectorAll("[data-pick-partner]").forEach((node) => {
			node.addEventListener("click", () => {
				state.wizard.partner = node.dataset.pickPartner;
				state.wizard.scheme = null;
				paintWizard();
			});
		});
	};

	// -- 4 scheme
	WIZARD[3] = () => '<div class="pos-loading">Finding the schemes this purchase qualifies for…</div>';

	WIRE[3] = async () => {
		const wizard = state.wizard;
		try {
			const schemes = await A3.call("a3_retail.api.emi.eligible_schemes", {
				invoice_total: wizard.total,
				partner: wizard.partner,
				item_code: (wizard.items[0] || {}).item_code || null,
			});
			wizard.schemes = schemes;

			if (!schemes.length) {
				$("wizard-body").innerHTML = `<section class="rep-empty">
					<b>No scheme fits this purchase</b>
					<span>${esc(wizard.partner || "This financier")} has nothing active for
						${money2(wizard.total)} at this branch today. Try another financier, or ask
						head office to configure a scheme.</span></section>`;
				return;
			}

			$("wizard-body").innerHTML = `<p class="emi-hint">Every figure below is the shop's own
				arithmetic on its scheme configuration — indicative. ${esc(wizard.partner)} decides
				the instalment the customer is actually offered.</p>
			<div class="emi-scheme-cards">${schemes.map((scheme) => `
				<button class="emi-scheme ${wizard.scheme === scheme.name ? "is-active" : ""}"
				        data-scheme="${esc(scheme.name)}">
					<span class="emi-scheme-top">
						<b>${scheme.tenure_months} months</b>
						${scheme.is_no_cost_emi ? '<span class="pill pill-good">No cost</span>'
							: `<span class="pill pill-warn">${scheme.interest_rate}%</span>`}</span>
					<span class="emi-scheme-emi">${money2(scheme.emi_amount)}<small>/ month</small></span>
					<span class="emi-scheme-name">${esc(scheme.scheme_name)}</span>
					<span class="emi-scheme-rows">
						<span>Down payment<b>${money(scheme.suggested_down_payment)}</b></span>
						<span>Processing fee<b>${money(scheme.processing_fee_amount)}</b></span>
						${scheme.documentation_fee
							? `<span>Documentation<b>${money(scheme.documentation_fee)}</b></span>` : ""}
						<span>Merchant subvention<b>${scheme.subvention_percent || 0}%</b></span>
						<span>Customer subvention<b>${scheme.customer_subvention_percent || 0}%</b></span>
						${scheme.cashback_amount
							? `<span>Cashback<b>${money(scheme.cashback_amount)}</b></span>` : ""}
						<span>Payable today<b>${money(scheme.customer_payable_today)}</b></span>
					</span>
				</button>`).join("")}</div>`;

			$("wizard-body").querySelectorAll("[data-scheme]").forEach((node) => {
				node.addEventListener("click", () => {
					wizard.scheme = node.dataset.scheme;
					wizard.quote = schemes.find((row) => row.name === wizard.scheme);
					wizard.down_payment = wizard.quote.suggested_down_payment;
					paintWizard();
				});
			});
		} catch (error) {
			$("wizard-body").innerHTML = `<section class="rep-empty"><b>Could not read the schemes</b>
				<span>${esc(error.message)}</span></section>`;
		}
	};

	// -- 5 contribution
	WIZARD[4] = () => {
		const wizard = state.wizard;
		const quote = wizard.quote || {};
		const down = wizard.down_payment || 0;
		const loan = Math.max((wizard.total || 0) - down, 0);
		const fees = (quote.processing_fee_amount || 0) + (quote.documentation_fee || 0);

		return `<div class="emi-contribution">
			<div>
				<div class="field-grid">
					${field("Down payment", "z-down", 'type="number" step="1"', down)}
					${field("Processing fee", "z-fee", 'type="number" step="1"',
						quote.processing_fee_amount || 0)}
					${field("Documentation fee", "z-docfee", 'type="number" step="1"',
						quote.documentation_fee || 0)}
				</div>
				<p class="emi-hint">The scheme's minimum down payment is
					${money(quote.suggested_down_payment || 0)}; the application refuses anything less.</p>
			</div>
			<div class="emi-summary">
				<div class="sum-row"><span>Product total</span><b>${money2(wizard.total)}</b></div>
				<div class="sum-row"><span>Down payment</span><b>${money2(down)}</b></div>
				<div class="sum-row"><span>Financed amount</span>
					<b class="strong">${money2(loan)}</b></div>
				<div class="sum-row"><span>Fees</span><b>${money2(fees)}</b></div>
				<div class="sum-row emi-summary-big"><span>Customer pays today</span>
					<b>${money2(down + fees)}</b></div>
				<div class="sum-row emi-summary-big"><span>EMI</span>
					<b>${money2(quote.emi_amount || 0)} × ${quote.tenure_months || 0}M</b></div>
				<p class="emi-hint">Indicative until ${esc(wizard.partner || "the financier")} answers.</p>
			</div>
		</div>`;
	};

	WIRE[4] = () => {
		["z-down", "z-fee", "z-docfee"].forEach((id) => {
			$(id).addEventListener("input", () => {
				state.wizard.down_payment = Number($("z-down").value) || 0;
				if (state.wizard.quote) {
					state.wizard.quote.processing_fee_amount = Number($("z-fee").value) || 0;
					state.wizard.quote.documentation_fee = Number($("z-docfee").value) || 0;
				}
				const wizard = state.wizard;
				const loan = Math.max((wizard.total || 0) - wizard.down_payment, 0);
				const quote = wizard.quote || {};
				$("wizard-body").querySelector(".emi-summary").innerHTML = `
					<div class="sum-row"><span>Product total</span><b>${money2(wizard.total)}</b></div>
					<div class="sum-row"><span>Down payment</span><b>${money2(wizard.down_payment)}</b></div>
					<div class="sum-row"><span>Financed amount</span>
						<b class="strong">${money2(loan)}</b></div>
					<div class="sum-row"><span>Fees</span><b>${money2(
						(quote.processing_fee_amount || 0) + (quote.documentation_fee || 0))}</b></div>
					<div class="sum-row emi-summary-big"><span>Customer pays today</span>
						<b>${money2(wizard.down_payment + (quote.processing_fee_amount || 0)
							+ (quote.documentation_fee || 0))}</b></div>
					<div class="sum-row emi-summary-big"><span>EMI</span>
						<b>${money2(quote.tenure_months ? loan / quote.tenure_months : 0)} × ${
							quote.tenure_months || 0}M</b></div>
					<p class="emi-hint">Indicative until the financier answers.</p>`;
			});
		});
	};

	// -- 6 documents
	WIZARD[5] = () => {
		const wizard = state.wizard;
		if (!wizard.name) {
			return `<p class="emi-hint">The checklist comes from the scheme — and from the financier
				when the scheme names none of its own. Save the draft to raise it, then upload
				against each row.</p>
			<div class="cust-none">Save the draft first (the button below) and the checklist for
				${esc(wizard.partner || "this financier")} appears here.</div>`;
		}
		return `<p class="emi-hint">Upload against each row. Files are attached to the application
			itself, so they carry its permissions.</p>
		<div class="bill-table-wrap"><table class="bill-table emi-table">
			<thead><tr><th>Document</th><th>Required</th><th>Uploaded</th><th>Verified</th>
				<th>Status</th><th></th></tr></thead>
			<tbody>${wizard.documents.map((row) => `<tr>
				<td><b>${esc(row.document_type)}</b></td>
				<td>${row.is_mandatory ? "Mandatory" : "Optional"}</td>
				<td>${row.is_received ? "yes" : "—"}</td>
				<td>${row.verified ? "yes" : "—"}</td>
				<td>${pill(row.state, row.state === "Verified" ? "pill-good"
					: row.state === "Uploaded" ? "pill-warn"
					: row.state === "Required" ? "pill-bad" : "pill-sky")}</td>
				<td><button class="linkish" data-upload="${esc(row.row)}">${
					row.is_received ? "Replace" : "Upload"}</button></td></tr>`).join("")}</tbody>
		</table></div>`;
	};

	WIRE[5] = () => {
		$("wizard-body").querySelectorAll("[data-upload]").forEach((node) => {
			node.addEventListener("click", () => askUpload(state.wizard.name, node.dataset.upload));
		});
	};

	// -- 7 review
	WIZARD[6] = () => {
		const wizard = state.wizard;
		const quote = wizard.quote || {};
		const loan = Math.max((wizard.total || 0) - (wizard.down_payment || 0), 0);
		const missing = wizard.documents.filter((row) => row.is_mandatory && !row.is_received);

		return `<div class="emi-view-grid two">
			<div class="emi-block"><h4>Customer</h4>
				${[["Name", wizard.customer_name || "—"], ["Mobile", wizard.mobile || "—"],
				   ["Employment", wizard.employment || "—"]].map(([label, value]) =>
					`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
			</div>
			<div class="emi-block"><h4>Purchase</h4>
				${[["Invoice", wizard.invoice || "not raised yet"],
				   ["Products", wizard.items.map((row) => row.item_name).join(", ") || "—"],
				   ["Total", money2(wizard.total)]].map(([label, value]) =>
					`<div class="sum-row"><span>${label}</span><b>${esc(value)}</b></div>`).join("")}
			</div>
			<div class="emi-block"><h4>Finance</h4>
				${[["Financier", wizard.partner || "—"], ["Scheme", wizard.scheme || "—"],
				   ["Financed", money2(loan)], ["Down payment", money2(wizard.down_payment)],
				   ["EMI", `${money2(quote.emi_amount || 0)} × ${quote.tenure_months || 0}M`],
				   ["Fees", money2((quote.processing_fee_amount || 0) + (quote.documentation_fee || 0))]]
					.map(([label, value]) =>
						`<div class="sum-row"><span>${label}</span><b>${value}</b></div>`).join("")}
			</div>
			<div class="emi-block"><h4>Documents</h4>
				${wizard.documents.length
					? `<div class="sum-row"><span>On the checklist</span><b>${
						wizard.documents.length}</b></div>
					   <div class="sum-row"><span>Still missing</span><b class="${
						missing.length ? "warn-red" : "good"}">${missing.length}</b></div>
					   ${missing.length ? `<p class="emi-hint">${esc(missing.map((row) =>
						row.document_type).join(", "))}</p>` : ""}`
					: '<p class="emi-hint">Save the draft to raise the checklist.</p>'}
			</div>
		</div>
		<p class="emi-hint">Submitting records the application as sent to the financier. Its answer
			— approved or rejected, with the reference it gives — is recorded separately, because
			the financier decides, not this page.</p>`;
	};

	function wizardMessage(text, kind) {
		$("wizard-msg").textContent = A3.plain(text);
		$("wizard-msg").className = "msg" + (kind ? " " + kind : "");
	}

	function collectWizard() {
		const wizard = state.wizard;
		if (wizard.step === 0 || $("z-mobile")) {
			wizard.mobile = ($("z-mobile") || {}).value || wizard.mobile;
			wizard.customer_name = ($("z-name") || {}).value || wizard.customer_name;
			wizard.email = ($("z-email") || {}).value || wizard.email;
			wizard.employment = ($("z-employment") || {}).value || wizard.employment;
			wizard.income = Number(($("z-income") || {}).value) || wizard.income;
			wizard.dob = ($("z-dob") || {}).value || wizard.dob;
			wizard.pan = ($("z-pan") || {}).value || wizard.pan;
			wizard.aadhaar = ($("z-aadhaar") || {}).value || wizard.aadhaar;
			wizard.existing = ($("z-existing") || {}).value || wizard.existing;
		}
		if ($("z-total")) wizard.total = Number($("z-total").value) || wizard.total;
		if ($("z-down")) wizard.down_payment = Number($("z-down").value) || 0;
	}

	async function saveDraft(quiet) {
		collectWizard();
		const wizard = state.wizard;
		const quote = wizard.quote || {};

		try {
			const result = await A3.call("a3_retail.api.emi.save_application", {
				payload: {
					name: wizard.name,
					customer: wizard.customer,
					mobile_no: wizard.mobile,
					customer_name: wizard.customer_name,
					email: wizard.email,
					date_of_birth: wizard.dob || null,
					employment_type: wizard.employment,
					monthly_income: wizard.income,
					pan: wizard.pan,
					aadhaar_last4: wizard.aadhaar,
					existing_loan_account: wizard.existing,
					sales_invoice: wizard.invoice,
					items: wizard.items,
					invoice_total: wizard.total,
					partner: wizard.partner,
					scheme: wizard.scheme,
					down_payment: wizard.down_payment,
					processing_fee: quote.processing_fee_amount,
					documentation_fee: quote.documentation_fee,
				},
			});

			wizard.name = result.application;
			const full = await A3.call("a3_retail.api.emi.application", { name: wizard.name });
			wizard.documents = full.documents;

			if (!quiet) {
				toast(`${result.application} saved as a draft.`, "ok");
				loadHead();
				loadTab();
			}
			return result;
		} catch (error) {
			wizardMessage(error.message, "error");
			throw error;
		}
	}

	async function wizardNext() {
		const wizard = state.wizard;
		collectWizard();

		if (wizard.step === 0 && !wizard.customer && !wizard.mobile) {
			return wizardMessage("A financing application needs the customer's mobile number.",
				"error");
		}
		if (wizard.step === 0 && (!wizard.pan || !wizard.aadhaar || !wizard.employment)) {
			return wizardMessage("Every financier asks what the customer does for a living, their "
				+ "PAN and the last four digits of their Aadhaar. Fill those in before going on.",
				"error");
		}
		if (wizard.step === 1 && !wizard.total) {
			return wizardMessage("Load the invoice, or type what the purchase comes to.", "error");
		}
		if (wizard.step === 2 && !wizard.partner) {
			return wizardMessage("Pick the financier this application goes to.", "error");
		}
		if (wizard.step === 3 && !wizard.scheme) {
			return wizardMessage("Pick the scheme the customer is taking.", "error");
		}

		// Saving at the contribution step is what raises the checklist, which is
		// the next thing the counter needs to fill in.
		if (wizard.step === 4) {
			try {
				await saveDraft(true);
			} catch (error) {
				return;
			}
		}

		if (wizard.step === STEPS.length - 1) return submitWizard();

		wizard.step += 1;
		paintWizard();
	}

	async function submitWizard() {
		try {
			await saveDraft(true);
			const result = await A3.call("a3_retail.api.emi.submit_application",
				{ name: state.wizard.name });
			$("wizard-modal").hidden = true;
			toast(`${result.application} is with ${state.wizard.partner}.`, "ok");
			loadHead();
			loadTab();
			openApplication(result.application);
		} catch (error) {
			wizardMessage(error.message, "error");
		}
	}

	// ================================================================= start
	async function refreshBoot() {
		state.boot = await A3.call("a3_retail.api.emi.bootstrap", {});
		state.boot.payment_modes = state.boot.partners
			.map((row) => row.mode_of_payment).filter(Boolean);

		$("partner").innerHTML = '<option value="">All</option>'
			+ state.boot.partners.map((row) =>
				`<option value="${esc(row.name)}">${esc(row.partner_name || row.name)}</option>`).join("");
		$("scheme").innerHTML = '<option value="">All</option>'
			+ state.boot.schemes.map((row) =>
				`<option value="${esc(row.name)}">${esc(row.scheme_name)}</option>`).join("");
		$("status").innerHTML = '<option value="all">All</option>'
			+ '<option value="open">Still open</option>'
			+ '<option value="pending">Waiting on the financier</option>'
			+ state.boot.statuses.map((status) =>
				`<option value="${esc(status)}">${esc(status)}</option>`).join("");
		$("sales-person").innerHTML = '<option value="">Anyone</option>'
			+ state.boot.sales_people.map((person) =>
				`<option value="${esc(person)}">${esc(person)}</option>`).join("");
		$("item-group").innerHTML = '<option value="">All</option>'
			+ state.boot.item_groups.map((group) =>
				`<option value="${esc(group)}">${esc(group)}</option>`).join("");

		$("new-partner").hidden = !state.boot.can.partner;
		$("new-scheme").hidden = !state.boot.can.scheme;
		$("new-application").hidden = !state.boot.can.apply;
	}

	async function start(options) {
		state.branch = options.branch;
		state.company = options.company;
		state.opening = options;
		state.filters = { ...BLANK };
		state.tab = options.tab || "overview";

		try {
			await refreshBoot();
		} catch (error) {
			$("tab-body").innerHTML = `<section class="svc-panel rep-empty">
				<b>The financing desk could not start</b><span>${esc(error.message)}</span></section>`;
			return;
		}

		let searchTimer;
		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				state.page = 1;
				loadTab();
			}, 220);
		});

		[["from-date", "from_date"], ["to-date", "to_date"], ["partner", "partner"],
		 ["scheme", "scheme"], ["status", "status"], ["branch", "branch"],
		 ["sales-person", "sales_person"], ["item-group", "item_group"]].forEach(([id, key]) => {
			$(id).addEventListener("change", () => {
				state.filters[key] = $(id).value;
				state.page = 1;
				loadHead();
				loadTab();
			});
		});

		$("clear").addEventListener("click", () => {
			state.filters = { ...BLANK };
			["q", "from-date", "to-date"].forEach((id) => { $(id).value = ""; });
			["partner", "scheme", "sales-person", "item-group"].forEach((id) => { $(id).value = ""; });
			$("status").value = "all";
			$("branch").value = "current";
			state.page = 1;
			load();
		});

		document.querySelectorAll("#tabs .tab").forEach((node) => {
			node.addEventListener("click", () => setTab(node.dataset.tab));
		});
		document.body.addEventListener("click", (event) => {
			const goer = event.target.closest("[data-go-tab]");
			if (goer) setTab(goer.dataset.goTab);
		});

		$("new-application").addEventListener("click", () => openWizard(null));
		$("new-partner").addEventListener("click", () => partnerForm(null));
		$("new-scheme").addEventListener("click", () => schemeForm(null));
		$("more").addEventListener("click", () => {
			openWork("More", "", `<ul class="simple-list">
				<li><button class="linkish" data-do="calc">EMI calculator</button></li>
				<li><button class="linkish" data-do="export">Export this list</button></li>
				<li><a class="linkish" href="/branch/reports?category=Finance%20%26%20EMI">
					EMI reports</a></li>
			</ul>`);
			$("work-body").querySelectorAll("[data-do]").forEach((node) => {
				node.addEventListener("click", () => {
					$("work-modal").hidden = true;
					if (node.dataset.do === "calc") calculator();
					if (node.dataset.do === "export") exportCsv();
				});
			});
		});

		$("wizard-next").addEventListener("click", wizardNext);
		$("wizard-back").addEventListener("click", () => {
			state.wizard.step = Math.max(state.wizard.step - 1, 0);
			paintWizard();
		});
		$("wizard-draft").addEventListener("click", () => saveDraft(false).catch(() => {}));

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((modal) => { modal.hidden = true; });
			}
		});

		setTab(state.tab);
		loadHead();

		if (options.application) openApplication(options.application);
		else if (options.invoice || options.customer) openWizard(null);
	}

	function exportCsv() {
		if (!state.rows.length) return toast("Nothing on this tab to export.", "error");
		const keys = Object.keys(state.rows[0]).filter((key) =>
			typeof state.rows[0][key] !== "object");
		const body = state.rows.map((row) => keys.map((key) =>
			`"${String(row[key] == null ? "" : row[key]).replace(/"/g, '""')}"`).join(","));
		const url = URL.createObjectURL(
			new Blob([keys.join(",") + "\n" + body.join("\n")], { type: "text/csv" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = `emi-${state.tab}.csv`;
		link.click();
		URL.revokeObjectURL(url);
		toast(`Exported ${state.rows.length} rows.`, "ok");
	}

	return { start, state };
})();
