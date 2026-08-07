// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Service Bookings — every device the counter has taken in.
 *
 * The list a service desk actually needs: what is in the shop, what is waiting
 * on a part, what is ready to hand back and what is running late. It reads the
 * job cards the Mobile Service POS writes and changes none of them — a booking
 * is opened, printed or taken back to the counter, and the counter does the work.
 */

window.BOOKINGS = (function () {
	const state = {
		branch: "", page: 1, pageSize: 20, rows: [], boot: null,
		filters: { query: "", from_date: "", to_date: "", status: "all", payment: "all",
		           technician: "", priority: "all", delay: "all", branch: "current" },
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

	function stamp(value) {
		if (!value) return "—";
		const date = new Date(String(value).replace(" ", "T"));
		return isNaN(date) ? String(value)
			: date.toLocaleString("en-IN", { day: "2-digit", month: "short",
			                                 hour: "2-digit", minute: "2-digit" });
	}

	function toast(text, kind) {
		const box = document.createElement("div");
		box.className = "toast" + (kind ? " " + kind : "");
		box.textContent = text;
		document.body.appendChild(box);
		setTimeout(() => box.remove(), 3600);
	}

	function payTone(row) {
		if (row.warranty_borne_amount > 0 && row.customer_payable <= 0) return "pill-purple";
		if (row.balance > 0.005) return row.advance_amount > 0 ? "pill-warn" : "pill-bad";
		return "pill-good";
	}

	function payLabel(row) {
		if (row.warranty_borne_amount > 0 && row.customer_payable <= 0) return "Warranty";
		if (row.balance > 0.005) return row.advance_amount > 0 ? "Part paid" : "Unpaid";
		return "Settled";
	}

	/** The same glyphs the rest of the app draws. */
	function icon(name) {
		const paths = {
			clipboard: '<path d="M9 4h6v3H9z"/><path d="M9 5.5H7a2 2 0 0 0-2 2V19a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.5a2 2 0 0 0-2-2h-2"/><path d="M9 12h6M9 16h4"/>',
			wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 21H10L4.3 15.3a4 4 0 0 1 5-5z"/><path d="M9 9l6 6"/>',
			clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
			check: '<path d="M20 6 9 17l-5-5"/>',
			truck: '<rect x="2" y="7" width="12" height="9" rx="2"/><path d="M14 10h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>',
			alarm: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 3 2 6M19 3l3 3"/>',
			cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>',
			eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
			print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>',
			more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
		};
		return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
			stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ""}</svg>`;
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
				A3.call("a3_retail.api.bookings.summary", { filters: state.filters }),
				A3.call("a3_retail.api.bookings.list_bookings", {
					filters: state.filters, page: state.page, page_size: state.pageSize }),
			]);
			paintTiles(tiles);
			paintRows(data);
		} catch (error) {
			$("rows").innerHTML = `<tr><td colspan="15" class="bill-empty-cell">
				<b>Could not load the bookings.</b><span>${esc(error.message)}</span></td></tr>`;
		}
	}

	function paintTiles(tiles) {
		const card = (key, label, sub, tone, glyph, filter) => {
			const box = tiles[key];
			return `<div class="ctile bill-tile" data-filter="${filter || ""}">
				<div class="ctile-head"><span class="ctile-ico ${tone}">${icon(glyph)}</span>
					<span class="ctile-label">${label}</span></div>
				<div class="ctile-value">${box.count.toLocaleString("en-IN")}</div>
				<div class="ctile-sub">${sub(box)}</div>
			</div>`;
		};

		$("tiles").innerHTML =
			card("total", "Bookings", (box) => money(box.amount) + " of work", "sky",
			     "clipboard", "status=all")
			+ card("in_shop", "In the shop", (box) => money(box.amount) + " in hand", "sky",
			       "wrench", "status=in_shop")
			+ card("waiting", "Waiting", () => "on parts, an estimate or the customer", "warn",
			       "clock", "status=waiting")
			+ card("ready", "Ready", () => "waiting to be collected", "good", "check",
			       "status=ready")
			+ card("delivered", "Handed over today", (box) => money(box.amount), "good", "truck",
			       "status=delivered")
			+ card("delayed", "Running late", () => "past the promised time", "bad", "alarm",
			       "delay=delayed")
			+ card("outstanding", "Still owed", (box) => money(box.amount), "bad", "cash",
			       "payment=unpaid")
			+ card("advance", "Advances taken", (box) => money(box.amount), "warn", "cash", "");

		$("tiles").querySelectorAll("[data-filter]").forEach((node) => {
			if (!node.dataset.filter) return;
			node.classList.add("is-clickable");
			node.addEventListener("click", () => {
				const [key, value] = node.dataset.filter.split("=");
				state.filters = { ...state.filters, status: "all", delay: "all", payment: "all" };
				state.filters[key] = value;
				["status", "delay", "payment"].forEach((id) => { $(id).value = state.filters[id]; });
				load(1);
			});
		});
	}

	function paintRows(data) {
		state.rows = data.rows;

		if (!data.rows.length) {
			$("rows").innerHTML = `<tr><td colspan="15" class="bill-empty-cell">
				<b>No bookings found</b>
				<span>Try a different search, or book a device in at the counter.</span></td></tr>`;
		} else {
			$("rows").innerHTML = data.rows.map((row) => `
				<tr data-name="${esc(row.name)}" class="${row.overdue ? "is-late" : ""}">
					<td><a class="bill-no" href="/branch/booking?name=${encodeURIComponent(row.name)}">${
						esc(row.name)}</a>${row.priority === "Urgent (Same Day)" || row.priority === "High"
							? `<small class="row-flag">${esc(row.priority)}</small>` : ""}</td>
					<td class="nowrap">${esc(stamp(row.received_on))}</td>
					<td>${esc(row.customer_name || row.customer)}</td>
					<td class="nowrap">${esc(row.customer_mobile || "—")}</td>
					<td>${esc(row.device || "—")}<small>${esc(row.repair_category || "")}</small></td>
					<td class="nowrap">${esc(row.imei_1 || row.serial_no || "—")}</td>
					<td class="cell-clip" title="${esc(row.complaint_description || "")}">${
						esc((row.complaint_description || "—").slice(0, 60))}</td>
					<td class="nowrap">${esc(row.technician_name || "Unassigned")}</td>
					<td class="nowrap ${row.overdue ? "warn-red" : ""}">${esc(stamp(row.estimated_delivery_date))}</td>
					<td><span class="pill ${row.tone}">${esc(row.status)}</span></td>
					<td class="num strong">${money(row.grand_total)}</td>
					<td class="num good">${money(row.advance_amount)}</td>
					<td class="num ${row.balance > 0 ? "warn-red" : ""}">${money(row.balance)}</td>
					<td><span class="pill ${payTone(row)}">${payLabel(row)}</span></td>
					<td class="bill-actions">
						<a class="icon-btn plain" title="Open this booking"
						   href="/branch/booking?name=${encodeURIComponent(row.name)}">${icon("eye")}</a>
						<button class="icon-btn plain" data-act="print"
						        title="Print the acknowledgement">${icon("print")}</button>
						<a class="icon-btn plain" title="Open at the service counter"
						   href="/branch/service?booking=${encodeURIComponent(row.name)}">${icon("wrench")}</a>
						<button class="icon-btn plain" data-act="more" title="More">${icon("more")}</button>
					</td>
				</tr>`).join("");
		}

		$("showing").textContent = data.total
			? `Showing ${data.showing[0]}–${data.showing[1]} of ${
				data.total.toLocaleString("en-IN")} bookings`
			: "No bookings";
		paintPager(data);

		$("rows").querySelectorAll("[data-act]").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.stopPropagation();
				const name = node.closest("tr").dataset.name;
				const row = state.rows.find((r) => r.name === name);
				if (node.dataset.act === "print") return print(name);
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

	// ------------------------------------------------------------- actions
	/** One print path for the whole application: the counter's own
	 *  acknowledgement, the sheet the customer walked out with. */
	async function print(name) {
		try {
			const url = await A3.call("a3_retail.api.bookings.print_url", { name });
			window.open(url, "_blank");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function more(row) {
		$("list-title").textContent = row.name;
		$("list-note").textContent = `${row.customer_name} · ${row.device || ""} · ${
			money2(row.balance)} owed`;
		const options = [
			["Open the booking", () => { window.location = "/branch/booking?name="
				+ encodeURIComponent(row.name); }],
			["Open at the service counter", () => { window.location = "/branch/service?booking="
				+ encodeURIComponent(row.name); }],
			["Print the acknowledgement", () => print(row.name)],
			["Send the customer an update", () => notify(row.name, "WhatsApp")],
			["Email the customer an update", () => notify(row.name, "Email")],
		];
		if (row.sales_invoice) {
			options.push(["Open the invoice", () => { window.location = "/branch/invoice?name="
				+ encodeURIComponent(row.sales_invoice); }]);
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

	async function notify(name, channel) {
		try {
			const result = await A3.call("a3_retail.api.bookings.notify", { name, channel });
			toast(result.sent ? channel + " sent." : channel + " was not sent — check messaging "
				+ "settings.", result.sent ? "ok" : "error");
		} catch (error) {
			toast(error.message, "error");
		}
	}

	function exportCsv() {
		const head = ["Booking", "Booked", "Customer", "Phone", "Device", "IMEI", "Complaint",
		              "Technician", "Promised", "Status", "Total", "Advance", "Balance"]
			.join(",") + "\n";
		const body = state.rows.map((row) => [row.name, row.received_on, row.customer_name,
			row.customer_mobile || "", row.device || "", row.imei_1 || "",
			row.complaint_description || "", row.technician_name || "",
			row.estimated_delivery_date || "", row.status, row.grand_total, row.advance_amount,
			row.balance]
			.map((cell) => `"${String(cell == null ? "" : cell).replace(/"/g, '""')}"`).join(","))
			.join("\n");

		const url = URL.createObjectURL(new Blob([head + body], { type: "text/csv" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = "service-bookings.csv";
		link.click();
		URL.revokeObjectURL(url);
		toast(`Exported the ${state.rows.length} bookings on this page.`, "ok");
	}

	// --------------------------------------------------------------- start
	let searchTimer;
	async function start(options) {
		state.branch = options.branch;

		try {
			state.boot = await A3.call("a3_retail.api.bookings.bootstrap", {});
			$("status-list").innerHTML = state.boot.statuses.map((status) =>
				`<option value="${esc(status)}">${esc(status)}</option>`).join("");
			$("technician").innerHTML = '<option value="">Anyone</option>'
				+ state.boot.technicians.map((row) =>
					`<option value="${esc(row.name)}">${esc(row.label)}</option>`).join("");
		} catch (error) {
			toast(error.message, "error");
		}

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				state.filters.query = $("q").value.trim();
				load(1);
			}, 220);
		});

		[["from-date", "from_date"], ["to-date", "to_date"], ["status", "status"],
		 ["payment", "payment"], ["technician", "technician"], ["priority", "priority"],
		 ["delay", "delay"], ["branch", "branch"]].forEach(([id, key]) => {
			$(id).addEventListener("change", () => {
				state.filters[key] = $(id).value;
				load(1);
			});
		});

		$("page-size").addEventListener("change", () => {
			state.pageSize = Number($("page-size").value);
			load(1);
		});
		$("clear").addEventListener("click", () => {
			state.filters = { query: "", from_date: "", to_date: "", status: "all", payment: "all",
			                  technician: "", priority: "all", delay: "all", branch: "current" };
			["q", "from-date", "to-date"].forEach((id) => { $(id).value = ""; });
			["status", "payment", "priority", "delay"].forEach((id) => { $(id).value = "all"; });
			$("technician").value = "";
			$("branch").value = "current";
			load(1);
		});
		$("refresh").addEventListener("click", () => { load(); toast("Refreshed."); });
		$("export").addEventListener("click", exportCsv);
		$("filter-toggle").addEventListener("click", () => {
			$("filter-row").classList.toggle("is-open");
		});

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
