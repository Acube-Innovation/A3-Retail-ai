// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Sales returns — the credit notes this branch has raised.
 *
 * A list, like Bills, with raising one behind a sheet over it: finding the
 * bill and saying what is coming back is a short errand, and the counter
 * should land back on the list it started from rather than on another page.
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
	// The sheet works in paise: a counter handing cash back has to see the
	// figure it is handing back, not a rounded one.
	const money2 = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2,
			maximumFractionDigits: 2 }).format(value || 0);

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

	// ---------------------------------------------------- raising one
	const sheet = { bill: null, lines: [], saving: false };
	let billTimer = null;

	function note(text, kind) {
		$("work-msg").textContent = A3.plain(text || "");
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------- the bill
	async function findBills() {
		const q = $("bill-q").value.trim();
		if (q.length < 2) return ($("bill-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.returns.find_bills", { query: q, limit: 8 });
		$("bill-hits").innerHTML = hits.length
			? hits.map((b) => `<button class="pick ret-hit" data-name="${esc(b.name)}">
				<span class="ret-hit-no">${esc(b.name)}</span>
				<span class="ret-hit-who">${esc(b.customer_name)}</span>
				<span class="ret-hit-when">${esc(day(b.posting_date))}</span>
				<span class="ret-hit-amt">${esc(money2(b.payable))}</span></button>`).join("")
			: '<p class="muted ret-none">No bill of this branch matches that.</p>';
	}

	async function pickBill(name) {
		$("bill-hits").innerHTML = "";
		try {
			const data = await A3.call("a3_retail.api.returns.bill_lines", { invoice: name });
			sheet.bill = data;
			sheet.lines = data.lines.map((l) => ({ ...l, returning: 0 }));
			$("bill-q").value = "";
			$("bill-picked").hidden = false;
			$("bill-picked").innerHTML = `
				<div class="ret-picked-main">
					<b>${esc(data.invoice)}</b>
					<span>${esc(data.customer_name)} · ${esc(day(data.posting_date))}</span>
				</div>
				<div class="ret-picked-amt">${esc(money2(data.payable))}</div>
				<button class="btn btn-quiet btn-sm" id="bill-clear">Change bill</button>`;
			$("bill-clear").addEventListener("click", reset);
			$("lines-panel").hidden = false;
			paintLines();
		} catch (error) {
			toast(error.message || "Could not open that bill.", "error");
		}
	}

	function paintLines() {
		const body = $("lines").querySelector("tbody");
		body.innerHTML = sheet.lines.map((l, i) => `
			<tr${l.returning > 0 ? ' class="is-returning"' : ""}>
				<td>${esc(l.item_name)}</td>
				<td class="num">${l.qty}</td>
				<td class="num">${l.returned || "—"}</td>
				<td class="num"><input class="back" data-i="${i}" type="number" min="0" step="1"
					max="${l.can_return}" value="${l.returning || ""}"
					placeholder="0" ${l.can_return ? "" : "disabled"}></td>
				<td class="num">${esc(money2(l.rate))}</td>
				<td class="num">${esc(money2((l.returning || 0) * l.rate))}</td>
			</tr>`).join("");

		body.querySelectorAll(".back").forEach((n) => n.addEventListener("input", () => {
			const line = sheet.lines[Number(n.dataset.i)];
			const asked = Number(n.value) || 0;
			// The box will not let more come back than went out and has not
			// already returned — said here rather than after a failed save.
			if (asked > line.can_return) {
				toast(`Only ${line.can_return} of ${line.item_name} can still come back.`, "error");
				n.value = line.can_return;
			}
			line.returning = Math.min(asked, line.can_return);
			paintTotals();
			n.closest("tr").classList.toggle("is-returning", line.returning > 0);
			n.closest("tr").lastElementChild.textContent = money2(line.returning * line.rate);
		}));
		paintTotals();
	}

	function paintTotals() {
		const total = sheet.lines.reduce((sum, l) => sum + (l.returning || 0) * l.rate, 0);
		const count = sheet.lines.filter((l) => l.returning > 0).length;
		$("r-lines").textContent = count;
		$("r-total").textContent = money2(total);
		$("r-save").disabled = !count;
	}

	// ---------------------------------------------------------------- save
	async function save() {
		if (sheet.saving || !sheet.bill) return;
		const coming = sheet.lines.filter((l) => l.returning > 0);
		if (!coming.length) return note("Say what is coming back.", "error");

		sheet.saving = true;
		$("r-save").disabled = true;
		note("Raising the credit note…");
		try {
			const result = await A3.call("a3_retail.api.returns.create", {
				payload: {
					invoice: sheet.bill.invoice,
					date: $("r-date").value,
					sold_by: $("r-seller").value || "",
					reason: $("r-reason").value.trim(),
					refund_amount: Number($("r-refund").value) || 0,
					mode_of_payment: $("r-mode").value,
					items: coming.map((l) => ({
						item_code: l.item_code, qty: l.returning, rate: l.rate,
						serials: (l.serials || []).slice(0, l.returning),
					})),
				},
			});
			note(`${result.credit_note} raised — ${money2(result.amount)} back`
				+ (result.refunded ? `, ${money2(result.refunded)} refunded` : "")
				+ (result.credit_left ? `, ${money2(result.credit_left)} left as credit` : "")
				+ ".", "ok");
			window.open(result.print_url, "_blank");
			// It is already on the list, so close and let it repaint.
			setTimeout(() => {
				$("return-modal").hidden = true;
				reset();
				load(1);
			}, 1200);
		} catch (error) {
			note(error.message || "Could not raise the credit note.", "error");
			sheet.saving = false;
			$("r-save").disabled = false;
		}
	}

	function reset() {
		sheet.bill = null;
		sheet.lines = [];
		$("bill-q").value = "";
		$("bill-picked").hidden = true;
		$("bill-picked").innerHTML = "";
		$("lines-panel").hidden = true;
		$("r-refund").value = "";
		$("r-reason").value = "";
		$("r-lines").textContent = "0";
		$("r-total").textContent = money2(0);
		$("r-save").disabled = true;
		note("");
		$("bill-q").focus();
	}

	async function startSheet() {
		
		// The shop's own day, not UTC: `toISOString` rolls the date back five
		// and a half hours every evening.
		const today = new Date().toLocaleDateString("en-CA");
		$("r-date").value = today;
		$("r-date").max = today;
		A3.datePicker($("r-date"));
		// The face is drawn from the input's value and only redrawn on `change`,
		// which setting `.value` in code does not fire — so it is fired here, or
		// the box reads "Choose a date" over a date that is already chosen.
		$("r-date").dispatchEvent(new Event("change"));

		try {
			const [boot, staff] = await Promise.all([
				A3.call("a3_retail.api.returns.bootstrap"),
				A3.call("a3_retail.api.pos.branch_staff"),
			]);
			$("r-mode").innerHTML = (boot.modes || [])
				.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
			$("r-seller").innerHTML = '<option value="">Who handled it?</option>'
				+ (staff || []).map((p) =>
					`<option value="${esc(p.employee)}">${esc(p.employee_name)}</option>`).join("");
		} catch (error) {
			note(error.message || "Could not start the screen.", "error");
		}

		$("bill-q").addEventListener("input", () => {
			clearTimeout(billTimer);
			billTimer = setTimeout(findBills, 220);
		});
		$("bill-hits").addEventListener("click", (event) => {
			const pick = event.target.closest(".pick");
			if (pick) pickBill(pick.dataset.name);
		});
		$("take-all").addEventListener("click", () => {
			sheet.lines.forEach((l) => { l.returning = l.can_return; });
			paintLines();
		});
		$("r-save").addEventListener("click", save);
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
		$("new-return").addEventListener("click", () => {
			reset();
			$("return-modal").hidden = false;
			$("bill-q").focus();
		});
		document.querySelectorAll("[data-close]").forEach((node) =>
			node.addEventListener("click", () => { $("return-modal").hidden = true; }));
		startSheet();
		$("export").addEventListener("click", exportCsv);

		load(1);
	});
})();
