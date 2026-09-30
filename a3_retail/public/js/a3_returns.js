// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Sales returns.
 *
 * A customer comes back with a phone and the bill. The counter finds the bill,
 * says what is coming back, and either hands the money over or leaves it on the
 * customer's account. The quantity that can come back is whatever has not
 * already been returned, so the same handset cannot be credited twice.
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

	const state = { branch: "", bill: null, lines: [], saving: false };
	let billTimer = null;

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

	// ------------------------------------------------------------- the bill
	async function findBills() {
		const q = $("bill-q").value.trim();
		if (q.length < 2) return ($("bill-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.returns.find_bills", { query: q, limit: 8 });
		$("bill-hits").innerHTML = hits.length
			? hits.map((b) => `<button class="pick" data-name="${esc(b.name)}">
				${esc(b.name)} · ${esc(b.customer_name)} · ${esc(b.posting_date)}
				· ${money(b.payable)}</button>`).join("")
			: '<p class="muted">No bill of this branch matches that.</p>';
	}

	async function pickBill(name) {
		$("bill-hits").innerHTML = "";
		try {
			const data = await A3.call("a3_retail.api.returns.bill_lines", { invoice: name });
			state.bill = data;
			state.lines = data.lines.map((l) => ({ ...l, returning: 0 }));
			$("bill-q").value = name;
			$("bill-picked").textContent =
				`${data.customer_name} · ${data.posting_date} · bill ${money(data.payable)}`;
			$("lines-panel").hidden = false;
			paintLines();
		} catch (error) {
			say(error.message || "Could not open that bill.", "error");
		}
	}

	function paintLines() {
		const body = $("lines").querySelector("tbody");
		body.innerHTML = state.lines.map((l, i) => `
			<tr>
				<td>${esc(l.item_name)}</td>
				<td class="num">${l.qty}</td>
				<td class="num">${l.returned || "—"}</td>
				<td><input class="back" data-i="${i}" type="number" min="0" step="1"
					max="${l.can_return}" value="${l.returning || ""}"
					${l.can_return ? "" : "disabled"}></td>
				<td class="num">${money(l.rate)}</td>
				<td class="num">${money((l.returning || 0) * l.rate)}</td>
			</tr>`).join("");

		body.querySelectorAll(".back").forEach((n) => n.addEventListener("input", () => {
			const line = state.lines[Number(n.dataset.i)];
			const asked = Number(n.value) || 0;
			// The box will not let more come back than went out and has not
			// already returned — said here rather than after a failed save.
			if (asked > line.can_return) {
				say(`Only ${line.can_return} of ${line.item_name} can still come back.`, "error");
				n.value = line.can_return;
			}
			line.returning = Math.min(asked, line.can_return);
			paintLines();
		}));

		const total = state.lines.reduce((sum, l) => sum + (l.returning || 0) * l.rate, 0);
		const count = state.lines.filter((l) => l.returning > 0).length;
		$("r-lines").textContent = count;
		$("r-total").textContent = money(total);
		$("r-save").disabled = !count;
	}

	// ------------------------------------------------------------ the notes
	async function load() {
		try {
			const data = await A3.call("a3_retail.api.returns.recent", { limit: 30 });
			paint(data.rows || []);
		} catch (error) {
			$("rows").innerHTML =
				`<p class="muted">${esc(error.message || "Could not load credit notes.")}</p>`;
		}
	}

	function paint(rows) {
		if (!rows.length) {
			$("rows").innerHTML = '<p class="muted">No goods have come back yet.</p>';
			return;
		}
		$("rows").innerHTML = `
			<table class="bill-table">
				<thead><tr><th>Credit note</th><th>Customer</th><th>Date</th>
					<th>Against</th><th class="num">Amount</th></tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td>${esc(r.name)}</td>
						<td>${esc(r.customer_name)}</td>
						<td>${esc(r.posting_date)}</td>
						<td>${esc(r.return_against || "—")}</td>
						<td class="num">${money(r.amount)}</td>
					</tr>`).join("")}
				</tbody>
			</table>`;
	}

	// ---------------------------------------------------------------- save
	async function save() {
		if (state.saving || !state.bill) return;
		const coming = state.lines.filter((l) => l.returning > 0);
		if (!coming.length) return note("Say what is coming back.", "error");

		state.saving = true;
		$("r-save").disabled = true;
		note("Raising the credit note…");
		try {
			const result = await A3.call("a3_retail.api.returns.create", {
				payload: {
					invoice: state.bill.invoice,
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
			note(`${result.credit_note} raised — ${money(result.amount)} back`
				+ (result.refunded ? `, ${money(result.refunded)} refunded` : "")
				+ (result.credit_left ? `, ${money(result.credit_left)} left as credit` : "")
				+ ".", "ok");
			window.open(result.print_url, "_blank");
			reset();
			load();
		} catch (error) {
			note(error.message || "Could not raise the credit note.", "error");
		} finally {
			state.saving = false;
			$("r-save").disabled = false;
		}
	}

	function reset() {
		state.bill = null;
		state.lines = [];
		$("bill-q").value = "";
		$("bill-picked").textContent = "";
		$("lines-panel").hidden = true;
		$("r-refund").value = "";
		$("r-reason").value = "";
		$("r-lines").textContent = "0";
		$("r-total").textContent = money(0);
		$("r-save").disabled = true;
	}

	async function start(options) {
		state.branch = options.branch;
		$("r-date").value = new Date().toISOString().slice(0, 10);

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
		$("r-save").addEventListener("click", save);
		$("refresh").addEventListener("click", load);
		load();
	}

	window.RETURNS = { start };
})();
