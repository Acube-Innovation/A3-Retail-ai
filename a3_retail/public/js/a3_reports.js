// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Reports — one page, two states.
 *
 * The catalogue and the report live on the same screen: pick one and the page
 * becomes that report, Back turns it into the catalogue again. Nothing is
 * hardcoded per report — the filters come from the report's own definition, the
 * columns and rows from the ERP's own SQL, and one print routine renders
 * whatever is on screen. A new report in the app appears here on its own.
 *
 * Read-only, all the way through. There is nothing on this page that writes.
 */

window.REPORTS = (function () {
	const state = {
		branch: "", company: "", who: "",
		catalogue: null, category: "all", scope: "all", query: "",
		report: null, definition: null, filters: {}, result: null,
	};
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);
	const number = (value) => new Intl.NumberFormat("en-IN").format(value || 0);

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
		setTimeout(() => box.remove(), 3600);
	}

	function icon(name) {
		const paths = {
			tag: '<path d="M3 12V5a2 2 0 0 1 2-2h7l9 9-9 9-9-9z"/><circle cx="7.5" cy="7.5" r="1.4"/>',
			wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 21H10L4.3 15.3a4 4 0 0 1 5-5z"/><path d="M9 9l6 6"/>',
			users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.5a3 3 0 0 1 0 5.6M17 14.4a5.5 5.5 0 0 1 4 5.6"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
			shield: '<path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="m9 12 2 2 4-4"/>',
			truck: '<rect x="2" y="7" width="12" height="9" rx="2"/><path d="M14 10h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>',
			chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
			grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
			star: '<path d="m12 3 2.7 5.6 6.3.9-4.5 4.4 1 6.1-5.5-2.9-5.5 2.9 1-6.1L3 9.5l6.3-.9z"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	const TONES = { sales: "sky", service: "good", customers: "sky", payments: "warn",
	                inventory: "sky", warranty: "good", delivery: "sky", financial: "warn",
	                people: "sky" };

	// ----------------------------------------------------------- catalogue
	async function loadCatalogue() {
		$("list").innerHTML = '<div class="pos-loading">Loading the reports…</div>';
		state.catalogue = await A3.call("a3_retail.api.reports.catalogue", {});

		$("cats").innerHTML = state.catalogue.categories.filter((cat) => cat.count).map((cat) => `
			<button class="ctile rep-cat ${cat.key === state.category ? "is-active" : ""}"
			        data-cat="${esc(cat.key)}">
				<div class="ctile-head"><span class="ctile-ico ${TONES[cat.key] || "sky"}">${
					icon(cat.icon)}</span>
					<span class="ctile-label">${esc(cat.label)}</span></div>
				<div class="ctile-value">${cat.count}</div>
				<div class="ctile-sub">${cat.count === 1 ? "report" : "reports"}</div>
				<div class="rep-cat-note">${esc(cat.description)}</div>
			</button>`).join("");

		$("category").innerHTML = '<option value="all">All categories</option>'
			+ state.catalogue.categories.filter((cat) => cat.count).map((cat) =>
				`<option value="${esc(cat.key)}">${esc(cat.label)}</option>`).join("");
		$("category").value = state.category;

		$("cats").querySelectorAll(".rep-cat").forEach((node) => {
			node.addEventListener("click", () => {
				state.category = state.category === node.dataset.cat ? "all" : node.dataset.cat;
				$("category").value = state.category;
				paintList();
			});
		});

		paintList();
	}

	function paintList() {
		$("cats").querySelectorAll(".rep-cat").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.cat === state.category);
		});

		const query = state.query.toLowerCase();
		let rows = state.catalogue.reports.filter((report) => {
			if (state.category !== "all" && report.category !== state.category) return false;
			if (state.scope === "favourites" && !report.favourite) return false;
			if (!query) return true;
			return (report.name + " " + report.description).toLowerCase().indexOf(query) !== -1;
		});
		rows = rows.slice().sort((a, b) => (b.favourite ? 1 : 0) - (a.favourite ? 1 : 0)
			|| a.name.localeCompare(b.name));

		if (!rows.length) {
			$("list").innerHTML = `<div class="svc-panel rep-empty">
				<b>No reports found</b>
				<span>Try changing the category or the search.</span></div>`;
			return;
		}

		const labels = {};
		state.catalogue.categories.forEach((cat) => { labels[cat.key] = cat.label; });

		$("list").innerHTML = rows.map((report) => `
			<article class="rep-card" data-name="${esc(report.name)}">
				<button class="rep-star ${report.favourite ? "is-on" : ""}"
				        data-star="${esc(report.name)}" title="Favourite">${icon("star")}</button>
				<h3>${esc(report.name)}</h3>
				<p>${esc(report.description)}</p>
				<div class="rep-card-foot">
					<span class="pill pill-sky">${esc(labels[report.category] || report.category)}</span>
					<span class="rep-when">${report.last_run
						? "Last run " + esc(day(report.last_run)) : "Not run yet"}</span>
					<button class="btn btn-outline btn-sm" data-open="${esc(report.name)}">View Report</button>
				</div>
			</article>`).join("");

		$("list").querySelectorAll("[data-open]").forEach((node) => {
			node.addEventListener("click", () => openReport(node.dataset.open));
		});
		$("list").querySelectorAll("[data-star]").forEach((node) => {
			node.addEventListener("click", async (event) => {
				event.stopPropagation();
				const result = await A3.call("a3_retail.api.reports.toggle_favourite",
					{ report: node.dataset.star });
				const report = state.catalogue.reports.find((r) => r.name === node.dataset.star);
				report.favourite = result.favourite;
				paintList();
			});
		});
		$("list").querySelectorAll(".rep-card h3").forEach((node) => {
			node.addEventListener("click", () => openReport(node.closest(".rep-card").dataset.name));
		});
	}

	// -------------------------------------------------------- one report
	async function openReport(name) {
		state.report = name;
		state.definition = await A3.call("a3_retail.api.reports.definition", { report: name });
		state.filters = {};
		(state.definition.filters || []).forEach((filter) => {
			if (filter.default) state.filters[filter.fieldname] = filter.default;
		});
		if (state.definition.branch_locked) state.filters.branch = state.definition.branch;

		$("catalogue").hidden = true;
		$("viewer").hidden = false;
		$("back").hidden = false;
		$("print").hidden = false;
		$("export").hidden = false;
		$("title").textContent = name;
		$("subtitle").textContent = state.definition.description || "";
		history.replaceState({}, "", "/retail/reports?report=" + encodeURIComponent(name));

		paintFilters();
		runReport();
	}

	function backToCatalogue() {
		state.report = null;
		$("catalogue").hidden = false;
		$("viewer").hidden = true;
		$("back").hidden = true;
		$("print").hidden = true;
		$("export").hidden = true;
		$("title").textContent = "Reports";
		$("subtitle").textContent = "Business insights and operational reports";
		history.replaceState({}, "", "/retail/reports");
		paintList();
	}

	function paintFilters() {
		const filters = state.definition.filters || [];
		$("rep-filters").innerHTML = filters.map((filter) => {
			const value = state.filters[filter.fieldname] || "";
			if (filter.fieldtype === "Select") {
				const options = (filter.options || "").split("\n").filter(Boolean);
				return `<label class="field"><span>${esc(filter.label)}</span>
					<select data-filter="${esc(filter.fieldname)}">
						<option value="">All</option>
						${options.map((option) => `<option value="${esc(option)}"${
							option === value ? " selected" : ""}>${esc(option)}</option>`).join("")}
					</select></label>`;
			}
			const type = filter.fieldtype === "Date" ? "date"
				: (filter.fieldtype === "Int" || filter.fieldtype === "Float") ? "number" : "text";
			const locked = filter.fieldname === "branch" && state.definition.branch_locked;
			return `<label class="field"><span>${esc(filter.label)}</span>
				<input type="${type}" data-filter="${esc(filter.fieldname)}"
				       value="${esc(locked ? state.definition.branch : value)}"
				       ${locked ? "disabled title=\"You see your own branch\"" : ""}
				       placeholder="${filter.fieldtype === "Link" ? "Any " + esc(filter.options || "") : ""}">
				</label>`;
		}).join("") || '<div class="cust-none">This report takes no filters.</div>';

		$("rep-filters").querySelectorAll("[data-filter]").forEach((node) => {
			node.addEventListener("change", () => {
				state.filters[node.dataset.filter] = node.value;
			});
		});
	}

	async function runReport() {
		$("kpis").innerHTML = "";
		$("chart").innerHTML = "";
		$("table-wrap").innerHTML = '<div class="pos-loading">Running the report…</div>';
		$("table-foot").innerHTML = "";

		try {
			state.result = await A3.call("a3_retail.api.reports.run",
				{ report: state.report, filters: state.filters });
			paintResult();
		} catch (error) {
			$("table-wrap").innerHTML = `<div class="rep-empty"><b>Could not run this report</b>
				<span>${esc(error.message)}</span></div>`;
		}
	}

	function paintResult() {
		const result = state.result;

		$("rep-head").innerHTML = `
			<div class="rep-head-main">
				<span class="ctile-ico ${TONES[state.definition.category] || "sky"}">${
					icon((state.catalogue && (state.catalogue.categories
						.find((c) => c.key === state.definition.category) || {}).icon) || "chart")}</span>
				<div>
					<h2>${esc(result.report)}</h2>
					<p>${esc(state.definition.description || "")}</p>
				</div>
			</div>
			<dl class="rep-meta">
				${metaRow("Report Period", periodLabel())}
				${metaRow("Branch", result.branch || "All branches")}
				${metaRow("Generated", esc(result.generated_on))}
				${metaRow("Generated By", esc(result.generated_by))}
			</dl>`;

		$("kpis").innerHTML = result.kpis.map((kpi) => `
			<div class="ctile">
				<div class="ctile-label">${esc(kpi.label)}</div>
				<div class="ctile-value">${kpi.fieldtype === "Currency"
					? money(kpi.value) : number(kpi.value)}</div>
			</div>`).join("");

		$("chart").innerHTML = result.chart ? chartMarkup(result.chart) : "";

		if (!result.rows.length) {
			$("table-wrap").innerHTML = `<div class="rep-empty"><b>No data available</b>
				<span>Try changing the selected filters or date range.</span></div>`;
			$("table-foot").innerHTML = "";
			return;
		}

		$("table-wrap").innerHTML = tableMarkup(result);
		$("table-foot").innerHTML =
			`<span>${number(result.row_count)} ${result.row_count === 1 ? "row" : "rows"}</span>`;
	}

	function metaRow(label, value) {
		return `<div><dt>${label}</dt><dd>${value}</dd></div>`;
	}

	function periodLabel() {
		const from = state.filters.from_date;
		const to = state.filters.to_date;
		if (from && to) return `${esc(day(from))} – ${esc(day(to))}`;
		if (to) return "Up to " + esc(day(to));
		return "Everything on record";
	}

	function cell(row, column) {
		const value = row[column.fieldname];
		if (value == null || value === "") return "—";
		if (column.fieldtype === "Currency") return money(value);
		if (column.fieldtype === "Percent") return Number(value).toFixed(1) + "%";
		if (column.fieldtype === "Int" || column.fieldtype === "Float") return number(value);
		if (column.fieldtype === "Date") return esc(day(value));
		return esc(value);
	}

	function isNumeric(column) {
		return ["Currency", "Float", "Int", "Percent"].indexOf(column.fieldtype) !== -1;
	}

	function tableMarkup(result) {
		const columns = result.columns;
		return `<table class="bill-table rep-table">
			<thead><tr>${columns.map((column) =>
				`<th class="${isNumeric(column) ? "num" : ""}">${esc(column.label)}</th>`).join("")}</tr></thead>
			<tbody>${result.rows.map((row) => `<tr>${columns.map((column) =>
				`<td class="${isNumeric(column) ? "num" : ""}">${cell(row, column)}</td>`).join("")}</tr>`).join("")}
			</tbody>
			<tfoot><tr>
				${columns.map((column, index) => {
					if (index === 0) return '<td class="rep-total-label">Total</td>';
					const total = result.totals[column.fieldname];
					return `<td class="${isNumeric(column) ? "num" : ""}">${
						total == null ? "" : (column.fieldtype === "Currency"
							? money(total) : number(total))}</td>`;
				}).join("")}
			</tr></tfoot>
		</table>`;
	}

	/** A small inline chart — no library, and only where the data has a shape. */
	function chartMarkup(chart) {
		const width = 900;
		const height = 150;
		const points = chart.points;
		const top = Math.max(...points.map((point) => point.value)) || 1;
		const step = points.length > 1 ? width / (points.length - 1) : width;

		const body = chart.kind === "line"
			? `<polyline fill="none" stroke="#1c6ef2" stroke-width="2"
				points="${points.map((point, index) =>
					`${index * step},${height - (point.value / top) * (height - 20)}`).join(" ")}"/>`
			: points.map((point, index) => {
				const barWidth = Math.max(width / points.length - 6, 4);
				const barHeight = (point.value / top) * (height - 20);
				return `<rect x="${index * (width / points.length)}" y="${height - barHeight}"
					width="${barWidth}" height="${barHeight}" rx="3" fill="#1c6ef2" opacity=".85"/>`;
			}).join("");

		return `<div class="svc-panel rep-chart">
			<div class="panel-head"><h2>${esc(chart.label)}</h2>
				<span class="rep-when">Peak ${money(top)}</span></div>
			<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" class="rep-svg">${body}</svg>
			<div class="rep-axis"><span>${esc(points[0].label)}</span>
				<span>${esc(points[points.length - 1].label)}</span></div>
		</div>`;
	}

	// ---------------------------------------------------------------- print
	/** One print routine for every report: whatever is on screen, on paper.
	 *  Landscape once the table is too wide for portrait to hold it. */
	function printReport() {
		const result = state.result;
		if (!result || !result.rows.length) return toast("Nothing to print yet.", "error");

		const landscape = result.columns.length > 6;
		const applied = (state.definition.filters || [])
			.filter((filter) => state.filters[filter.fieldname])
			.map((filter) => `${filter.label}: ${state.filters[filter.fieldname]}`)
			.join(" · ");

		const win = window.open("", "_blank");
		win.document.write(`<!doctype html>
			<title>${esc(result.report)}</title>
			<style>
				@page { size: A4 ${landscape ? "landscape" : "portrait"}; margin: 12mm; }
				body { font: 11px/1.5 "Plus Jakarta Sans", system-ui, sans-serif; color: #2a3342; }
				.brand { display: flex; justify-content: space-between; align-items: flex-start;
					border-bottom: 1px solid #d9dee7; padding-bottom: 10px; margin-bottom: 12px; }
				.brand h1 { margin: 0; font-size: 17px; }
				.brand .sub { font-size: 9px; letter-spacing: .12em; color: #8b93a1; }
				.meta { text-align: right; font-size: 10px; color: #5b6472; }
				h2 { margin: 0 0 2px; font-size: 15px; }
				.desc { margin: 0 0 10px; color: #5b6472; }
				.kpis { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
				.kpi { border: 1px solid #e6e9ef; border-radius: 6px; padding: 6px 10px; min-width: 110px; }
				.kpi b { display: block; font-size: 13px; }
				.kpi span { font-size: 9px; color: #8b93a1; text-transform: uppercase;
					letter-spacing: .06em; }
				table { width: 100%; border-collapse: collapse; }
				th, td { padding: 5px 6px; border-bottom: 1px solid #eceff4; text-align: left; }
				th { background: #f6f8fb; font-size: 9.5px; text-transform: uppercase;
					letter-spacing: .05em; color: #5b6472; }
				td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
				tfoot td { font-weight: 700; border-top: 1.5px solid #2a3342; border-bottom: 0; }
				tfoot { display: table-footer-group; }
				thead { display: table-header-group; }
				.foot { margin-top: 14px; padding-top: 8px; border-top: 1px solid #e6e9ef;
					font-size: 9px; color: #8b93a1; display: flex; justify-content: space-between; }
			</style>
			<div class="brand">
				<div><h1>A3 Retail</h1><div class="sub">BY ACUBE INNOVATIONS</div>
					<div>${esc(state.company || "")}</div></div>
				<div class="meta">
					<div><b>Branch:</b> ${esc(result.branch || "All branches")}</div>
					<div><b>Generated:</b> ${esc(result.generated_on)}</div>
					<div><b>By:</b> ${esc(result.generated_by)}</div>
				</div>
			</div>
			<h2>${esc(result.report)}</h2>
			<p class="desc">${esc(state.definition.description || "")}<br>
				<b>Period:</b> ${periodLabel()}${applied ? ` &nbsp;·&nbsp; ${esc(applied)}` : ""}</p>
			<div class="kpis">${result.kpis.map((kpi) => `<div class="kpi">
				<b>${kpi.fieldtype === "Currency" ? money(kpi.value) : number(kpi.value)}</b>
				<span>${esc(kpi.label)}</span></div>`).join("")}</div>
			${tableMarkup(result)}
			<div class="foot"><span>A3 Retail · ${esc(result.report)}</span>
				<span>${esc(result.generated_on)}</span></div>`);
		win.document.close();
		win.focus();
		win.print();
	}

	function exportCsv() {
		const result = state.result;
		if (!result || !result.rows.length) return toast("Nothing to export yet.", "error");

		const head = result.columns.map((column) => `"${column.label}"`).join(",") + "\n";
		const body = result.rows.map((row) => result.columns.map((column) =>
			`"${String(row[column.fieldname] == null ? "" : row[column.fieldname])
				.replace(/"/g, '""')}"`).join(",")).join("\n");

		const url = URL.createObjectURL(new Blob([head + body], { type: "text/csv" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = frappeSlug(result.report) + ".csv";
		link.click();
		URL.revokeObjectURL(url);
		toast("Exported " + result.row_count + " rows.", "ok");
	}

	function frappeSlug(name) {
		return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
	}

	// --------------------------------------------------------------- start
	let searchTimer;
	async function start(options) {
		state.branch = options.branch;
		state.company = options.company;
		state.who = options.who;

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => { state.query = $("q").value.trim(); paintList(); }, 180);
		});
		$("category").addEventListener("change", () => {
			state.category = $("category").value;
			paintList();
		});
		$("scope").addEventListener("change", () => {
			state.scope = $("scope").value;
			paintList();
		});
		$("clear").addEventListener("click", () => {
			state.query = ""; state.category = "all"; state.scope = "all";
			$("q").value = ""; $("category").value = "all"; $("scope").value = "all";
			paintList();
		});

		$("back").addEventListener("click", backToCatalogue);
		$("print").addEventListener("click", printReport);
		$("export").addEventListener("click", exportCsv);
		$("apply").addEventListener("click", runReport);
		$("reset").addEventListener("click", () => {
			state.filters = {};
			(state.definition.filters || []).forEach((filter) => {
				if (filter.default) state.filters[filter.fieldname] = filter.default;
			});
			if (state.definition.branch_locked) state.filters.branch = state.definition.branch;
			paintFilters();
			runReport();
		});
		$("refresh").addEventListener("click", () => {
			if (state.report) { runReport(); toast("Refreshed."); }
			else loadCatalogue();
		});

		await loadCatalogue();
		if (options.report) openReport(options.report);
	}

	return { start, state };
})();
