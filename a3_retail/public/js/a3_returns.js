// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Sales returns — the credit notes this branch has raised.
 *
 * A list, like Bills. Raising one is the rare act and has a page of its own;
 * reading back what came back is the daily one, so it gets the screen. Nothing
 * here writes: a credit note is raised at /retail/return_entry and printed
 * through the same print link every other document uses.
 */

(function () {
	const state = {
		page: 1, pageSize: 20, rows: [],
		filters: { query: "", from_date: "", to_date: "", settled: "all",
		           show_cancelled: 0 },
	};
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);

	function esc(value) {
		// `"` and `'` as well: almost every use of this is inside an attribute,
		// and a name like `APPLE IPAD A16 "11"` would otherwise close it early.
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
	}

	const day = (value) => !value ? "—" : new Date(value + "T00:00:00")
		.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

	function icon(name) {
		const paths = {
			eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			back: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			wallet: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><circle cx="17" cy="14" r="1.3"/>',
			calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	const settledTone = (status) =>
		({ "Refunded": "pill-good", "On account": "pill-sky",
		   "Part refunded": "pill-warn" }[status] || "pill-sky");
	const docTone = (status) =>
		({ "Cancelled": "pill-bad", "Draft": "pill-sky" }[status] || "pill-good");

	// ------------------------------------------------------------- loading
	function skeleton() {
		$("rows").innerHTML = Array.from({ length: 6 }, () =>
			'<tr class="is-loading">' + "<td>&nbsp;</td>".repeat(12) + "</tr>").join("");
	}

	async function load(page) {
		state.page = page || state.page;
		skeleton();
		try {
			const [tiles, data] = await Promise.all([
				A3.call("a3_retail.api.returns.summary", { filters: state.filters }),
				A3.call("a3_retail.api.returns.recent",
				        { filters: state.filters, page: state.page, limit: state.pageSize }),
			]);
			state.rows = data.rows || [];
			paintTiles(tiles);
			paintRows(data);
		} catch (error) {
			$("rows").innerHTML =
				`<tr><td colspan="12">${esc(error.message || "Could not load returns.")}</td></tr>`;
		}
	}

	function paintTiles(tiles) {
		const card = (key, label, tone, glyph, sub) => {
			const box = tiles[key] || { count: 0, amount: 0 };
			return `<div class="ctile bill-tile">
				<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
					<span class="ctile-label">${esc(label)}</span></div>
				<div class="ctile-value">${esc(money(box.amount))}</div>
				<div class="ctile-sub">${box.count} ${esc(sub)}${box.count === 1 ? "" : "s"}</div>
			</div>`;
		};
		$("tiles").innerHTML =
			card("total", "Came back", "sky", "back", "note")
			+ card("refunded", "Refunded", "good", "cash", "note")
			+ card("on_account", "On account", "warn", "wallet", "note")
			+ card("month", "This month", "neutral", "calendar", "note");
	}

	function paintRows(data) {
		const rows = state.rows;
		$("showing").textContent = data.total
			? `Showing ${data.showing[0]}–${data.showing[1]} of `
			  + `${data.total.toLocaleString("en-IN")} credit notes`
			: "No credit notes";

		if (!rows.length) {
			$("rows").innerHTML = `<tr><td colspan="12" class="bill-empty">
				Nothing has come back yet. Raise one with <b>+ New Return</b>.</td></tr>`;
			paintPager(data);
			return;
		}

		$("rows").innerHTML = rows.map((row) => `
			<tr data-name="${esc(row.name)}"${row.status === "Cancelled" ? ' class="is-cancelled"' : ""}>
				<td class="nowrap"><a class="bill-no"
				   href="/retail/invoice?name=${encodeURIComponent(row.name)}">${esc(row.name)}</a></td>
				<td class="nowrap">${esc(day(row.posting_date))}</td>
				<td>${esc(row.customer_name || "—")}
					${row.contact_mobile ? `<small class="muted">${esc(row.contact_mobile)}</small>` : ""}</td>
				<td class="nowrap">${row.return_against
					? `<a class="bill-no" href="/retail/invoice?name=${
						encodeURIComponent(row.return_against)}">${esc(row.return_against)}</a>`
					: "—"}</td>
				<td class="ret-items" title="${esc(row.items || "")}">${esc(row.items || "—")}
					${row.line_count > 1 ? `<small class="muted">${row.line_count} lines</small>` : ""}</td>
				<td class="num">${esc(money(row.amount))}</td>
				<td class="num">${row.refunded > 0.005 ? esc(money(row.refunded)) : "—"}</td>
				<td class="num ${row.on_account > 0.005 ? "warn-amber" : ""}">${
					row.on_account > 0.005 ? esc(money(row.on_account)) : "—"}</td>
				<td><span class="pill ${settledTone(row.status)}">${esc(row.status)}</span></td>
				<td><span class="pill ${docTone(row.status)}">${
					row.status === "Cancelled" ? "Cancelled"
						: row.status === "Draft" ? "Draft" : "Submitted"}</span></td>
				<td class="nowrap">${esc(row.sold_by || "—")}</td>
				<td class="bill-actions">
					<a class="icon-btn plain" title="View"
					   href="/retail/invoice?name=${encodeURIComponent(row.name)}">${icon("eye")}</a>
					<button class="icon-btn plain" data-act="print" title="Print">${icon("print")}</button>
				</td>
			</tr>`).join("");

		$("rows").querySelectorAll("[data-act='print']").forEach((node) => {
			node.addEventListener("click", async () => {
				const name = node.closest("tr").dataset.name;
				try {
					const url = await A3.call("a3_retail.api.stock_control.print_url",
					                          { doctype: "Sales Invoice", name });
					window.open(url, "_blank");
				} catch (error) { toast(error.message, "error"); }
			});
		});
		paintPager(data);
	}

	function paintPager(data) {
		const pages = data.pages || 1;
		const here = data.page || 1;
		const numbers = [];
		for (let n = 1; n <= pages; n += 1) {
			if (n <= 2 || n === pages || Math.abs(n - here) <= 1) numbers.push(n);
			else if (numbers[numbers.length - 1] !== "…") numbers.push("…");
		}
		$("pager").innerHTML =
			`<button class="page-btn" data-go="${here - 1}" ${here <= 1 ? "disabled" : ""}>Previous</button>`
			+ numbers.map((n) => n === "…"
				? '<span class="page-gap">…</span>'
				: `<button class="page-btn ${n === here ? "is-active" : ""}" data-go="${n}">${n}</button>`).join("")
			+ `<button class="page-btn" data-go="${here + 1}" ${here >= pages ? "disabled" : ""}>Next</button>`;
		$("pager").querySelectorAll("[data-go]").forEach((node) =>
			node.addEventListener("click", () => load(Number(node.dataset.go))));
	}

	function toast(text, kind) {
		const box = $("toast");
		box.textContent = A3.plain(text);
		box.className = "toast" + (kind ? " " + kind : "");
		box.hidden = false;
		setTimeout(() => { box.hidden = true; }, 3200);
	}

	function exportCsv() {
		const head = ["Credit note", "Date", "Customer", "Phone", "Against", "Items",
		              "Amount", "Refunded", "On account", "Settled", "Handled by"];
		const lines = state.rows.map((r) => [r.name, r.posting_date, r.customer_name,
			r.contact_mobile, r.return_against, r.items, r.amount, r.refunded,
			r.on_account, r.status, r.sold_by]);
		const csv = [head, ...lines]
			.map((cells) => cells.map((c) => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(","))
			.join("\n");
		const link = document.createElement("a");
		link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
		link.download = `sales-returns-${new Date().toLocaleDateString("en-CA")}.csv`;
		link.click();
	}

	// --------------------------------------------------------------- start
	document.addEventListener("DOMContentLoaded", () => {
		let timer = null;
		$("q").addEventListener("input", () => {
			clearTimeout(timer);
			timer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				load(1);
			}, 220);
		});
		[["from-date", "from_date"], ["to-date", "to_date"], ["settled", "settled"]]
			.forEach(([id, key]) => {
				$(id).addEventListener("change", () => {
					state.filters[key] = $(id).value;
					load(1);
				});
			});
		$("show-cancelled").addEventListener("change", () => {
			state.filters.show_cancelled = $("show-cancelled").checked ? 1 : 0;
			load(1);
		});
		$("clear").addEventListener("click", () => {
			state.filters = { query: "", from_date: "", to_date: "", settled: "all",
			                  show_cancelled: 0 };
			$("q").value = "";
			["from-date", "to-date"].forEach((id) => {
				$(id).value = "";
				$(id).dispatchEvent(new Event("change", { bubbles: false }));
			});
			$("settled").value = "all";
			$("show-cancelled").checked = false;
			load(1);
		});
		$("page-size").addEventListener("change", () => {
			state.pageSize = Number($("page-size").value);
			load(1);
		});
		$("filter-toggle").addEventListener("click", () =>
			$("filter-row").classList.toggle("is-open"));
		$("refresh").addEventListener("click", () => load(state.page));
		$("export").addEventListener("click", exportCsv);

		load(1);
	});
})();
