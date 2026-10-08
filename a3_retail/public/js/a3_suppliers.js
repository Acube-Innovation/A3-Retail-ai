// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * A3 Retail — Supplier management (/retail/suppliers).
 *
 * The counterpart to the customer desk and deliberately the same shape, because
 * the person using it is the same person. The one real difference is that money
 * goes out from here: a payment is allocated against the bills it settles, so
 * the ledger records which invoice each rupee closed.
 */
window.SUPPLIERS = (function () {
	const $ = (id) => document.getElementById(id);
	const esc = (value) =>
		String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2,
			maximumFractionDigits: 2 }).format(value || 0);
	const day = (value) => {
		if (!value) return "—";
		const date = new Date(String(value).slice(0, 10) + "T00:00:00");
		return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
	};

	const state = { supplier: null, profile: null, tab: "purchases", page: 1,
	                query: "", owing: false, editing: null, open: [] };

	function toast(text, tone) {
		const node = $("toast");
		node.textContent = text;
		node.className = "toast" + (tone ? " " + tone : "");
		node.hidden = false;
		setTimeout(() => { node.hidden = true; }, 3200);
	}

	// ------------------------------------------------------------- the list
	async function loadList(page) {
		state.page = page || 1;
		const data = await A3.call("a3_retail.api.supplier_desk.list_suppliers", {
			query: state.query, page: state.page, only_owing: state.owing ? 1 : 0,
		});
		$("count").textContent = data.total;
		$("rows").innerHTML = data.rows.map((row) => `
			<li class="cust-row ${row.name === state.supplier ? "is-active" : ""}"
			    data-name="${esc(row.name)}">
				<div class="cust-avatar">${esc(row.initials)}</div>
				<div class="cust-who">
					<div class="cust-name">${esc(row.supplier_name)}</div>
					<div class="cust-sub">${esc(row.gstin || row.mobile_no || "—")}</div>
				</div>
				<div class="cust-meta">
					${row.outstanding > 0
						? `<span class="pill warn">${esc(money(row.outstanding))}</span>`
						: `<span class="pill">settled</span>`}
				</div>
			</li>`).join("") || `<li class="cust-empty">${esc("No suppliers found.")}</li>`;

		$("rows").querySelectorAll(".cust-row").forEach((node) => {
			node.addEventListener("click", () => open(node.dataset.name));
		});

		$("showing").textContent = data.total
			? `${data.showing[0]}–${data.showing[1]} of ${data.total}` : "none";
		$("pager").innerHTML = Array.from({ length: data.pages }, (_, i) => i + 1)
			.filter((n) => Math.abs(n - data.page) < 3 || n === 1 || n === data.pages)
			.map((n) => `<button class="${n === data.page ? "is-active" : ""}"
			                     data-page="${n}">${n}</button>`).join("");
		$("pager").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => loadList(Number(node.dataset.page)));
		});
	}

	// --------------------------------------------------------- the supplier
	async function open(supplier) {
		state.supplier = supplier;
		state.tab = "purchases";
		$("rows").querySelectorAll(".cust-row").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.name === supplier);
		});
		state.profile = await A3.call("a3_retail.api.supplier_desk.profile", { supplier });
		paintDetail();
		await paintTab();
	}

	function paintDetail() {
		const p = state.profile;
		const address = p.address || {};
		const place = [address.city, address.state].filter(Boolean).join(", ");
		$("detail").innerHTML = `
			<div class="cust-head">
				<div class="cust-avatar lg">${esc(p.initials)}</div>
				<div class="cust-head-who">
					<h2>${esc(p.supplier_name)}
						${p.disabled ? `<span class="pill warn">stopped</span>` : ""}</h2>
					<div class="cust-sub">${esc(p.gstin || "no GSTIN")}${place ? " · " + esc(place) : ""}</div>
				</div>
				<div class="cust-head-actions">
					<button class="btn btn-primary" id="d-pay">${esc("Pay")}</button>
					<button class="btn btn-outline" id="d-edit">${esc("Edit")}</button>
					<button class="btn btn-quiet" id="d-toggle">
						${p.disabled ? esc("Resume") : esc("Stop buying")}</button>
				</div>
			</div>

			<div class="ctiles">
				<div class="ctile"><span>${esc("Outstanding")}</span>
					<b class="${p.outstanding > 0 ? "warn" : ""}">${esc(money(p.outstanding))}</b></div>
				<div class="ctile"><span>${esc("Bills")}</span><b>${p.bills}</b></div>
				<div class="ctile"><span>${esc("Bought")}</span><b>${esc(money(p.spend))}</b></div>
				<div class="ctile"><span>${esc("Last bill")}</span><b>${esc(day(p.last_seen))}</b></div>
			</div>

			<div class="cust-facts">
				<div><span>${esc("Phone")}</span>${esc(p.mobile_no || "—")}</div>
				<div><span>${esc("Email")}</span>${esc(p.email_id || "—")}</div>
				<div><span>${esc("GST category")}</span>${esc(p.gst_category || "—")}</div>
				<div><span>${esc("Address")}</span>${esc(address.address_line1 || "—")}</div>
			</div>

			<div class="seg" id="tabs">
				${[["purchases", "Purchases"], ["payments", "Payments"], ["returns", "Debit notes"]]
					.map(([key, label]) => `<button class="seg-btn ${key === state.tab ? "is-active" : ""}"
					        data-value="${key}">${esc(label)}</button>`).join("")}
			</div>
			<div id="tab-body"><div class="cust-empty">${esc("Loading…")}</div></div>`;

		$("d-pay").addEventListener("click", openPay);
		$("d-edit").addEventListener("click", () => openSupplier(state.profile));
		$("d-toggle").addEventListener("click", toggleSupplier);
		$("tabs").querySelectorAll(".seg-btn").forEach((node) => {
			node.addEventListener("click", () => {
				state.tab = node.dataset.value;
				$("tabs").querySelectorAll(".seg-btn").forEach((b) =>
					b.classList.toggle("is-active", b === node));
				paintTab();
			});
		});
	}

	async function paintTab() {
		const rows = await A3.call("a3_retail.api.supplier_desk.tab", {
			supplier: state.supplier, name: state.tab });
		if (!rows.length) {
			$("tab-body").innerHTML = `<div class="cust-empty">${esc("Nothing here yet.")}</div>`;
			return;
		}
		const head = state.tab === "payments"
			? ["Payment", "Date", "Paid by", "Amount"]
			: ["Bill", "Date", "Their no.", "Total", "Outstanding"];
		const body = rows.map((r) => state.tab === "payments"
			? `<tr><td>${esc(r.name)}</td><td>${esc(day(r.posting_date))}</td>
			       <td>${esc(r.mode_of_payment || "—")}</td>
			       <td class="num">${esc(money(r.paid_amount))}</td></tr>`
			: `<tr><td>${esc(r.name)}</td><td>${esc(day(r.posting_date))}</td>
			       <td>${esc(r.bill_no || "—")}</td>
			       <td class="num">${esc(money(r.grand_total))}</td>
			       <td class="num ${r.outstanding_amount > 0 ? "warn" : ""}">
			         ${esc(money(r.outstanding_amount))}</td></tr>`).join("");
		$("tab-body").innerHTML =
			`<table class="bill-table"><thead><tr>${head.map((h) =>
				`<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
	}

	// ------------------------------------------------------- new / editing
	function openSupplier(existing) {
		state.editing = existing ? existing.name : null;
		const address = (existing && existing.address) || {};
		$("supplier-modal-title").textContent =
			existing ? "Edit " + existing.supplier_name : "New supplier";
		$("s-name").value = existing ? existing.supplier_name || "" : "";
		$("s-phone").value = existing ? existing.mobile_no || "" : "";
		$("s-email").value = existing ? existing.email_id || "" : "";
		$("s-address").value = address.address_line1 || "";
		$("s-city").value = address.city || "";
		if (address.state) $("s-state").value = address.state;
		$("s-pin").value = address.pincode || "";
		$("s-gstin").value = (existing && existing.gstin) || "";
		$("s-note").textContent = "";
		$("supplier-modal").hidden = false;
		$("s-name").focus();
	}

	async function saveSupplier() {
		const name = $("s-name").value.trim();
		if (!name) { $("s-note").textContent = "Give the supplier a name."; return; }
		try {
			const saved = await A3.call("a3_retail.api.supplier_desk.save_supplier", {
				supplier: state.editing,
				supplier_name: name,
				mobile_no: $("s-phone").value.trim(),
				email_id: $("s-email").value.trim(),
				gstin: $("s-gstin").value.trim().toUpperCase(),
				address_line1: $("s-address").value.trim(),
				city: $("s-city").value.trim(),
				state: $("s-state").value.trim(),
				pincode: $("s-pin").value.trim(),
			});
			$("supplier-modal").hidden = true;
			toast(state.editing ? "Supplier updated." : name + " added.", "ok");
			state.supplier = saved.name;
			await loadList(state.page);
			await open(saved.name);
		} catch (error) {
			$("s-note").textContent = error.message || "Could not save that supplier.";
		}
	}

	async function toggleSupplier() {
		const p = state.profile;
		state.profile = await A3.call("a3_retail.api.supplier_desk.set_disabled", {
			supplier: p.name, disabled: p.disabled ? 0 : 1 });
		paintDetail();
		await paintTab();
		await loadList(state.page);
	}

	async function fetchGstin() {
		const gstin = $("s-gstin").value.trim().toUpperCase();
		if (!gstin) return;
		$("s-fetch").disabled = true;
		$("s-note").textContent = "Checking…";
		try {
			const info = await A3.call("a3_retail.api.purchases.gstin_info", { gstin });
			if (info.supplier_name && !$("s-name").value.trim())
				$("s-name").value = info.supplier_name;
			if (info.address_line1) $("s-address").value = info.address_line1;
			if (info.city) $("s-city").value = info.city;
			if (info.state) $("s-state").value = info.state;
			if (info.pincode) $("s-pin").value = info.pincode;
			$("s-note").textContent = info.note
				|| ("Found " + (info.supplier_name || gstin) + " on the GST portal.");
		} catch (error) {
			$("s-note").textContent = error.message || "Could not check that number.";
		} finally {
			$("s-fetch").disabled = false;
		}
	}

	// -------------------------------------------------------------- paying
	async function openPay() {
		state.open = await A3.call("a3_retail.api.supplier_desk.open_invoices", {
			supplier: state.supplier });
		$("pay-to").textContent = state.profile.supplier_name
			+ " — " + money(state.profile.outstanding) + " outstanding";
		$("pay-amount").value = "";
		$("pay-ref").value = "";
		$("pay-note").textContent = "";
		paintPayRows();
		$("pay-modal").hidden = false;
		$("pay-amount").focus();
	}

	function paintPayRows() {
		if (!state.open.length) {
			$("pay-rows").innerHTML =
				`<li class="cust-empty">${esc("Nothing outstanding — this will be an advance.")}</li>`;
			summarise();
			return;
		}
		$("pay-rows").innerHTML = state.open.map((r) => `
			<li class="pay-row">
				<div class="pay-which">
					<b>${esc(r.name)}</b>
					<span>${esc(day(r.posting_date))}${r.bill_no ? " · " + esc(r.bill_no) : ""}</span>
				</div>
				<div class="pay-owed">${esc(money(r.outstanding_amount))}</div>
				<input class="pay-alloc" data-invoice="${esc(r.name)}"
				       data-owed="${r.outstanding_amount}" inputmode="decimal" placeholder="0.00">
			</li>`).join("");
		$("pay-rows").querySelectorAll(".pay-alloc").forEach((node) => {
			node.addEventListener("input", summarise);
		});
		summarise();
	}

	function allocations() {
		return Array.from($("pay-rows").querySelectorAll(".pay-alloc"))
			.map((node) => ({ invoice: node.dataset.invoice,
			                  amount: parseFloat(node.value) || 0 }))
			.filter((row) => row.amount > 0);
	}

	function summarise() {
		const amount = parseFloat($("pay-amount").value) || 0;
		const allocated = allocations().reduce((sum, row) => sum + row.amount, 0);
		const left = amount - allocated;
		$("pay-summary").innerHTML =
			`${esc("Paying")} <b>${esc(money(amount))}</b> · ${esc("allocated")}
			 <b>${esc(money(allocated))}</b> · ${esc(left < -0.005 ? "over by" : "on account")}
			 <b class="${left < -0.005 ? "warn" : ""}">${esc(money(Math.abs(left)))}</b>`;
	}

	/** Fill the bills from the oldest down, which is the order a shop settles. */
	function autoAllocate() {
		let left = parseFloat($("pay-amount").value) || 0;
		$("pay-rows").querySelectorAll(".pay-alloc").forEach((node) => {
			const owed = parseFloat(node.dataset.owed) || 0;
			const take = Math.min(left, owed);
			node.value = take > 0 ? take.toFixed(2) : "";
			left -= take;
		});
		summarise();
	}

	async function savePay() {
		const amount = parseFloat($("pay-amount").value) || 0;
		if (amount <= 0) { $("pay-note").textContent = "Enter how much is being paid."; return; }
		$("pay-save").disabled = true;
		try {
			const done = await A3.call("a3_retail.api.supplier_desk.pay", {
				supplier: state.supplier,
				amount: amount,
				mode_of_payment: $("pay-mode").value,
				reference_no: $("pay-ref").value.trim(),
				allocations: allocations(),
			});
			$("pay-modal").hidden = true;
			toast(money(done.paid) + " paid — " + done.payment, "ok");
			await open(state.supplier);
			await loadList(state.page);
		} catch (error) {
			$("pay-note").textContent = error.message || "Could not record that payment.";
		} finally {
			$("pay-save").disabled = false;
		}
	}

	// --------------------------------------------------------------- start
	async function start() {
		let timer = null;
		$("q").addEventListener("input", () => {
			clearTimeout(timer);
			timer = setTimeout(() => { state.query = $("q").value.trim(); loadList(1); }, 220);
		});
		$("owing").addEventListener("click", () => {
			state.owing = !state.owing;
			$("owing").classList.toggle("is-active", state.owing);
			loadList(1);
		});
		$("new-supplier").addEventListener("click", () => openSupplier(null));
		$("s-save").addEventListener("click", saveSupplier);
		$("s-fetch").addEventListener("click", fetchGstin);
		$("s-gstin").addEventListener("change", fetchGstin);
		$("pay-save").addEventListener("click", savePay);
		$("pay-auto").addEventListener("click", autoAllocate);
		$("pay-amount").addEventListener("input", summarise);

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		await loadList(1);

		// The purchases screen links straight to a distributor to settle a bill.
		const wanted = new URLSearchParams(window.location.search).get("supplier");
		if (wanted) {
			await open(wanted);
			if (new URLSearchParams(window.location.search).get("pay")) await openPay();
		}
	}

	document.addEventListener("DOMContentLoaded", start);
	return { start, state };
})();
