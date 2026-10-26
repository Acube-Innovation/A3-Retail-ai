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
		// `"` and `'` as well, not just the tag characters: almost every use of
		// this is inside an attribute, and a name like `APPLE IPAD A16 "11"`
		// would otherwise close the attribute at its first inner quote and the
		// rest of the name would be parsed as stray attributes.
		return String(v == null ? "" : v)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
	}

	/** Today in the shop's own day — toISOString is UTC and lands on yesterday
	 *  here before half past five in the morning. */
	const today = () => new Date().toLocaleDateString("en-CA");

	const state = {
		categories: [], sources: [], modes: [], uoms: [], gstRates: [], itc: [],
		canAddCategory: false, canCreateItem: false,
		lines: [], supplier: null, employee: null, catalogue: [], chosen: new Set(),
		saving: false,
	};

	function say(text, kind) {
		$("x-msg").textContent = text || "";
		$("x-msg").className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------------ start
	async function start() {
		$("x-date").value = today();
		$("x-date").max = today();
		// After the value and the ceiling, so the calendar opens on the right
		// month and refuses the days that have not happened.
		A3.datePicker($("x-date"));
		A3.datePicker($("x-due"));
		try {
			const boot = await A3.call("a3_retail.api.expenses.bootstrap");
			state.categories = boot.categories || [];
			state.sources = boot.sources || [];
			state.modes = boot.modes || [];
			state.canAddCategory = !!boot.can_add_category;
			state.canCreateItem = !!boot.can_create_item;
			state.uoms = boot.uoms || [];
			state.gstRates = boot.gst_rates || [];
			state.itc = boot.itc_options || [];

			$("x-category").innerHTML = categoryOptions();
			$("x-source").innerHTML = state.sources.map((s) =>
				`<option value="${esc(s.account)}">${esc(s.label)}</option>`).join("");
			$("x-mode").innerHTML = '<option value="">Select</option>'
				+ state.modes.map((m) =>
					`<option value="${esc(m)}">${esc(m)}</option>`).join("");
			$("x-prefix").value = boot.series.prefix;
			$("x-number").value = boot.series.number;
			$("x-newcat").hidden = !state.canAddCategory;
			$("x-newitem").hidden = !state.canCreateItem;
			$("ni-uom").innerHTML = state.uoms.map((u) =>
				`<option value="${esc(u)}"${u === "Nos" ? " selected" : ""}>${esc(u)}</option>`)
				.join("");
			$("ni-gst").innerHTML = '<option value="">None</option>'
				+ state.gstRates.filter((r) => r).map((r) =>
					`<option value="${r}">${r}%</option>`).join("");
			$("ni-itc").innerHTML = state.itc.map((o) =>
				`<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
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
		paintCount();
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
				paintCount();
			}));
		paintCount();
	}

	/** What is ticked, beside the heading — the Add button is up there now and
	 *  the tick may be forty rows below it. */
	function paintCount() {
		const n = state.chosen.size;
		$("x-count").textContent = n ? `${n} picked` : "";
		$("x-pick-add").disabled = !n;
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
	function askCategory() {
		$("nc-name").value = "";
		$("nc-msg").textContent = "";
		$("x-newcat-modal").hidden = false;
		setTimeout(() => $("nc-name").focus(), 60);
	}

	async function saveCategory() {
		const label = $("nc-name").value.trim();
		if (!label) return ($("nc-msg").textContent = "Give the category a name.");
		$("nc-save").disabled = true;
		try {
			const made = await A3.call("a3_retail.api.expenses.add_category", { label });
			if (made.created) {
				state.categories.push({ account: made.account, label: made.label });
				state.categories.sort((a, b) => a.label.localeCompare(b.label));
			}
			$("x-category").innerHTML = categoryOptions(made.account);
			$("x-newcat-modal").hidden = true;
			A3.toast(made.created ? `Added ${made.label}.`
				: `${made.label} was already there.`, "ok");
		} catch (error) {
			$("nc-msg").textContent = error.message || "Could not add that category.";
		} finally {
			$("nc-save").disabled = false;
		}
	}

	function askItem() {
		$("ni-name").value = $("x-q").value.trim();
		$("ni-rate").value = 0;
		$("ni-hsn").value = "";
		$("ni-gst").value = "";
		$("ni-taxincl").value = "0";
		$("ni-msg").textContent = "";
		document.querySelector('input[name="ni-kind"][value="Product"]').checked = true;
		$("x-newitem-modal").hidden = false;
		setTimeout(() => $("ni-name").focus(), 60);
	}

	async function saveItem() {
		const name = $("ni-name").value.trim();
		if (!name) return ($("ni-msg").textContent = "Give it a name.");
		$("ni-save").disabled = true;
		try {
			const made = await A3.call("a3_retail.api.expenses.create_item", {
				payload: {
					item_name: name,
					kind: document.querySelector('input[name="ni-kind"]:checked').value,
					rate: Number($("ni-rate").value) || 0,
					tax_included: $("ni-taxincl").value === "1" ? 1 : 0,
					uom: $("ni-uom").value,
					hsn: $("ni-hsn").value.trim(),
					gst_rate: Number($("ni-gst").value) || 0,
					itc: $("ni-itc").value,
					expense_account: $("x-category").value,
				},
			});
			$("x-newitem-modal").hidden = true;
			state.chosen.add(made.item_code);
			await search(name);
			A3.toast(made.created ? `Added ${made.item_name}.`
				: `${made.item_name} was already there.`, "ok");
		} catch (error) {
			$("ni-msg").textContent = error.message || "Could not add that item.";
		} finally {
			$("ni-save").disabled = false;
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
					employee: state.employee || "",
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
			const asWhat = { "Supplier Invoice": "supplier invoice",
			                 "Employee Claim": "employee claim",
			                 "Journal": "journal entry" }[result.posted_as] || "entry";
			say(`${result.expense} saved as a ${asWhat} (${result.posted}) — `
				+ money(result.amount)
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
		$("nc-save").addEventListener("click", saveCategory);
		$("ni-save").addEventListener("click", saveItem);
		document.querySelectorAll("[data-close-item]").forEach((n) =>
			n.addEventListener("click", () => { $("x-newitem-modal").hidden = true; }));
		document.querySelectorAll("[data-close-cat]").forEach((n) =>
			n.addEventListener("click", () => { $("x-newcat-modal").hidden = true; }));
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

		const staff = $("x-employee");
		const staffHits = $("x-employee-hits");
		staff.addEventListener("input", async () => {
			state.employee = null;
			showRoute();
			const q = staff.value.trim();
			if (q.length < 2) { staffHits.innerHTML = ""; return; }
			const rows = await A3.call("a3_retail.api.expenses.search_employees",
				{ query: q, limit: 6 }).catch(() => []);
			staffHits.innerHTML = (rows || []).map((r) =>
				`<button type="button" class="w-hit" data-name="${esc(r.name)}"
					data-label="${esc(r.employee_name)}">${esc(r.employee_name)}${
					r.designation ? ` · ${esc(r.designation)}` : ""}</button>`).join("");
		});
		staffHits.addEventListener("mousedown", (event) => {
			const hit = event.target.closest(".w-hit");
			if (!hit) return;
			event.preventDefault();
			state.employee = hit.dataset.name;
			staff.value = hit.dataset.label;
			staffHits.innerHTML = "";
			showRoute();
		});
		staff.addEventListener("blur", () =>
			setTimeout(() => { staffHits.innerHTML = ""; }, 120));

		$("x-gst").addEventListener("change", showRoute);
		showRoute();
	}

	/** Say which of the three documents this will become, before it is saved. */
	function showRoute() {
		const gst = $("x-gst").checked;
		const staff = !!state.employee;
		const line = $("x-route");
		if (gst && staff) {
			line.textContent = "A GST bill cannot also be an employee claim —"
				+ " clear one of them.";
			line.className = "xp-route is-bad";
			return;
		}
		line.className = "xp-route";
		line.textContent = gst
			? "Saves as the supplier's purchase invoice, so the GST can be claimed."
			: staff
				? "Saves as an employee claim — what the shop owes "
				  + $("x-employee").value.trim() + " back."
				: "Saves as a journal entry, straight into this branch's books.";
	}

	document.addEventListener("DOMContentLoaded", start);
})();
