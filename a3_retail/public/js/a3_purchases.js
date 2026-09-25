// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Branch purchase entry.
 *
 * A distributor's rep walks in with stock and a bill, so the form is the bill:
 * who it is from, their bill number, what came in and at what cost, and whether
 * they were paid on the spot. One save records the liability and takes the goods
 * into the branch store.
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

	const state = { branch: "", supplier: null, lines: [], modes: [], saving: false };
	let supplierTimer = null;
	let itemTimer = null;

	function say(text, kind) {
		const toast = $("toast");
		toast.textContent = text || "";
		toast.className = "toast" + (kind ? " " + kind : "");
		toast.hidden = !text;
		if (text) setTimeout(() => { toast.hidden = true; }, 4000);
	}

	// ------------------------------------------------------------- the list
	async function load() {
		try {
			const data = await A3.call("a3_retail.api.purchases.recent", { limit: 30 });
			paint(data.rows || []);
		} catch (error) {
			$("rows").innerHTML =
				`<p class="muted">${esc(error.message || "Could not load purchases.")}</p>`;
		}
	}

	function paint(rows) {
		if (!rows.length) {
			$("rows").innerHTML =
				'<p class="muted">Nothing bought in yet. Record the first supplier bill.</p>';
			return;
		}
		$("rows").innerHTML = `
			<table class="bill-table">
				<thead><tr>
					<th>Bill</th><th>Supplier</th><th>Date</th><th>Lines</th>
					<th>Total</th><th>Owed</th><th>Status</th>
				</tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td>${esc(r.bill_no || r.name)}</td>
						<td>${esc(r.supplier_name || r.supplier)}</td>
						<td>${esc(r.posting_date)}</td>
						<td>${esc(r.line_count)}</td>
						<td>${money(r.grand_total)}</td>
						<td>${r.outstanding_amount > 0 ? money(r.outstanding_amount) : "—"}</td>
						<td><span class="pill">${esc(r.docstatus === 0 ? "Draft" : r.status)}</span></td>
					</tr>`).join("")}
				</tbody>
			</table>`;
	}

	async function start(options) {
		state.branch = options.branch;

		$("refresh").addEventListener("click", load);

		$("item-hits").addEventListener("click", (event) => {
			const pick = event.target.closest(".pick");
			if (pick) addLine(pick.dataset.code, pick.dataset.label);
		});

		load();
	}

	window.PURCHASES = { start };
})();
