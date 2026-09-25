// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Recording a purchase, on a screen of its own.
 *
 * A rep can arrive with a dozen lines and a supplier the shop has never bought
 * from, carrying a phone launched last week. All three — the bill, the supplier
 * and the item — have to be enterable without leaving the page, so the two "add
 * new" panels open in place rather than stacking a dialog on a dialog.
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
			: '<p class="muted">No supplier by that name — use “New supplier”.</p>';
	}

	function pickSupplier(name, label) {
		state.supplier = name;
		$("supplier-picked").textContent = "Buying from " + label;
		$("supplier-hits").innerHTML = "";
		$("supplier-q").value = label;
		$("supplier-new").hidden = true;
	}

	async function fetchGstin() {
		const gstin = $("s-gstin").value.trim().toUpperCase();
		if (!gstin) return;
		$("s-fetch").disabled = true;
		$("s-gstin-note").textContent = "Checking…";
		try {
			const info = await A3.call("a3_retail.api.purchases.gstin_info", { gstin });
			if (info.supplier_name) $("s-name").value = info.supplier_name;
			if (info.address_line1) $("s-addr").value = info.address_line1;
			if (info.city) $("s-city").value = info.city;
			if (info.state) $("s-state").value = info.state;
			if (info.pincode) $("s-pin").value = info.pincode;
			$("s-gstin-note").textContent = info.note
				|| ("Found " + (info.supplier_name || "") + " on the GST portal.");
		} catch (error) {
			$("s-gstin-note").textContent = error.message || "Could not check that number.";
		} finally {
			$("s-fetch").disabled = false;
		}
	}

	async function saveSupplier() {
		const name = $("s-name").value.trim();
		if (!name) return say("Give the supplier a name.", "error");
		try {
			const made = await A3.call("a3_retail.api.purchases.create_supplier", {
				supplier_name: name,
				mobile_no: $("s-phone").value.trim(),
				gstin: $("s-gstin").value.trim().toUpperCase(),
				address_line1: $("s-addr").value.trim(),
				city: $("s-city").value.trim(),
				state: $("s-state").value.trim(),
				pincode: $("s-pin").value.trim(),
			});
			pickSupplier(made.name, made.supplier_name);
			say(made.created ? made.supplier_name + " added."
				: made.supplier_name + " was already on file — using that.", "ok");
		} catch (error) {
			say(error.message || "Could not save the supplier.", "error");
		}
	}

	// ----------------------------------------------------------------- items
	async function findItems() {
		const q = $("item-q").value.trim();
		if (q.length < 2) return ($("item-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.pos.catalogue", { query: q, limit: 8 });
		$("item-hits").innerHTML = (hits || []).length
			? hits.map((i) => `<button class="pick" data-code="${esc(i.item_code)}"
				data-label="${esc(i.item_name)}">${esc(i.item_name)}</button>`).join("")
			: '<p class="muted">Not in the catalogue — use “New item”.</p>';
	}

	async function saveItem() {
		const name = $("i-name").value.trim();
		if (!name) return say("Give the item a name.", "error");
		try {
			const made = await A3.call("a3_retail.api.stock_control.create_item", {
				payload: {
					item_name: name,
					item_group: $("i-group").value,
					hsn_code: $("i-hsn").value.trim(),
					uom: $("i-uom").value,
					selling_price: Number($("i-price").value) || 0,
					has_serial: $("i-serial").checked ? 1 : 0,
					opening_qty: 0,
				},
			});
			addLine(made.item_code || made.item, name);
			$("item-new").hidden = true;
			say(name + " added to the catalogue.", "ok");
		} catch (error) {
			say(error.message || "Could not add the item.", "error");
		}
	}

	function addLine(code, label) {
		const found = state.lines.find((l) => l.item_code === code);
		if (found) found.qty += 1;
		else state.lines.push({ item_code: code, item_name: label, qty: 1, rate: 0 });
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
				<td><input class="qty" data-i="${i}" type="number" min="1" step="1" value="${l.qty}"></td>
				<td><input class="rate" data-i="${i}" type="number" min="0" step="0.01" value="${l.rate}"></td>
				<td>${money(l.qty * l.rate)}</td>
				<td><button class="drop" data-i="${i}" aria-label="Remove">×</button></td>
			</tr>`).join("");

		body.querySelectorAll(".qty").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].qty = Number(n.value) || 0; paintLines();
		}));
		body.querySelectorAll(".rate").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].rate = Number(n.value) || 0; paintLines();
		}));
		body.querySelectorAll(".drop").forEach((n) => n.addEventListener("click", () => {
			state.lines.splice(Number(n.dataset.i), 1); paintLines();
		}));

		$("p-lines").textContent = state.lines.length;
		$("p-total").textContent = money(total());
	}

	const total = () => state.lines.reduce((sum, l) => sum + l.qty * l.rate, 0);

	// ---------------------------------------------------------------- saving
	async function save() {
		if (state.saving) return;
		if (!state.supplier) return note("Choose who the stock was bought from.", "error");
		if (!state.lines.length) return note("Add what came in.", "error");
		if (state.lines.some((l) => l.qty <= 0)) return note("Every line needs a quantity.", "error");

		state.saving = true;
		$("p-save").disabled = true;
		note("Saving…");
		try {
			const result = await A3.call("a3_retail.api.purchases.create", {
				payload: {
					supplier: state.supplier,
					bill_no: $("bill-no").value.trim(),
					date: $("p-date").value,
					notes: $("p-notes").value.trim(),
					paid_amount: Number($("paid").value) || 0,
					mode_of_payment: $("p-mode").value,
					items: state.lines.map((l) => ({
						item_code: l.item_code, qty: l.qty, rate: l.rate,
					})),
				},
			});
			note(`${result.purchase} saved — ${money(result.grand_total)}`
				+ (result.outstanding > 0 ? `, ${money(result.outstanding)} still owed.` : ", settled."),
				"ok");
			setTimeout(() => { window.location.href = "/retail/purchases"; }, 1400);
		} catch (error) {
			note(error.message || "Could not save the purchase.", "error");
			state.saving = false;
			$("p-save").disabled = false;
		}
	}

	// ----------------------------------------------------------------- start
	async function start(options) {
		state.branch = options.branch;
		$("p-date").value = new Date().toISOString().slice(0, 10);

		try {
			const [boot, stock] = await Promise.all([
				A3.call("a3_retail.api.purchases.bootstrap"),
				A3.call("a3_retail.api.stock_control.bootstrap"),
			]);
			$("p-mode").innerHTML = (boot.modes || [])
				.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
			$("i-group").innerHTML = (stock.item_groups || [])
				.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
			$("i-uom").innerHTML = (stock.uoms || ["Nos"])
				.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join("");
			if (!(stock.can && stock.can.create_item)) $("toggle-item").hidden = true;
		} catch (error) {
			note(error.message || "Could not start the screen.", "error");
		}

		$("toggle-supplier").addEventListener("click", () => {
			$("supplier-new").hidden = !$("supplier-new").hidden;
		});
		$("s-cancel").addEventListener("click", () => { $("supplier-new").hidden = true; });
		$("s-fetch").addEventListener("click", fetchGstin);
		$("s-gstin").addEventListener("change", fetchGstin);
		$("s-save").addEventListener("click", saveSupplier);

		$("toggle-item").addEventListener("click", () => {
			$("item-new").hidden = !$("item-new").hidden;
		});
		$("i-cancel").addEventListener("click", () => { $("item-new").hidden = true; });
		$("i-save").addEventListener("click", saveItem);

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
			if (pick) addLine(pick.dataset.code, pick.dataset.label);
		});

		$("p-save").addEventListener("click", save);
		paintLines();
	}

	window.PURCHASE_ENTRY = { start };
})();
