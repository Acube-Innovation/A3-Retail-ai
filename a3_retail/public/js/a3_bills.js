// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Bills — the invoices the counters wrote.
 *
 * Reads and prints; it creates nothing of its own. A draft goes back to the
 * sales counter to be edited, because that screen already knows how to price a
 * basket, and printing goes through the one print link the counter uses, so a
 * bill looks the same wherever it comes out.
 */

window.BILLS = (function () {
	const state = {
		branch: "", page: 1, pageSize: 20, rows: [], invoice: null,
		filters: { query: "", from_date: "", to_date: "", status: "all", mode: "all",
		           branch: "current", customer: "" },
	};
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);
	const money2 = (value) =>
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

	// ------------------------------------------------------------- loading
	function skeleton(rows) {
		$("rows").innerHTML = Array.from({ length: rows }, () =>
			'<tr class="is-skeleton">' + "<td><span></span></td>".repeat(15) + "</tr>").join("");
	}

	async function load(page) {
		state.page = page || state.page;
		skeleton(6);

		try {
			const [tiles, data] = await Promise.all([
				A3.call("a3_retail.api.bills.summary", { filters: state.filters }),
				A3.call("a3_retail.api.bills.list_bills", {
					filters: state.filters, page: state.page, page_size: state.pageSize }),
			]);
			paintTiles(tiles);
			paintRows(data);
		} catch (error) {
			$("rows").innerHTML = `<tr><td colspan="15" class="bill-empty-cell">
				<b>Could not load the bills.</b><span>${esc(error.message)}</span></td></tr>`;
		}
	}

	function paintTiles(tiles) {
		const card = (key, label, tone, glyph) => {
			const box = tiles[key];
			return `<div class="ctile bill-tile">
				<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
					<span class="ctile-label">${label}</span></div>
				<div class="ctile-value">${money(box.amount)}</div>
				<div class="ctile-sub">${box.count} ${box.count === 1 ? "bill" : "bills"}</div>
			</div>`;
		};

		$("tiles").innerHTML =
			card("total", "Total Bills", "sky", "file")
			+ card("paid", "Paid", "good", "check")
			+ card("partly", "Partially Paid", "warn", "cash")
			+ card("unpaid", "Unpaid", "bad", "ban")
			+ card("cancelled", "Cancelled", "bad", "ban")
			+ card("today", "Today's Sales", "warn", "cash");
	}

	function paintRows(data) {
		state.rows = data.rows;

		if (!data.rows.length) {
			$("rows").innerHTML = `<tr><td colspan="15" class="bill-empty-cell">
				<b>No invoices found</b>
				<span>Try changing your filters or search criteria.</span></td></tr>`;
		} else {
			$("rows").innerHTML = data.rows.map((row) => `
				<tr data-name="${esc(row.name)}" class="${row.status === "Cancelled" ? "is-cancelled" : ""}">
					<td><a class="bill-no" href="/retail/invoice?name=${encodeURIComponent(row.name)}">${
						esc(row.name)}</a></td>
					<td class="nowrap">${esc(day(row.posting_date))}</td>
					<td>${esc(row.customer_name || row.customer)}</td>
					<td class="nowrap">${esc(row.mobile_no || "—")}</td>
					<td class="num">${row.items}</td>
					<td class="num">${money(row.net_total)}</td>
					<td class="num">${row.discount_amount ? "- " + money(row.discount_amount) : "₹0"}</td>
					<td class="num">${money(row.total_taxes_and_charges)}</td>
					<td class="num strong">${money(row.payable)}</td>
					<td class="num good">${money(row.paid)}</td>
					<td class="num ${row.balance > 0 ? "warn-red" : ""}">${money(row.balance)}</td>
					<td><span class="pill ${payTone(row.payment_status)}">${esc(row.payment_status)}</span></td>
					<td><span class="pill ${docTone(row.status)}">${esc(row.status)}</span></td>
					<td class="nowrap">${esc(row.sales_person || "—")}</td>
					<td class="bill-actions">
						<a class="icon-btn plain" title="View"
						   href="/retail/invoice?name=${encodeURIComponent(row.name)}">${icon("eye")}</a>
						${row.editable
							? `<a class="icon-btn plain" title="Edit this draft"
							     href="/retail/sales?invoice=${encodeURIComponent(row.name)}">${icon("pencil")}</a>`
							: '<span class="icon-btn plain is-off" title="Only a draft can be edited">'
							  + icon("pencil") + "</span>"}
						<button class="icon-btn plain" data-act="print" title="Print">${icon("print")}</button>
						${row.balance > 0 && row.status === "Submitted"
							? `<button class="icon-btn plain" data-act="pay" title="Collect payment">${
								icon("cash")}</button>`
							: ""}
						<button class="icon-btn plain" data-act="more" title="More">${icon("more")}</button>
					</td>
				</tr>`).join("");
		}

		$("showing").textContent = data.total
			? `Showing ${data.showing[0]}–${data.showing[1]} of ${data.total.toLocaleString("en-IN")} invoices`
			: "No invoices";
		paintPager(data);

		$("rows").querySelectorAll("[data-act]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.stopPropagation();
				const name = node.closest("tr").dataset.name;
				const row = state.rows.find((r) => r.name === name);
				if (node.dataset.act === "print") return print(name);
				if (node.dataset.act === "pay") return askPayment(row);
				if (node.dataset.act === "more") return more(row);
			});
		});
	}

	function paintPager(data) {
		const pages = data.pages;
		const here = data.page;
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

		$("pager").querySelectorAll("[data-go]").forEach((node) => {
			node.addEventListener("click", () => load(Number(node.dataset.go)));
		});
	}

	/** The same glyphs the rest of the app draws, inline where the page builds
	 *  its own markup. */
	function icon(name) {
		const paths = {
			file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
			check: '<path d="M20 6 9 17l-5-5"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
			eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
			pencil: '<path d="M4 20h4L20 8l-4-4L4 16z"/><path d="M14 6l4 4"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
	}

	// ------------------------------------------------------------- actions
	/** One print path for the whole application: the counter's own link. */
	function print(name) {
		window.open("/api/method/frappe.utils.print_format.download_pdf"
			+ "?doctype=Sales%20Invoice&name=" + encodeURIComponent(name)
			+ "&format=Retail%20Tax%20Invoice&no_letterhead=0", "_blank");
	}

	function more(row) {
		$("list-title").textContent = row.name;
		$("list-note").textContent = `${row.customer_name} · ${money2(row.payable)}`;
		const options = [
			["Open the invoice", () => { window.location = "/retail/invoice?name="
				+ encodeURIComponent(row.name); }],
			["Print", () => print(row.name)],
			["Send on WhatsApp", () => send(row.name, "WhatsApp")],
			["Send by email", () => send(row.name, "Email")],
		];
		if (row.editable) {
			options.splice(1, 0, ["Edit this draft at the counter", () => {
				window.location = "/retail/sales?invoice=" + encodeURIComponent(row.name);
			}]);
		}

		$("list-body").innerHTML = options.map(([label], index) =>
			`<li><button class="linkish" data-i="${index}">${label}</button></li>`).join("");
		$("list-body").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				$("list-modal").hidden = true;
				options[Number(node.dataset.i)][1]();
			});
		});
		$("list-modal").hidden = false;
	}

	async function send(name, channel) {
		try {
			const result = await A3.call("a3_retail.api.bills.send", { name, channel });
			toast(result.sent ? channel + " sent." : channel + " was not sent — check messaging "
				+ "settings.", result.sent ? "ok" : "error");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function askPayment(row) {
		state.invoice = row;
		$("payment-note").textContent =
			`${row.name} · ${row.customer_name} · ${money2(row.balance)} still owed`;
		$("pay-amount").value = row.balance.toFixed(2);
		$("pay-amount").max = row.balance;
		$("pay-reference").value = "";
		$("payment-modal").hidden = false;
		$("pay-amount").focus();
	}

	async function takePayment() {
		try {
			const result = await A3.call("a3_retail.api.bills.collect_payment", {
				name: state.invoice.name,
				amount: Number($("pay-amount").value) || 0,
				mode_of_payment: $("pay-mode").value,
				reference: $("pay-reference").value.trim() || null,
			});
			$("payment-modal").hidden = true;
			toast(`${money2(result.paid)} taken — ${result.payment_status.toLowerCase()}.`, "ok");
			load();
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function exportCsv() {
		const head = ["Invoice", "Date", "Customer", "Phone", "Items", "Subtotal", "Discount",
		              "GST", "Grand Total", "Paid", "Balance", "Payment", "Status",
		              "Sales Person"].join(",") + "\n";
		const body = state.rows.map((row) => [row.name, row.posting_date,
			row.customer_name, row.mobile_no || "", row.items, row.net_total,
			row.discount_amount, row.total_taxes_and_charges, row.payable, row.paid,
			row.balance, row.payment_status, row.status, row.sales_person || ""]
			.map((cell) => `"${String(cell == null ? "" : cell).replace(/"/g, '""')}"`).join(","))
			.join("\n");

		const url = URL.createObjectURL(new Blob([head + body], { type: "text/csv" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = "bills.csv";
		link.click();
		URL.revokeObjectURL(url);
		toast(`Exported the ${state.rows.length} bills on this page.`, "ok");
	}

	// --------------------------------------------------------------- start
	let searchTimer;
	function start(options) {
		state.branch = options.branch;

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				load(1);
			}, 220);
		});

		[["from-date", "from_date"], ["to-date", "to_date"], ["status", "status"],
		 ["mode", "mode"], ["branch", "branch"]].forEach(([id, key]) => {
			$(id).addEventListener("change", () => {
				state.filters[key] = $(id).value;
				load(1);
			});
		});

		let customerTimer;
		$("customer").addEventListener("input", () => {
			clearTimeout(customerTimer);
			customerTimer = setTimeout(async () => {
				const typed = $("customer").value.trim();
				state.filters.customer = "";
				if (typed.length >= 2) {
					const rows = await A3.call("a3_retail.api.bills.customers", { query: typed });
					$("customer-list").innerHTML = rows.map((row) =>
						`<option value="${esc(row.name)}">${esc(row.customer_name)} · ${
							esc(row.mobile_no || "")}</option>`).join("");
					if (rows.some((row) => row.name === typed)) state.filters.customer = typed;
				}
				load(1);
			}, 260);
		});

		$("page-size").addEventListener("change", () => {
			state.pageSize = Number($("page-size").value);
			load(1);
		});
		$("clear").addEventListener("click", () => {
			state.filters = { query: "", from_date: "", to_date: "", status: "all", mode: "all",
			                  branch: "current", customer: "" };
			["q", "from-date", "to-date", "customer"].forEach((id) => { $(id).value = ""; });
			$("status").value = "all";
			$("mode").value = "all";
			$("branch").value = "current";
			load(1);
		});
		$("refresh").addEventListener("click", () => { load(); toast("Refreshed."); });
		$("export").addEventListener("click", exportCsv);
		$("filter-toggle").addEventListener("click", () => {
			$("filter-row").classList.toggle("is-open");
		});
		$("pay-save").addEventListener("click", takePayment);

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		load(1);
	}

	return { start, state };
})();
