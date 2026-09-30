// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Debit notes — stock going back to a supplier.
 *
 * The rep is standing at the counter with the box, so the form is the box: who
 * is taking it, what is in it, and why. Only what the branch actually holds can
 * be offered, and only as much of it as is on the shelf.
 */
(function () {
	const $ = (id) => document.getElementById(id);
	const money = (v) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2,
			maximumFractionDigits: 2 }).format(v || 0);

	function esc(v) {
		const n = document.createElement("div");
		n.textContent = v == null ? "" : String(v);
		return n.innerHTML;
	}

	const state = { branch: "", supplier: null, lines: [], saving: false };
	let supplierTimer = null;
	let itemTimer = null;

	function say(text, kind) {
		const toast = $("toast");
		toast.textContent = text || "";
		toast.className = "toast" + (kind ? " " + kind : "");
		toast.hidden = !text;
		if (text) setTimeout(() => { toast.hidden = true; }, 5000);
	}

	function note(text, kind) {
		$("work-msg").textContent = text || "";
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------- supplier
	async function findSuppliers() {
		const q = $("supplier-q").value.trim();
		if (q.length < 2) return ($("supplier-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.purchases.search_suppliers",
			{ query: q, limit: 8 });
		$("supplier-hits").innerHTML = hits.length
			? hits.map((s) => `<button class="pick" data-name="${esc(s.name)}"
				data-label="${esc(s.supplier_name)}">${esc(s.supplier_name)}${
				s.mobile_no ? " · " + esc(s.mobile_no) : ""}</button>`).join("")
			: '<p class="muted">No supplier by that name. Add them on the Purchases screen first.</p>';
	}

	function pickSupplier(name, label) {
		state.supplier = name;
		$("supplier-picked").textContent = "Going back to " + label;
		$("supplier-hits").innerHTML = "";
		$("supplier-q").value = label;
		paintLines();
	}

	// ----------------------------------------------------------------- items
	async function findItems() {
		const q = $("item-q").value.trim();
		if (q.length < 2) return ($("item-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.supplier_returns.stock_items",
			{ query: q, limit: 8 });
		$("item-hits").innerHTML = (hits || []).length
			? hits.map((i) => `<button class="pick" data-code="${esc(i.item_code)}"
				data-label="${esc(i.item_name)}" data-qty="${i.qty}" data-rate="${i.rate}">
				${esc(i.item_name)} · ${i.qty} in stock</button>`).join("")
			: '<p class="muted">Nothing by that name is in this branch\\u2019s stock.</p>';
	}

	function addLine(code, label, held, rate) {
		const found = state.lines.find((l) => l.item_code === code);
		if (found) {
			found.qty = Math.min(found.qty + 1, found.held);
		} else {
			state.lines.push({ item_code: code, item_name: label, held: Number(held) || 0,
				qty: 1, rate: Number(rate) || 0 });
		}
		$("item-q").value = "";
		$("item-hits").innerHTML = "";
		paintLines();
	}

	function paintLines() {
		const body = $("lines").querySelector("tbody");
		$("empty-note").hidden = state.lines.length > 0;
		body.innerHTML = state.lines.map((l, i) => `
			<tr>
				<td>${esc(l.item_name)}</td>
				<td class="num">${l.held}</td>
				<td><input class="qty" data-i="${i}" type="number" min="1" step="1"
					max="${l.held}" value="${l.qty}"></td>
				<td><input class="rate" data-i="${i}" type="number" min="0" step="0.01"
					value="${l.rate}"></td>
				<td class="num">${money(l.qty * l.rate)}</td>
				<td><button class="drop" data-i="${i}" aria-label="Remove">×</button></td>
			</tr>`).join("");

		body.querySelectorAll(".qty").forEach((n) => n.addEventListener("input", () => {
			const line = state.lines[Number(n.dataset.i)];
			const asked = Number(n.value) || 0;
			// Said here rather than after a failed save: the shelf is the limit.
			if (asked > line.held) {
				say(`Only ${line.held} of ${line.item_name} is in this branch.`, "error");
				n.value = line.held;
			}
			line.qty = Math.min(asked, line.held);
			paintLines();
		}));
		body.querySelectorAll(".rate").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].rate = Number(n.value) || 0; paintLines();
		}));
		body.querySelectorAll(".drop").forEach((n) => n.addEventListener("click", () => {
			state.lines.splice(Number(n.dataset.i), 1); paintLines();
		}));

		const total = state.lines.reduce((sum, l) => sum + l.qty * l.rate, 0);
		$("d-lines").textContent = state.lines.length;
		$("d-total").textContent = money(total);
		$("d-save").disabled = !state.lines.length || !state.supplier;
	}

	// ------------------------------------------------------------- the list
	async function load() {
		try {
			const data = await A3.call("a3_retail.api.supplier_returns.recent", { limit: 30 });
			paint(data.rows || []);
		} catch (error) {
			$("rows").innerHTML =
				`<p class="muted">${esc(error.message || "Could not load debit notes.")}</p>`;
		}
	}

	function paint(rows) {
		if (!rows.length) {
			$("rows").innerHTML = '<p class="muted">Nothing has gone back yet.</p>';
			return;
		}
		$("rows").innerHTML = `
			<table class="bill-table">
				<thead><tr><th>Debit note</th><th>Supplier</th><th>Date</th>
					<th>Lines</th><th class="num">Value</th></tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td>${esc(r.name)}</td>
						<td>${esc(r.supplier_name || r.supplier)}</td>
						<td>${esc(r.posting_date)}</td>
						<td>${esc(r.line_count)}</td>
						<td class="num">${money(r.amount)}</td>
					</tr>`).join("")}
				</tbody>
			</table>`;
	}

	// ---------------------------------------------------------------- save
	async function save() {
		if (state.saving) return;
		if (!state.supplier) return note("Choose which supplier it is going back to.", "error");
		if (!state.lines.length) return note("Say what is going back.", "error");

		state.saving = true;
		$("d-save").disabled = true;
		note("Raising the debit note…");
		try {
			const result = await A3.call("a3_retail.api.supplier_returns.create", {
				payload: {
					supplier: state.supplier,
					bill_no: $("d-bill").value.trim(),
					date: $("d-date").value,
					reason: $("d-reason").value.trim(),
					items: state.lines.map((l) => ({
						item_code: l.item_code, qty: l.qty, rate: l.rate,
					})),
				},
			});
			note(`${result.debit_note} raised — ${money(result.amount)} back to `
				+ `${result.supplier}.`, "ok");
			window.open(result.print_url, "_blank");
			reset();
			load();
		} catch (error) {
			note(error.message || "Could not raise the debit note.", "error");
		} finally {
			state.saving = false;
			$("d-save").disabled = false;
		}
	}

	function reset() {
		state.supplier = null;
		state.lines = [];
		$("supplier-q").value = "";
		$("supplier-picked").textContent = "";
		$("d-bill").value = "";
		$("d-reason").value = "";
		paintLines();
	}

	async function start(options) {
		state.branch = options.branch;
		$("d-date").value = new Date().toISOString().slice(0, 10);

		try {
			const boot = await A3.call("a3_retail.api.supplier_returns.bootstrap");
			if (!boot.can_create) $("d-save").hidden = true;
		} catch (error) {
			note(error.message || "Could not start the screen.", "error");
		}

		$("supplier-q").addEventListener("input", () => {
			clearTimeout(supplierTimer);
			supplierTimer = setTimeout(findSuppliers, 220);
		});
		$("supplier-hits").addEventListener("click", (event) => {
			const pick = event.target.closest(".pick");
			if (pick) pickSupplier(pick.dataset.name, pick.dataset.label);
		});
		$("item-q").addEventListener("input", () => {
			clearTimeout(itemTimer);
			itemTimer = setTimeout(findItems, 220);
		});
		$("item-hits").addEventListener("click", (event) => {
			const pick = event.target.closest(".pick");
			if (pick) addLine(pick.dataset.code, pick.dataset.label,
				pick.dataset.qty, pick.dataset.rate);
		});
		$("d-save").addEventListener("click", save);
		$("refresh").addEventListener("click", load);
		paintLines();
		load();
	}

	window.DEBIT_NOTES = { start };
})();
