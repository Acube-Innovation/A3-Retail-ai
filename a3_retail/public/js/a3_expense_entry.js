// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Create Expense — a page, not a dialog.
 *
 * Laid out the way the shop's old billing software laid it out, because sixty
 * of these a month are entered by people who learned it there: the category and
 * the series on the left, the bill number, date, payment and note on the right,
 * then the items and what it comes to.
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

	/** Today in the shop's own day — toISOString is UTC and lands on yesterday
	 *  here before half past five in the morning. */
	const today = () => new Date().toLocaleDateString("en-CA");

	const state = {
		categories: [], sources: [], modes: [], canAddCategory: false,
		lines: [], supplier: null, catalogue: [], chosen: new Set(), saving: false,
	};

	function say(text, kind) {
		$("x-msg").textContent = text || "";
		$("x-msg").className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------------ start
	async function start() {
		$("x-date").value = today();
		$("x-date").max = today();
		try {
			const boot = await A3.call("a3_retail.api.expenses.bootstrap");
			state.categories = boot.categories || [];
			state.sources = boot.sources || [];
			state.modes = boot.modes || [];
			state.canAddCategory = !!boot.can_add_category;

			$("x-category").innerHTML = categoryOptions();
			$("x-source").innerHTML = state.sources.map((s) =>
				`<option value="${esc(s.account)}">${esc(s.label)}</option>`).join("");
			$("x-mode").innerHTML = '<option value="">Select</option>'
				+ state.modes.map((m) =>
					`<option value="${esc(m)}">${esc(m)}</option>`).join("");
			$("x-prefix").value = boot.series.prefix;
			$("x-number").value = boot.series.number;
			$("x-newcat").hidden = !state.canAddCategory;
		} catch (error) {
			say(error.message || "Could not open this screen.", "error");
		}
		paintLines();
		wire();
	}

	const categoryOptions = (selected) =>
		'<option value="">Select Category</option>' + state.categories.map((c) =>
			`<option value="${esc(c.account)}"${c.account === selected ? " selected" : ""}>${
				esc(c.label)}</option>`).join("");

	// ------------------------------------------------------------------ lines
	const blankLine = (over) => Object.assign(
		{ item_code: null, description: "", qty: 1, rate: 0, gst_rate: 0 }, over || {});

	function paintLines() {
		const gst = $("x-gst").checked;
		$("x-lines-wrap").hidden = !state.lines.length;
		document.querySelectorAll(".xp-gst-col").forEach((n) => { n.hidden = !gst; });

		$("x-lines").innerHTML = state.lines.map((l, i) => `
			<tr data-i="${i}">
				<td><input class="xp-item" value="${esc(l.description)}"
					placeholder="What it was" autocomplete="off">
					<div class="w-hits" data-hits="${i}"></div></td>
				<td class="num"><input class="xp-qty num" type="number" min="0"
					step="0.01" value="${l.qty}"></td>
				<td class="num"><input class="xp-rate num" type="number" min="0"
					step="0.01" value="${l.rate || ""}"></td>
				<td class="num xp-gst-col"${gst ? "" : " hidden"}>
					<input class="xp-gstrate num" type="number" min="0" step="0.01"
						value="${l.gst_rate || 0}"></td>
				<td class="num">${esc(money(l.qty * l.rate))}</td>
				<td><button type="button" class="drop" aria-label="Remove">×</button></td>
			</tr>`).join("");
		wireLines();
		paintTotals();
	}

	function wireLines() {
		$("x-lines").querySelectorAll("tr").forEach((tr) => {
			const i = Number(tr.dataset.i);
			const line = state.lines[i];
			const box = tr.querySelector(".xp-item");
			const hits = tr.querySelector("[data-hits]");

			box.addEventListener("input", async () => {
				line.description = box.value;
				line.item_code = null;
				const q = box.value.trim();
				if (q.length < 2) { hits.innerHTML = ""; return; }
				const rows = await A3.call("a3_retail.api.expenses.search_items",
					{ query: q, limit: 8 }).catch(() => []);
				hits.innerHTML = (rows || []).map((r) =>
					`<button type="button" class="w-hit" data-code="${esc(r.item_code)}"
						data-name="${esc(r.item_name)}" data-rate="${r.rate || 0}"
						>${esc(r.item_name)}${r.rate ? `<b>${esc(money(r.rate))}</b>` : ""}
					</button>`).join("");
			});
			// mousedown, because blur tears the list down before a click lands.
			hits.addEventListener("mousedown", (event) => {
				const hit = event.target.closest(".w-hit");
				if (!hit) return;
				event.preventDefault();
				line.item_code = hit.dataset.code;
				line.description = hit.dataset.name;
				if (!line.rate) line.rate = Number(hit.dataset.rate) || 0;
				hits.innerHTML = "";
				paintLines();
			});
			box.addEventListener("blur", () =>
				setTimeout(() => { hits.innerHTML = ""; }, 120));

			tr.querySelector(".xp-qty").addEventListener("input", (e) => {
				line.qty = Number(e.target.value) || 0;
				paintAmount(tr, line);
			});
			tr.querySelector(".xp-rate").addEventListener("input", (e) => {
				line.rate = Number(e.target.value) || 0;
				paintAmount(tr, line);
			});
			const rate = tr.querySelector(".xp-gstrate");
			if (rate) rate.addEventListener("input", (e) => {
				line.gst_rate = Number(e.target.value) || 0;
				paintTotals();
			});
			tr.querySelector(".drop").addEventListener("click", () => {
				state.lines.splice(i, 1);
				paintLines();
			});
		});
	}

	/** Only the amount cell changes as you type, so the caret stays put. */
	function paintAmount(tr, line) {
		tr.querySelector("td:nth-last-child(2)").textContent = money(line.qty * line.rate);
		paintTotals();
	}

	function paintTotals() {
		const gst = $("x-gst").checked;
		const total = state.lines.reduce((s, l) => s + (l.qty * l.rate), 0);
		const discount = Number($("x-discount").value) || 0;
		const net = Math.max(total - discount, 0);
		const tax = !gst ? 0 : state.lines.reduce(
			(s, l) => s + (l.qty * l.rate * (l.gst_rate || 0) / 100), 0);
		const grand = Math.round((net + tax) * 100) / 100;
		const paid = $("x-paid").value === "" ? grand : Number($("x-paid").value) || 0;
		const owed = Math.round((grand - paid) * 100) / 100;

		// A balance has to be owed to somebody, so the date only matters then.
		$("x-due-wrap").hidden = owed <= 0;

		$("x-totals").innerHTML = `
			<div class="tr"><span>Total</span><span>${esc(money(total))}</span></div>
			${discount ? `<div class="tr"><span>Discount</span>
				<span>− ${esc(money(discount))}</span></div>` : ""}
			${gst && tax ? `<div class="tr"><span>GST</span>
				<span>${esc(money(tax))}</span></div>` : ""}
			<div class="tr grand"><span>Total Expense Amount</span>
				<span>${esc(money(grand))}</span></div>
			${owed > 0 ? `<div class="tr owed"><span>Still owed</span>
				<span>${esc(money(owed))}</span></div>` : ""}`;
	}

	// --------------------------------------------------------------- the picker
	async function openPicker() {
		state.chosen = new Set();
		$("x-q").value = "";
		$("x-pick").hidden = false;
		$("x-q").focus();
		await search("");
	}

	async function search(query) {
		try {
			state.catalogue = await A3.call("a3_retail.api.expenses.search_items",
				{ query, limit: 40 });
		} catch (error) {
			state.catalogue = [];
		}
		paintResults();
	}

	function paintResults() {
		if (!state.catalogue.length) {
			$("x-results").innerHTML =
				'<tr><td colspan="4">Nothing by that name — use “Create New Item”.</td></tr>';
			return;
		}
		$("x-results").innerHTML = state.catalogue.map((r) => `
			<tr>
				<td><input type="checkbox" data-code="${esc(r.item_code)}"
					${state.chosen.has(r.item_code) ? "checked" : ""}></td>
				<td>${esc(r.item_name)}</td>
				<td>${esc(r.hsn || "—")}</td>
				<td class="num">${r.rate ? esc(money(r.rate)) : "—"}</td>
			</tr>`).join("");
		$("x-results").querySelectorAll("input[type=checkbox]").forEach((box) =>
			box.addEventListener("change", () => {
				if (box.checked) state.chosen.add(box.dataset.code);
				else state.chosen.delete(box.dataset.code);
			}));
	}

	function addChosen() {
		state.catalogue
			.filter((r) => state.chosen.has(r.item_code))
			.forEach((r) => state.lines.push(blankLine({
				item_code: r.item_code, description: r.item_name,
				rate: r.rate || 0, gst_rate: r.gst_rate || 0,
			})));
		$("x-pick").hidden = true;
		if (!state.lines.length) state.lines.push(blankLine());
		paintLines();
	}

	// -------------------------------------------------------------- new records
	async function askCategory() {
		const label = (window.prompt("What should the new category be called?") || "").trim();
		if (!label) return;
		try {
			const made = await A3.call("a3_retail.api.expenses.add_category", { label });
			if (made.created) {
				state.categories.push({ account: made.account, label: made.label });
				state.categories.sort((a, b) => a.label.localeCompare(b.label));
			}
			$("x-category").innerHTML = categoryOptions(made.account);
			A3.toast(made.created ? `Added ${made.label}.`
				: `${made.label} was already there.`, "ok");
		} catch (error) {
			say(error.message || "Could not add that category.", "error");
		}
	}

	async function askItem() {
		const name = (window.prompt("What is the new item called?") || "").trim();
		if (!name) return;
		try {
			const made = await A3.call("a3_retail.api.expenses.create_item", {
				payload: { item_name: name, expense_account: $("x-category").value },
			});
			state.chosen.add(made.item_code);
			await search(name);
			A3.toast(made.created ? `Added ${made.item_name}.`
				: `${made.item_name} was already there.`, "ok");
		} catch (error) {
			A3.toast(error.message || "Could not add that item.", "error");
		}
	}

	// -------------------------------------------------------------------- save
	async function save() {
		if (state.saving) return;
		const lines = state.lines.filter((l) => l.description && l.rate > 0);
		if (!$("x-category").value) return say("Choose what this was spent on.", "error");
		if (!lines.length) return say("Add what the money went on.", "error");

		state.saving = true;
		$("x-save").disabled = true;
		say("Saving…");
		try {
			const result = await A3.call("a3_retail.api.expenses.create", {
				payload: {
					date: $("x-date").value,
					category: $("x-category").value,
					with_gst: $("x-gst").checked ? 1 : 0,
					reference_no: $("x-ref").value.trim(),
					supplier: state.supplier,
					paid_to: state.supplier ? "" : $("x-paidto").value.trim(),
					mode_of_payment: $("x-mode").value,
					paid_from: $("x-source").value,
					discount: Number($("x-discount").value) || 0,
					paid_amount: $("x-paid").value === "" ? null
						: Number($("x-paid").value) || 0,
					due_date: $("x-due").value || null,
					note: $("x-note").value.trim(),
					items: lines.map((l) => ({ item_code: l.item_code,
						description: l.description, qty: l.qty, rate: l.rate,
						gst_rate: l.gst_rate })),
				},
			});
			say(`${result.expense} saved — ${money(result.amount)}`
				+ (result.outstanding > 0
					? `, ${money(result.outstanding)} still owed.` : "."), "ok");
			setTimeout(() => { window.location.href = "/retail/expenses"; }, 1200);
		} catch (error) {
			say(error.message || "Could not save that expense.", "error");
			state.saving = false;
			$("x-save").disabled = false;
		}
	}

	// -------------------------------------------------------------------- wire
	function wire() {
		$("x-save").addEventListener("click", save);
		$("x-additem").addEventListener("click", openPicker);
		$("x-newcat").addEventListener("click", askCategory);
		$("x-newitem").addEventListener("click", askItem);
		$("x-pick-add").addEventListener("click", addChosen);
		$("x-gst").addEventListener("change", paintLines);
		$("x-discount").addEventListener("input", paintTotals);
		$("x-paid").addEventListener("input", paintTotals);
		document.querySelectorAll("[data-close]").forEach((n) =>
			n.addEventListener("click", () => { $("x-pick").hidden = true; }));

		let timer = null;
		$("x-q").addEventListener("input", () => {
			clearTimeout(timer);
			timer = setTimeout(() => search($("x-q").value.trim()), 220);
		});

		const paidTo = $("x-paidto");
		const hits = $("x-supplier-hits");
		paidTo.addEventListener("input", async () => {
			state.supplier = null;
			const q = paidTo.value.trim();
			if (q.length < 2) { hits.innerHTML = ""; return; }
			const rows = await A3.call("a3_retail.api.expenses.search_suppliers",
				{ query: q, limit: 6 }).catch(() => []);
			hits.innerHTML = (rows || []).map((r) =>
				`<button type="button" class="w-hit" data-name="${esc(r.name)}"
					data-label="${esc(r.supplier_name)}">${esc(r.supplier_name)}</button>`)
				.join("");
		});
		hits.addEventListener("mousedown", (event) => {
			const hit = event.target.closest(".w-hit");
			if (!hit) return;
			event.preventDefault();
			state.supplier = hit.dataset.name;
			paidTo.value = hit.dataset.label;
			hits.innerHTML = "";
		});
		paidTo.addEventListener("blur", () =>
			setTimeout(() => { hits.innerHTML = ""; }, 120));
	}

	document.addEventListener("DOMContentLoaded", start);
})();
