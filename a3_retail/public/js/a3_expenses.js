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

	const state = { categories: [], sources: [], work: null };

	function say(text, kind) {
		$("work-msg").textContent = text || "";
		$("work-msg").className = "msg" + (kind ? " " + kind : "");
	}

	async function load() {
		try {
			const [data, cats, srcs] = await Promise.all([
				A3.call("a3_retail.api.expenses.recent", { limit: 40 }),
				A3.call("a3_retail.api.expenses.categories"),
				A3.call("a3_retail.api.expenses.paid_from"),
			]);
			state.categories = cats || [];
			state.sources = srcs || [];
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
				'<tr><td colspan="5">Nothing recorded here yet.</td></tr>';
			return;
		}

		$("rows").innerHTML = rows.map((r) => `
			<tr>
				<td>${esc(r.posting_date || "")}</td>
				<td>${esc(r.category_label || "")}</td>
				<td>${esc((r.user_remark || "").split(" — ")[0])}</td>
				<td class="num">${esc(money(r.amount))}</td>
				<td><span class="pill">${esc(r.name)}</span></td>
			</tr>`).join("");
	}

	function openForm() {
		if (!state.categories.length) {
			return A3.toast("No expense categories exist yet. Ask head office to add one.", "error");
		}
		const today = new Date().toISOString().slice(0, 10);
		$("work-body").innerHTML = `
			<div class="field-grid">
				<label class="field"><span>Amount</span>
					<div class="input-rupee"><span>₹</span>
						<input id="e-amount" type="number" min="0" step="1" placeholder="0" autofocus>
					</div></label>
				<label class="field"><span>Date</span>
					<input id="e-date" type="date" value="${today}" max="${today}"></label>
			</div>
			<div class="field-grid">
				<label class="field"><span>Spent on</span>
					<select id="e-category">${state.categories.map((c) =>
						`<option value="${esc(c.account)}">${esc(c.label)}</option>`).join("")}</select></label>
				<label class="field"><span>Paid from</span>
					<select id="e-source">${state.sources.map((s) =>
						`<option value="${esc(s.account)}">${esc(s.label)}</option>`).join("")}</select></label>
			</div>
			<label class="field"><span>Note</span>
				<input id="e-note" placeholder="What it was for"></label>`;

		say("");
		$("work-modal").hidden = false;
		state.work = async () => {
			const amount = Number($("e-amount").value) || 0;
			if (amount <= 0) throw new Error("Enter how much was spent.");
			const result = await A3.call("a3_retail.api.expenses.create", {
				payload: {
					amount,
					date: $("e-date").value,
					category: $("e-category").value,
					paid_from: $("e-source").value,
					note: $("e-note").value.trim(),
				},
			});
			A3.toast(`${money(result.amount)} recorded against ${result.category}.`, "ok");
			load();
		};
		setTimeout(() => $("e-amount").focus(), 60);
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
