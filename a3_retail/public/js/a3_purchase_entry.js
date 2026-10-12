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

	const state = { branch: "", supplier: null, lines: [], saving: false, imeiRow: null };
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
				data-label="${esc(i.item_name)}" data-serial="${i.has_serial ? 1 : 0}"
				>${esc(i.item_name)}${i.has_serial ? ' <small>IMEI</small>' : ""}</button>`).join("")
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
					// `selling_price` was never a field the server reads — it reads
					// `selling_rate`, so every price typed here was dropped on the
					// floor and the item came out priced at nothing.
					selling_rate: Number($("i-price").value) || 0,
					purchase_rate: Number($("i-cost").value) || 0,
					barcode: $("i-barcode").value.trim(),
					has_serial: $("i-serial").checked ? 1 : 0,
					opening_qty: 0,
				},
			});
			addLine(made.item_code || made.item, name, $("i-serial").checked);
			const cost = Number($("i-cost").value) || 0;
			if (cost > 0) {
				const line = state.lines[state.lines.length - 1];
				if (line) { line.rate = cost; paintLines(); }
			}
			["i-cost", "i-barcode"].forEach((id) => { $(id).value = ""; });
			$("item-new").hidden = true;
			say(name + " added to the catalogue.", "ok");
		} catch (error) {
			say(error.message || "Could not add the item.", "error");
		}
	}

	function addLine(code, label, hasSerial) {
		const found = state.lines.find((l) => l.item_code === code);
		// A serialised line counts its own quantity: one handset per IMEI, so
		// bumping the count without a number to go with it would be a lie.
		if (found) { if (!found.has_serial) found.qty += 1; }
		else state.lines.push({ item_code: code, item_name: label, qty: 1, rate: 0,
		                        sell: 0, sell_hint: 0,
		                        has_serial: !!hasSerial, serials: [] });
		$("item-q").value = "";
		$("item-hits").innerHTML = "";
		paintLines();
	}

	function paintLines() {
		const body = $("lines").querySelector("tbody");
		$("empty-note").hidden = state.lines.length > 0;
		body.innerHTML = state.lines.map((l, i) => `
			<tr data-row="${i}">
				<td>${esc(l.item_name)}</td>
				<td><input class="qty" data-i="${i}" inputmode="numeric"
				           value="${l.qty || ""}"></td>
				<td><input class="rate" data-i="${i}" inputmode="decimal"
				           placeholder="0.00" value="${l.rate || ""}"></td>
				<td><input class="sell" data-i="${i}" inputmode="decimal"
				           placeholder="${l.sell_hint ? money(l.sell_hint) : "0.00"}"
				           value="${l.sell || ""}"></td>
				<td>${l.has_serial
					? `<button class="btn btn-sm imei ${
						l.qty && l.serials.length === l.qty ? "is-done" : "is-todo"}" data-i="${i}"
						>${l.serials.length}/${l.qty || 0}</button>`
					: '<span class="muted">—</span>'}</td>
				<td class="amount">${money(l.qty * l.rate)}</td>
				<td><button class="drop" data-i="${i}" aria-label="Remove">×</button></td>
			</tr>`).join("");

		// Typing must not redraw the row: replacing the input mid-keystroke takes
		// the focus with it, which is why the cost rate could never be typed into
		// — you got one character and the caret vanished. Only the figures that
		// are derived from the number are rewritten.
		body.querySelectorAll(".qty").forEach((n) => n.addEventListener("input", () => {
			const i = Number(n.dataset.i);
			const line = state.lines[i];
			line.qty = Number(n.value) || 0;
			refreshTotals(i);
			// The IMEI button shows how many of the quantity are accounted for, so
			// it has to follow the number being typed — without redrawing the row.
			const button = body.querySelector(`tr[data-row="${i}"] .imei`);
			if (button) {
				button.textContent = `${line.serials.length}/${line.qty || 0}`;
				const done = !!line.qty && line.serials.length === line.qty;
				button.classList.toggle("is-done", done);
				button.classList.toggle("is-todo", !done);
			}
		}));
		body.querySelectorAll(".rate").forEach((n) => n.addEventListener("input", () => {
			const line = state.lines[Number(n.dataset.i)];
			line.rate = Number(n.value) || 0;
			refreshTotals(Number(n.dataset.i));
		}));
		// The price does not touch the bill's total — it is what the shop will
		// ask for the goods, carried onto each piece as it comes in.
		body.querySelectorAll(".sell").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].sell = Number(n.value) || 0;
		}));
		body.querySelectorAll(".imei").forEach((n) => n.addEventListener("click", () => {
			openImei(Number(n.dataset.i));
		}));
		body.querySelectorAll(".drop").forEach((n) => n.addEventListener("click", () => {
			state.lines.splice(Number(n.dataset.i), 1); paintLines();
		}));

		refreshTotals();
	}

	/** The amount on one row, and the figures in the footer. Nothing is replaced
	 *  that somebody might be typing into. */
	function refreshTotals(index) {
		const body = $("lines").querySelector("tbody");
		if (index != null) {
			const line = state.lines[index];
			const cell = body.querySelector(`tr[data-row="${index}"] .amount`);
			if (cell) cell.textContent = money(line.qty * line.rate);
		}
		$("p-lines").textContent = state.lines.length;
		$("p-total").textContent = money(total());
	}

	// ------------------------------------------------------------------ IMEI
	/** The numbers on the boxes, one per line. These handsets are new to the
	 *  shop, so nothing is picked from a list — they are read off the cartons and
	 *  typed, scanned or pasted in, the way the serial field works in the desk. */
	function openImei(index) {
		state.imeiRow = index;
		const line = state.lines[index];
		$("imei-title").textContent = line.item_name;
		$("imei-wanted").textContent =
			`${line.qty || 0} handset${line.qty === 1 ? "" : "s"} on this line.`
			+ " Scan each box, or type the numbers below.";
		$("imei-box").value = line.serials.join("\n");
		$("imei-scan").value = "";
		flashImei("");
		$("imei-modal").hidden = false;
		countImei();
		// The gun is the fast path, so the caret waits there rather than in the
		// list — a scanner types into whatever has focus.
		$("imei-scan").focus();
	}

	function flashImei(text, kind) {
		const node = $("imei-flash");
		node.textContent = text;
		node.className = "imei-flash" + (kind ? " " + kind : "");
		node.hidden = !text;
	}

	/** One scan. The gun sends the digits then Enter, so this runs per carton. */
	function scanImei() {
		const imei = $("imei-scan").value.trim();
		$("imei-scan").value = "";
		if (!imei) return;

		const already = readImei();
		if (already.includes(imei)) {
			// Two scans of the same box is the commonest mis-scan there is, and
			// saying so now beats a refusal once the whole pallet is counted.
			flashImei(`${imei} — already scanned`, "warn");
			return;
		}
		const elsewhere = state.lines.some(
			(l, i) => i !== state.imeiRow && l.serials.includes(imei));
		if (elsewhere) {
			flashImei(`${imei} — already on another line of this bill`, "warn");
			return;
		}
		const box = $("imei-box");
		box.value = box.value.replace(/\s*$/, "") + (box.value.trim() ? "\n" : "") + imei;
		flashImei(`${imei} added`, "ok");
		countImei();
	}

	/** Whatever is in the box, one per line, blanks and repeats dropped. */
	function readImei() {
		const seen = [];
		for (const raw of $("imei-box").value.split(/[\r\n,;\t]+/)) {
			const imei = raw.trim();
			if (imei && !seen.includes(imei)) seen.push(imei);
		}
		return seen;
	}

	function countImei() {
		const line = state.lines[state.imeiRow];
		const found = readImei();
		const raw = $("imei-box").value.split(/[\r\n,;\t]+/).filter((v) => v.trim()).length;
		const bits = [`${found.length} number${found.length === 1 ? "" : "s"} for a quantity of ${line.qty || 0}`];
		if (raw > found.length) bits.push(`${raw - found.length} repeated and ignored`);
		// Said here rather than on save: a mis-scan is easiest to fix while the
		// cartons are still on the counter.
		const clash = found.filter((imei) => state.lines.some(
			(l, i) => i !== state.imeiRow && l.serials.includes(imei)));
		if (clash.length) bits.push(`${clash[0]} is already on another line`);
		$("imei-note").textContent = bits.join(" · ");
		$("imei-tally").textContent = `${found.length}/${line.qty || 0}`;
		$("imei-tally").classList.toggle("is-done",
			!!line.qty && found.length === line.qty);
	}

	function closeImei() {
		const line = state.lines[state.imeiRow];
		line.serials = readImei();
		// The quantity stays whatever was typed: the numbers are checked against
		// it on save, so a half-finished list is not silently turned into a
		// smaller delivery.
		$("imei-modal").hidden = true;
		paintLines();
	}

	const total = () => state.lines.reduce((sum, l) => sum + l.qty * l.rate, 0);

	// ---------------------------------------------------------------- saving
	async function save() {
		if (state.saving) return;
		if (!state.supplier) return note("Choose who the stock was bought from.", "error");
		if (!state.lines.length) return note("Add what came in.", "error");
		if (state.lines.some((l) => l.qty <= 0)) return note("Every line needs a quantity.", "error");
		const short = state.lines.find((l) => l.has_serial && l.serials.length !== l.qty);
		if (short) return note(
			`${short.item_name}: ${short.serials.length} IMEI number`
			+ `${short.serials.length === 1 ? "" : "s"} for a quantity of ${short.qty}.`
			+ " Every handset needs its own number.", "error");
		const dup = state.lines.find((l, i) => l.serials.some((imei) =>
			state.lines.some((o, j) => j !== i && o.serials.includes(imei))));
		if (dup) return note("The same IMEI is on more than one line.", "error");

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
						selling_rate: l.sell || 0,
						serials: l.has_serial ? l.serials : [],
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
			if (pick) addLine(pick.dataset.code, pick.dataset.label,
			                  pick.dataset.serial === "1");
		});

		$("imei-done").addEventListener("click", closeImei);
		$("imei-box").addEventListener("input", countImei);
		$("imei-scan").addEventListener("keydown", (event) => {
			if (event.key === "Enter") { event.preventDefault(); scanImei(); }
		});
		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => {
				const modal = node.closest(".modal");
				if (modal) { modal.hidden = true; if (modal.id === "imei-modal") closeImei(); }
			});
		});

		$("p-save").addEventListener("click", save);
		paintLines();
	}

	window.PURCHASE_ENTRY = { start };
})();
