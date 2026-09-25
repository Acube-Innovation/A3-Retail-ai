// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Cash and bank, for one branch.
 *
 * The closing-time question: how much is in the drawer, how much reached the
 * bank, and what moved today. Every figure is this branch's own — the company
 * balance belongs to head office and would tell a cashier nothing useful.
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

	const state = { branch: "", accounts: [], saving: false };

	function say(text, kind) {
		const toast = $("toast");
		toast.textContent = text || "";
		toast.className = "toast" + (kind ? " " + kind : "");
		toast.hidden = !text;
		if (text) setTimeout(() => { toast.hidden = true; }, 4500);
	}

	// ------------------------------------------------------------- balances
	async function load() {
		try {
			const [sums, txns] = await Promise.all([
				A3.call("a3_retail.api.cashbank.summary"),
				A3.call("a3_retail.api.cashbank.transactions",
					{ limit: 50, account: $("filter-account").value || null }),
			]);
			state.accounts = [...(sums.cash || []), ...(sums.banks || [])];
			paintTiles(sums);
			paintAccounts(sums);
			paintRows(txns.rows || []);
			fillPickers(sums);
		} catch (error) {
			$("accounts").innerHTML =
				`<p class="muted">${esc(error.message || "Could not load cash and bank.")}</p>`;
		}
	}

	function paintTiles(sums) {
		$("tiles").innerHTML = `
			<div class="ctile"><span class="ctile-label">In the drawer</span>
				<strong class="ctile-value">${money(sums.cash_total)}</strong></div>
			<div class="ctile"><span class="ctile-label">At the bank</span>
				<strong class="ctile-value">${money(sums.bank_total)}</strong></div>
			<div class="ctile"><span class="ctile-label">Held by this branch</span>
				<strong class="ctile-value">${money(sums.total)}</strong></div>`;
	}

	function paintAccounts(sums) {
		const row = (a, kind) => `
			<tr>
				<td>${esc(a.label)}</td>
				<td><span class="pill">${kind}</span></td>
				<td class="num">${money(a.balance)}</td>
			</tr>`;
		const cash = (sums.cash || []).map((a) => row(a, "Cash")).join("");
		const banks = (sums.banks || []).map((a) => row(a, "Bank")).join("");
		$("accounts").innerHTML = (cash || banks)
			? `<table class="bill-table">
					<thead><tr><th>Account</th><th>Type</th><th class="num">This branch</th></tr></thead>
					<tbody>${cash}${banks}</tbody>
				</table>
				<p class="muted">Balances count only what this branch banked or took in.</p>`
			: '<p class="muted">No cash or bank account is set up for this company yet.</p>';
	}

	function paintRows(rows) {
		if (!rows.length) {
			$("rows").innerHTML = '<p class="muted">Nothing has moved yet.</p>';
			return;
		}
		$("rows").innerHTML = `
			<table class="bill-table">
				<thead><tr>
					<th>Date</th><th>Account</th><th>Document</th><th>Detail</th>
					<th class="num">In</th><th class="num">Out</th>
				</tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td>${esc(r.posting_date)}</td>
						<td>${esc(r.account_name)}</td>
						<td>${esc(r.voucher_no)}</td>
						<td>${esc((r.remarks || r.against || "").slice(0, 60))}</td>
						<td class="num">${r.debit ? money(r.debit) : "—"}</td>
						<td class="num">${r.credit ? money(r.credit) : "—"}</td>
					</tr>`).join("")}
				</tbody>
			</table>`;
	}

	function fillPickers(sums) {
		const options = (list) => list
			.map((a) => `<option value="${esc(a.account)}">${esc(a.label)}</option>`).join("");
		// Cash goes to the bank, so the drawer is the natural source and a bank
		// account the natural destination — but neither list is locked down, since
		// a branch may also move money the other way to float the till.
		$("d-from").innerHTML = options(state.accounts);
		$("d-to").innerHTML = options(state.accounts);
		if ((sums.cash || []).length) $("d-from").value = sums.cash[0].account;
		if ((sums.banks || []).length) $("d-to").value = sums.banks[0].account;

		const keep = $("filter-account").value;
		$("filter-account").innerHTML = '<option value="">All accounts</option>'
			+ options(state.accounts);
		$("filter-account").value = keep;
	}

	// ------------------------------------------------------------- the deposit
	function open() {
		$("d-amount").value = "";
		$("d-note").value = "";
		$("d-date").value = new Date().toISOString().slice(0, 10);
		$("d-msg").textContent = "";
		$("deposit-modal").hidden = false;
	}

	const close = () => { $("deposit-modal").hidden = true; };

	async function save() {
		if (state.saving) return;
		const amount = Number($("d-amount").value) || 0;
		if (amount <= 0) {
			$("d-msg").textContent = "Enter how much was banked.";
			$("d-msg").className = "msg error";
			return;
		}
		state.saving = true;
		$("d-save").disabled = true;
		try {
			const result = await A3.call("a3_retail.api.cashbank.deposit", {
				payload: {
					amount,
					from_account: $("d-from").value,
					to_account: $("d-to").value,
					date: $("d-date").value,
					note: $("d-note").value.trim(),
				},
			});
			say(`${money(result.amount)} moved from ${result.from} into ${result.to}.`, "ok");
			close();
			load();
		} catch (error) {
			$("d-msg").textContent = error.message || "Could not record it.";
			$("d-msg").className = "msg error";
		} finally {
			state.saving = false;
			$("d-save").disabled = false;
		}
	}

	function start(options) {
		state.branch = options.branch;
		$("new-deposit").addEventListener("click", open);
		$("d-cancel").addEventListener("click", close);
		$("d-save").addEventListener("click", save);
		$("refresh").addEventListener("click", load);
		$("filter-account").addEventListener("change", load);
		load();
	}

	window.CASHBANK = { start };
})();
