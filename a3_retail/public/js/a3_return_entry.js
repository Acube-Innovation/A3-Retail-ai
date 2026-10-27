// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Raising a credit note — /retail/return_entry.
 *
 * A customer comes back with a phone and the bill. The counter finds the bill,
 * says what is coming back, and either hands the money over or leaves it on the
 * customer's account. The quantity that can come back is whatever has not
 * already been returned, so the same handset cannot be credited twice.
 *
 * Reading back what has come back is the Sales Return list; this page only
 * writes, and goes back to that list once it has.
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

	const day = (value) => !value ? "" : new Date(value + "T00:00:00")
		.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

	const state = { branch: "", bill: null, lines: [], saving: false };
	let billTimer = null;

	function say(text, kind) {
		const toast = $("toast");
		toast.textContent = A3.plain(text || "");
		toast.className = "toast" + (kind ? " " + kind : "");
		toast.hidden = !text;
		if (text) setTimeout(() => { toast.hidden = true; }, 5000);
	}

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
				<span class="ret-hit-amt">${esc(money(b.payable))}</span></button>`).join("")
			: '<p class="muted ret-none">No bill of this branch matches that.</p>';
	}

	async function pickBill(name) {
		$("bill-hits").innerHTML = "";
		try {
			const data = await A3.call("a3_retail.api.returns.bill_lines", { invoice: name });
			state.bill = data;
			state.lines = data.lines.map((l) => ({ ...l, returning: 0 }));
			$("bill-q").value = "";
			$("bill-picked").hidden = false;
			$("bill-picked").innerHTML = `
				<div class="ret-picked-main">
					<b>${esc(data.invoice)}</b>
					<span>${esc(data.customer_name)} · ${esc(day(data.posting_date))}</span>
				</div>
				<div class="ret-picked-amt">${esc(money(data.payable))}</div>
				<button class="btn btn-quiet btn-sm" id="bill-clear">Change bill</button>`;
			$("bill-clear").addEventListener("click", reset);
			$("lines-panel").hidden = false;
			paintLines();
		} catch (error) {
			say(error.message || "Could not open that bill.", "error");
		}
	}

	function paintLines() {
		const body = $("lines").querySelector("tbody");
		body.innerHTML = state.lines.map((l, i) => `
			<tr${l.returning > 0 ? ' class="is-returning"' : ""}>
				<td>${esc(l.item_name)}</td>
				<td class="num">${l.qty}</td>
				<td class="num">${l.returned || "—"}</td>
				<td class="num"><input class="back" data-i="${i}" type="number" min="0" step="1"
					max="${l.can_return}" value="${l.returning || ""}"
					placeholder="0" ${l.can_return ? "" : "disabled"}></td>
				<td class="num">${esc(money(l.rate))}</td>
				<td class="num">${esc(money((l.returning || 0) * l.rate))}</td>
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
			paintTotals();
			n.closest("tr").classList.toggle("is-returning", line.returning > 0);
			n.closest("tr").lastElementChild.textContent = money(line.returning * line.rate);
		}));
		paintTotals();
	}

	function paintTotals() {
		const total = state.lines.reduce((sum, l) => sum + (l.returning || 0) * l.rate, 0);
		const count = state.lines.filter((l) => l.returning > 0).length;
		$("r-lines").textContent = count;
		$("r-total").textContent = money(total);
		$("r-save").disabled = !count;
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
			// Back to the list, which is where the counter looks next.
			setTimeout(() => { window.location.href = "/retail/returns"; }, 1400);
		} catch (error) {
			note(error.message || "Could not raise the credit note.", "error");
			state.saving = false;
			$("r-save").disabled = false;
		}
	}

	function reset() {
		state.bill = null;
		state.lines = [];
		$("bill-q").value = "";
		$("bill-picked").hidden = true;
		$("bill-picked").innerHTML = "";
		$("lines-panel").hidden = true;
		$("r-refund").value = "";
		$("r-reason").value = "";
		$("r-lines").textContent = "0";
		$("r-total").textContent = money(0);
		$("r-save").disabled = true;
		note("");
		$("bill-q").focus();
	}

	async function start(options) {
		state.branch = options.branch;
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
			state.lines.forEach((l) => { l.returning = l.can_return; });
			paintLines();
		});
		$("r-save").addEventListener("click", save);
	}

	window.RETURN_ENTRY = { start };
})();
