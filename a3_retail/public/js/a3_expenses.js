// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Branch petty cash.
 *
 * Sixty of these a month in a shop this size, most of them under two hundred
 * rupees — so the form is four fields and opens with today's date already in it.
 */
(function () {
	const $ = (id) => document.getElementById(id);
	const money = (v) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v || 0);

	function esc(v) {
		const n = document.createElement("div");
		n.textContent = v == null ? "" : String(v);
		return n.innerHTML;
	}

	const state = { categories: [], sources: [], modes: [], work: null,
	                canAddCategory: false, lines: [], supplier: null };

	function say(text, kind) {
		$("work-msg").textContent = text || "";
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	async function load() {
		try {
			const [data, cats, srcs, mayAdd, modes] = await Promise.all([
				A3.call("a3_retail.api.expenses.recent", { limit: 40 }),
				A3.call("a3_retail.api.expenses.categories"),
				A3.call("a3_retail.api.expenses.paid_from"),
				A3.call("a3_retail.api.expenses.can_add_category"),
				A3.call("a3_retail.api.expenses.modes"),
			]);
			state.categories = cats || [];
			state.sources = srcs || [];
			state.canAddCategory = !!mayAdd;
			state.modes = modes || [];
			paint(data);
		} catch (error) {
			$("rows").innerHTML =
				`<tr><td colspan="5">${esc(error.message || "Could not load expenses.")}</td></tr>`;
		}
	}

	function paint(data) {
		const rows = data.rows || [];
		const spentThisMonth = data.month_total || 0;
		const count = rows.length;
		const biggest = rows.reduce((m, r) => Math.max(m, r.amount || 0), 0);

		$("kpis").innerHTML = [
			["This month", money(spentThisMonth), "neutral"],
			["Entries shown", String(count), "neutral"],
			["Largest", money(biggest), "neutral"],
		].map(([label, value]) => `
			<div class="ctile">
				<div class="ctile-value">${esc(value)}</div>
				<div class="ctile-label">${esc(label)}</div>
			</div>`).join("");

		if (!rows.length) {
			$("rows").innerHTML =
				'<tr><td colspan="7">Nothing recorded here yet.</td></tr>';
			return;
		}

		$("rows").innerHTML = rows.map((r) => `
			<tr${r.docstatus === 0 ? ' class="is-draft"' : ""}>
				<td>${esc(r.posting_date || "")}</td>
				<td>${esc(r.category_label || "")}</td>
				<td>${esc(r.paid_to_label || "")}</td>
				<td>${esc(r.notes || "")}</td>
				<td class="num">${esc(money(r.amount))}</td>
				<td class="num">${r.outstanding_amount > 0
					? esc(money(r.outstanding_amount)) : ""}</td>
				<td><span class="pill">${esc(r.name)}</span></td>
			</tr>`).join("");
	}

	const categoryOptions = (selected) => state.categories.map((c) =>
		`<option value="${esc(c.account)}"${c.account === selected ? " selected" : ""}>${
			esc(c.label)}</option>`).join("");

	/** A shop has its own words for what it spends on. Managers may add one. */
	async function askCategory() {
		const label = (window.prompt("What should the new category be called?") || "").trim();
		if (!label) return;
		try {
			const made = await A3.call("a3_retail.api.expenses.add_category", { label });
			if (made.created) {
				state.categories.push({ account: made.account, label: made.label });
				state.categories.sort((a, b) => a.label.localeCompare(b.label));
			}
			$("e-category").innerHTML = categoryOptions(made.account);
			A3.toast(made.created ? `Added ${made.label}.`
				: `${made.label} was already there.`, "ok");
		} catch (error) {
			say(error.message || "Could not add that category.", "error");
		}
	}

	function openForm() {
		if (!state.categories.length) {
			return A3.toast("No expense categories exist yet. Add one with the + button.",
				"error");
		}
		const today = new Date().toLocaleDateString("en-CA");
		state.lines = [blankLine()];
		state.supplier = null;

		$("work-body").innerHTML = `
			<div class="field-grid three">
				<label class="field"><span>Date</span>
					<input id="e-date" type="date" value="${today}" max="${today}"></label>
				<label class="field"><span>Spent on</span>
					<div class="field-with-add">
						<select id="e-category">${categoryOptions()}</select>
						${state.canAddCategory
							? '<button type="button" class="btn btn-quiet" id="e-newcat"'
							  + ' title="Add a category">+</button>' : ""}
					</div></label>
				<label class="field"><span>Bill / slip no.</span>
					<input id="e-ref" placeholder="Optional"></label>
			</div>

			<div class="field-grid">
				<label class="field"><span>Paid to</span>
					<input id="e-paidto" placeholder="Name, or search a supplier"
					       autocomplete="off">
					<div class="w-hits" id="e-supplier-hits"></div></label>
				<label class="field"><span>Payment mode</span>
					<select id="e-mode"><option value="">—</option>${state.modes.map((m) =>
						`<option value="${esc(m)}">${esc(m)}</option>`).join("")}</select></label>
			</div>

			<div class="exp-lines">
				<table class="bill-table exp-table">
					<thead><tr>
						<th>Item</th><th class="num">Qty</th><th class="num">Rate</th>
						<th class="num">Amount</th><th></th>
					</tr></thead>
					<tbody id="e-lines"></tbody>
				</table>
				<div class="exp-line-actions">
					<button type="button" class="btn btn-quiet" id="e-addline">+ Add line</button>
					<button type="button" class="btn btn-quiet" id="e-newitem">
						+ Create new item</button>
				</div>
			</div>

			<div class="field-grid three">
				<label class="field"><span>Discount</span>
					<div class="input-rupee"><span>₹</span>
						<input id="e-discount" type="number" min="0" step="0.01" value="0">
					</div></label>
				<label class="field"><span>Paid now</span>
					<div class="input-rupee"><span>₹</span>
						<input id="e-paid" type="number" min="0" step="0.01"
						       placeholder="All of it"></div></label>
				<label class="field"><span>Paid from</span>
					<select id="e-source">${state.sources.map((x) =>
						`<option value="${esc(x.account)}">${esc(x.label)}</option>`)
						.join("")}</select></label>
			</div>

			<div class="field-grid">
				<label class="field"><span>Note</span>
					<input id="e-note" placeholder="What it was for"></label>
				<label class="field" id="e-due-wrap" hidden><span>Due date</span>
					<input id="e-due" type="date"></label>
			</div>

			<div class="exp-totals" id="e-totals"></div>`;

		paintLines();
		wireForm();
		say("");
		$("work-modal").hidden = false;
		setTimeout(() => {
			const first = document.querySelector("#e-lines .exp-item");
			if (first) first.focus();
		}, 60);

		state.work = async () => {
			const lines = state.lines.filter((l) => l.description && l.rate > 0);
			if (!lines.length) throw new Error("Add what the money went on.");
			const result = await A3.call("a3_retail.api.expenses.create", {
				payload: {
					date: $("e-date").value,
					category: $("e-category").value,
					reference_no: $("e-ref").value.trim(),
					supplier: state.supplier,
					paid_to: state.supplier ? "" : $("e-paidto").value.trim(),
					mode_of_payment: $("e-mode").value,
					paid_from: $("e-source").value,
					discount: Number($("e-discount").value) || 0,
					paid_amount: $("e-paid").value === "" ? null
						: Number($("e-paid").value) || 0,
					due_date: $("e-due").value || null,
					note: $("e-note").value.trim(),
					items: lines.map((l) => ({ item_code: l.item_code,
						description: l.description, qty: l.qty, rate: l.rate })),
				},
			});
			A3.toast(`${money(result.amount)} recorded against ${result.category}`
				+ (result.outstanding > 0
					? `, ${money(result.outstanding)} still owed.` : "."), "ok");
			load();
		};
	}

	const blankLine = () => ({ item_code: null, description: "", qty: 1, rate: 0 });

	function paintLines() {
		$("e-lines").innerHTML = state.lines.map((l, i) => `
			<tr data-i="${i}">
				<td><input class="exp-item" value="${esc(l.description)}"
				           placeholder="Search or type what it was"
				           autocomplete="off">
					<div class="w-hits" data-hits="${i}"></div></td>
				<td class="num"><input class="exp-qty num" type="number" min="0"
				                       step="0.01" value="${l.qty}"></td>
				<td class="num"><input class="exp-rate num" type="number" min="0"
				                       step="0.01" value="${l.rate || ""}"></td>
				<td class="num">${esc(money(l.qty * l.rate))}</td>
				<td>${state.lines.length > 1
					? '<button type="button" class="drop" aria-label="Remove">×</button>' : ""}</td>
			</tr>`).join("");
		wireLines();
		paintTotals();
	}

	function paintTotals() {
		const total = state.lines.reduce((s, l) => s + (l.qty * l.rate), 0);
		const discount = Number($("e-discount") && $("e-discount").value) || 0;
		const grand = Math.max(total - discount, 0);
		const paidBox = $("e-paid");
		const paid = !paidBox || paidBox.value === "" ? grand : Number(paidBox.value) || 0;
		const owed = Math.round((grand - paid) * 100) / 100;

		// A balance has to be owed to somebody, so the date only matters then.
		if ($("e-due-wrap")) $("e-due-wrap").hidden = owed <= 0;

		$("e-totals").innerHTML = `
			<div class="tr"><span>Total</span><span>${esc(money(total))}</span></div>
			${discount ? `<div class="tr"><span>Discount</span>
				<span>− ${esc(money(discount))}</span></div>` : ""}
			<div class="tr grand"><span>Grand total</span>
				<span>${esc(money(grand))}</span></div>
			${owed > 0 ? `<div class="tr owed"><span>Still owed</span>
				<span>${esc(money(owed))}</span></div>` : ""}`;
	}

	function wireLines() {
		$("e-lines").querySelectorAll("tr").forEach((tr) => {
			const i = Number(tr.dataset.i);
			const line = state.lines[i];
			const itemBox = tr.querySelector(".exp-item");
			const hits = tr.querySelector("[data-hits]");

			itemBox.addEventListener("input", async () => {
				line.description = itemBox.value;
				line.item_code = null;
				const q = itemBox.value.trim();
				if (q.length < 2) { hits.innerHTML = ""; return; }
				const rows = await A3.call("a3_retail.api.expenses.search_items",
					{ query: q, limit: 8 }).catch(() => []);
				hits.innerHTML = (rows || []).map((r) =>
					`<button type="button" class="w-hit" data-code="${esc(r.item_code)}"
					         data-name="${esc(r.item_name)}">${esc(r.item_name)}</button>`)
					.join("");
			});
			// mousedown, because blur would tear the list down before a click lands.
			hits.addEventListener("mousedown", (event) => {
				const hit = event.target.closest(".w-hit");
				if (!hit) return;
				event.preventDefault();
				line.item_code = hit.dataset.code;
				line.description = hit.dataset.name;
				itemBox.value = hit.dataset.name;
				hits.innerHTML = "";
				const rate = tr.querySelector(".exp-rate");
				if (!line.rate) rate.focus();
			});
			itemBox.addEventListener("blur", () =>
				setTimeout(() => { hits.innerHTML = ""; }, 120));

			tr.querySelector(".exp-qty").addEventListener("input", (e) => {
				line.qty = Number(e.target.value) || 0;
				paintAmount(tr, line);
			});
			tr.querySelector(".exp-rate").addEventListener("input", (e) => {
				line.rate = Number(e.target.value) || 0;
				paintAmount(tr, line);
			});
			const x = tr.querySelector(".drop");
			if (x) x.addEventListener("click", () => {
				state.lines.splice(i, 1);
				paintLines();
			});
		});
	}

	/** Only the amount cell changes as you type, so the caret stays where it is. */
	function paintAmount(tr, line) {
		tr.children[3].textContent = money(line.qty * line.rate);
		paintTotals();
	}

	function wireForm() {
		if (state.canAddCategory) $("e-newcat").addEventListener("click", askCategory);
		$("e-addline").addEventListener("click", () => {
			state.lines.push(blankLine());
			paintLines();
			const boxes = $("e-lines").querySelectorAll(".exp-item");
			if (boxes.length) boxes[boxes.length - 1].focus();
		});
		$("e-newitem").addEventListener("click", askItem);
		$("e-discount").addEventListener("input", paintTotals);
		$("e-paid").addEventListener("input", paintTotals);

		const paidTo = $("e-paidto");
		const hits = $("e-supplier-hits");
		paidTo.addEventListener("input", async () => {
			state.supplier = null;
			const q = paidTo.value.trim();
			if (q.length < 2) { hits.innerHTML = ""; return; }
			const rows = await A3.call("a3_retail.api.expenses.search_suppliers",
				{ query: q, limit: 6 }).catch(() => []);
			hits.innerHTML = (rows || []).map((r) =>
				`<button type="button" class="w-hit" data-name="${esc(r.name)}"
				         data-label="${esc(r.supplier_name)}">${esc(r.supplier_name)}
				 </button>`).join("");
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

	/** Something the shop buys but does not stock. */
	async function askItem() {
		const name = (window.prompt("What is the new item called?") || "").trim();
		if (!name) return;
		try {
			const made = await A3.call("a3_retail.api.expenses.create_item", {
				payload: { item_name: name, expense_account: $("e-category").value },
			});
			const line = state.lines.find((l) => !l.description) || blankLine();
			if (!state.lines.includes(line)) state.lines.push(line);
			line.item_code = made.item_code;
			line.description = made.item_name;
			paintLines();
			A3.toast(made.created ? `Added ${made.item_name}.`
				: `${made.item_name} was already there.`, "ok");
		} catch (error) {
			say(error.message || "Could not add that item.", "error");
		}
	}

	document.addEventListener("DOMContentLoaded", () => {
		$("new-expense").addEventListener("click", openForm);
		document.querySelectorAll("[data-close]").forEach((n) =>
			n.addEventListener("click", () => { $("work-modal").hidden = true; }));
		$("work-go").addEventListener("click", async () => {
			if (!state.work) return;
			$("work-go").disabled = true;
			say("Saving…");
			try {
				await state.work();
				$("work-modal").hidden = true;
			} catch (error) {
				say(error.message || "Could not save that expense.", "error");
			} finally {
				$("work-go").disabled = false;
			}
		});
		load();
	});
})();
