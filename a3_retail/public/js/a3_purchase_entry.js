// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Recording a purchase, on a screen of its own.
 *
 * A rep can arrive with a dozen lines, a supplier the shop has never bought
 * from, and a phone launched last week. The bill is the thing on the counter,
 * so it stays whole on the page; everything a line needs — which items, which
 * handsets, an item nobody has catalogued yet — is asked for in a dialog and
 * closed again, rather than pushing the bill off the screen.
 */
(function () {
	const $ = (id) => document.getElementById(id);
	const money = (v) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2,
			maximumFractionDigits: 2 }).format(v || 0);
	const num = (v) => Number(String(v == null ? "" : v).replace(/[^0-9.\-]/g, "")) || 0;

	function esc(v) {
		const n = document.createElement("div");
		n.textContent = v == null ? "" : String(v);
		return n.innerHTML;
	}

	/** "12 Oct 2026" — the way a date is read off a delivery note. */
	function shortDate(value) {
		const d = value ? new Date(value) : new Date();
		if (isNaN(d)) return "";
		return d.toLocaleDateString("en-IN",
			{ day: "2-digit", month: "short", year: "numeric" });
	}

	const state = {
		branch: "",
		supplier: null,
		lines: [],
		saving: false,
		meta: { groups: [], uoms: [], taxes: [], warehouses: [], warehouse: "",
		        canCreateItem: false },
		pick: { hits: [], chosen: new Map(), cursor: -1 },
		imei: { row: -1, rows: [] },
	};
	let supplierTimer = null;
	let pickTimer = null;

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

	/** Which dialog is on top, so Esc and F7 reach the right one. */
	const topModal = () => [...document.querySelectorAll(".modal:not([hidden])")].pop();

	function openModal(id) { $(id).hidden = false; }
	function closeModal(id) { $(id).hidden = true; }

	// ---------------------------------------------------------------- supplier
	async function findSuppliers() {
		const q = $("supplier-q").value.trim();
		if (q.length < 2) return ($("supplier-hits").innerHTML = "");
		const hits = await A3.call("a3_retail.api.purchases.search_suppliers",
			{ query: q, limit: 8 });
		$("supplier-hits").innerHTML = hits.length
			? hits.map((s) => `<button class="pick" data-name="${esc(s.name)}"
				data-label="${esc(s.supplier_name)}" data-registered="${s.registered ? 1 : 0}"
				>${esc(s.supplier_name)}${
				s.mobile_no ? " · " + esc(s.mobile_no) : ""}${
				s.registered ? "" : ' <small>no GST number</small>'}</button>`).join("")
			: '<p class="muted">No supplier by that name — use “New supplier”.</p>';
	}

	function pickSupplier(name, label, registered) {
		state.supplier = name;
		// An unregistered dealer cannot charge GST, so the bill carries none and
		// the screen should not pretend otherwise.
		state.supplierRegistered = registered !== false;
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
			pickSupplier(made.name, made.supplier_name,
			             !!$("s-gstin").value.trim());
			say(made.created ? made.supplier_name + " added."
				: made.supplier_name + " was already on file — using that.", "ok");
		} catch (error) {
			say(error.message || "Could not save the supplier.", "error");
		}
	}

	// ====================================================== Add Items to Bill
	/* One list, answering the three questions a buyer asks of every line at
	   once: what is on the shelf, what it sells for, what it costs. Quantities
	   are gathered against the list and go onto the bill in one go, because a
	   rep reads out a dozen lines in a row and closing a dialog between each
	   one is how a line gets missed. */

	function openPicker(forScan) {
		state.pick.chosen = new Map();
		state.pick.cursor = -1;
		$("pick-q").value = "";
		openModal("pick-modal");
		paintPicker();
		loadPicker();
		$("pick-q").focus();
		if (forScan) flashPickHint("Scan the barcode — the cursor is in the box.");
	}

	function flashPickHint(text) {
		$("pick-empty").textContent = text;
		$("pick-empty").hidden = !text;
	}

	async function loadPicker() {
		const query = $("pick-q").value.trim();
		try {
			state.pick.hits = await A3.call("a3_retail.api.purchases.catalogue", {
				query, item_group: $("pick-group").value || "", limit: 40 });
		} catch (error) {
			state.pick.hits = [];
			say(error.message || "Could not read the catalogue.", "error");
		}
		state.pick.cursor = state.pick.hits.length ? 0 : -1;
		paintPicker();
	}

	function paintPicker() {
		const { hits, chosen, cursor } = state.pick;
		const body = $("pick-rows");
		body.innerHTML = hits.map((item, i) => {
			const taken = chosen.get(item.item_code);
			const qty = taken ? taken.qty : 0;
			return `<tr data-i="${i}" class="${i === cursor ? "is-cursor " : ""}${
				qty ? "is-picked" : ""}">
				<td><span class="pick-name">${esc(item.item_name)}</span>${
					item.has_serial ? '<span class="pick-serial">IMEI</span>' : ""}</td>
				<td class="pick-code">${esc(item.barcode || item.item_code)}</td>
				<td class="num"><span class="pick-stock${item.stock > 0 ? "" : " is-out"}"
					>${item.stock > 0 ? item.stock : "—"}</span></td>
				<td class="num">${item.sales_price
					? money(item.sales_price) : '<span class="pick-nil">—</span>'}</td>
				<td class="num">${item.purchase_price
					? money(item.purchase_price) : '<span class="pick-nil">—</span>'}</td>
				<td class="num col-pickqty"><span class="pick-add">${qty
					? `<span class="pick-step">
						<button class="less" data-i="${i}" aria-label="One fewer">−</button>
						<input class="cnt" data-i="${i}" inputmode="numeric" value="${qty}">
						<button class="more" data-i="${i}" aria-label="One more">+</button>
					   </span>`
					: `<button class="btn-add1" data-i="${i}">+ Add</button>`}</span></td>
			</tr>`;
		}).join("");

		if (!hits.length) {
			flashPickHint($("pick-q").value.trim()
				? "Nothing matches that. Create the item if it is new to the shop."
				: "Search for what the rep has brought in.");
		} else {
			$("pick-empty").hidden = true;
		}

		body.querySelectorAll(".btn-add1").forEach((n) =>
			n.addEventListener("click", () => bump(Number(n.dataset.i), 1)));
		body.querySelectorAll(".more").forEach((n) =>
			n.addEventListener("click", () => bump(Number(n.dataset.i), 1)));
		body.querySelectorAll(".less").forEach((n) =>
			n.addEventListener("click", () => bump(Number(n.dataset.i), -1)));
		// Typing a count must not redraw the row out from under the caret, so
		// only the footer follows the keystroke.
		body.querySelectorAll(".cnt").forEach((n) => n.addEventListener("input", () => {
			const item = state.pick.hits[Number(n.dataset.i)];
			const qty = Math.max(0, Math.floor(num(n.value)));
			if (qty) state.pick.chosen.set(item.item_code, { item, qty });
			else state.pick.chosen.delete(item.item_code);
			paintPickerFoot();
		}));
		body.querySelectorAll("tr").forEach((row) => row.addEventListener("click", (e) => {
			if (e.target.closest("button, input")) return;
			state.pick.cursor = Number(row.dataset.i);
			markCursor();
		}));

		paintPickerFoot();
	}

	function markCursor() {
		$("pick-rows").querySelectorAll("tr").forEach((row) =>
			row.classList.toggle("is-cursor", Number(row.dataset.i) === state.pick.cursor));
		const row = $("pick-rows").querySelector("tr.is-cursor");
		if (row) row.scrollIntoView({ block: "nearest" });
	}

	function bump(index, by) {
		const item = state.pick.hits[index];
		if (!item) return;
		const taken = state.pick.chosen.get(item.item_code);
		const qty = Math.max(0, (taken ? taken.qty : 0) + by);
		if (qty) state.pick.chosen.set(item.item_code, { item, qty });
		else state.pick.chosen.delete(item.item_code);
		state.pick.cursor = index;
		paintPicker();
	}

	function paintPickerFoot() {
		let pieces = 0;
		let value = 0;
		state.pick.chosen.forEach(({ item, qty }) => {
			pieces += qty;
			value += qty * (item.purchase_price || 0);
		});
		const count = state.pick.chosen.size;
		$("pick-count").textContent =
			`${count} item${count === 1 ? "" : "s"} selected`;
		$("pick-count").disabled = !count;
		$("pick-qty").textContent = `${pieces} pcs`;
		$("pick-total").textContent = money(value);
		$("pick-done").disabled = !count;
	}

	/** Everything gathered against the list, onto the bill. */
	function commitPicker() {
		if (!state.pick.chosen.size) return;
		let firstSerial = -1;
		state.pick.chosen.forEach(({ item, qty }) => {
			const index = addLine(item, qty);
			if (item.has_serial && firstSerial < 0) firstSerial = index;
		});
		closeModal("pick-modal");
		paintLines();
		// A handset cannot go on a bill without its number, so the screen asks
		// for it straight away rather than waiting to refuse the save.
		if (firstSerial >= 0 && !state.lines[firstSerial].serials.length) openImei(firstSerial);
	}

	/** Add to the bill, or add to a line already on it. Returns its index. */
	function addLine(item, qty) {
		const found = state.lines.findIndex((l) => l.item_code === item.item_code);
		if (found >= 0) {
			state.lines[found].qty += qty;
			return found;
		}
		state.lines.push({
			item_code: item.item_code,
			item_name: item.item_name,
			barcode: item.barcode || "",
			qty: qty,
			rate: item.purchase_price || 0,
			sell: 0,
			sell_hint: item.sales_price || 0,
			gst_rate: item.gst_rate == null ? 18 : Number(item.gst_rate),
			has_serial: !!item.has_serial,
			serials: [],
		});
		return state.lines.length - 1;
	}

	// --------------------------------------------------------------- the bill
	function paintLines() {
		const body = $("lines").querySelector("tbody");
		$("empty-note").hidden = state.lines.length > 0;
		body.innerHTML = state.lines.map((l, i) => `
			<tr data-row="${i}">
				<td class="cell-no">${i + 1}</td>
				<td class="cell-item">${esc(l.item_name)}${
					l.barcode ? `<small>${esc(l.barcode)}</small>` : ""}</td>
				<td><input class="qty" data-i="${i}" inputmode="numeric"
				           value="${l.qty || ""}"></td>
				<td><input class="rate" data-i="${i}" inputmode="decimal"
				           placeholder="0.00" value="${l.rate || ""}"></td>
				<td><input class="sell" data-i="${i}" inputmode="decimal"
				           placeholder="${l.sell_hint ? l.sell_hint : "0.00"}"
				           value="${l.sell || ""}"></td>
				<td>${l.has_serial
					? `<button class="btn imei ${
						l.qty && l.serials.length === l.qty ? "is-done" : "is-todo"}" data-i="${i}"
						>${l.serials.length}/${l.qty || 0}</button>`
					: '<span class="muted">—</span>'}</td>
				<td class="cell-amt">${money(l.qty * l.rate)}</td>
				<td><button class="drop" data-i="${i}" aria-label="Remove">×</button></td>
			</tr>`).join("");

		// Typing must not redraw the row: replacing the input mid-keystroke takes
		// the focus with it, which is why the cost rate could never be typed into
		// — you got one character and the caret vanished. Only the figures that
		// are derived from the number are rewritten.
		body.querySelectorAll(".qty").forEach((n) => n.addEventListener("input", () => {
			const i = Number(n.dataset.i);
			const line = state.lines[i];
			line.qty = num(n.value);
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
			const i = Number(n.dataset.i);
			state.lines[i].rate = num(n.value);
			refreshTotals(i);
		}));
		// The price does not touch the bill's total — it is what the shop will
		// ask for the goods, carried onto each piece as it comes in.
		body.querySelectorAll(".sell").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].sell = num(n.value);
		}));
		body.querySelectorAll(".imei").forEach((n) =>
			n.addEventListener("click", () => openImei(Number(n.dataset.i))));
		body.querySelectorAll(".drop").forEach((n) => n.addEventListener("click", () => {
			state.lines.splice(Number(n.dataset.i), 1);
			paintLines();
		}));

		refreshTotals();
	}

	/** The amount on one row, and the figures in the footer. Nothing is replaced
	 *  that somebody might be typing into. */
	function refreshTotals(index) {
		const body = $("lines").querySelector("tbody");
		if (index != null) {
			const line = state.lines[index];
			const cell = body.querySelector(`tr[data-row="${index}"] .cell-amt`);
			if (cell) cell.textContent = money(line.qty * line.rate);
		}
		const taxable = total();
		// The bill is taxed at the highest rate its lines carry, which is what
		// the document posts; a single-rate bill is the normal case anyway.
		const rate = state.supplierRegistered === false ? 0
			: state.lines.reduce((top, l) => Math.max(top, Number(l.gst_rate) || 0), 0);
		const gst = taxable * rate / 100;

		$("p-lines").textContent = state.lines.length;
		$("p-taxable").textContent = money(taxable);
		$("p-gst-rate").textContent = rate || 0;
		$("p-gst").textContent = money(gst);
		$("p-gst").closest(".tr").hidden = !rate;
		$("p-total").textContent = money(Math.round(taxable + gst));
	}

	/** What the goods cost before tax — the figure the rep quotes per piece. */
	const total = () => state.lines.reduce((sum, l) => sum + l.qty * l.rate, 0);

	// ===================================================== Add Serial Numbers
	/* These handsets are new to the shop, so nothing is picked from a list —
	   the numbers are read off the cartons. One row each, because a mis-scan in
	   a delivery of twenty has to be findable and correctable on its own line. */

	function openImei(index) {
		state.imei.row = index;
		const line = state.lines[index];
		state.imei.rows = line.serials.map((sn) => ({ sn }));
		$("imei-item").value = line.item_name;
		$("imei-qty").value = line.qty || "";
		$("imei-scan").value = "";
		flashImei("");
		openModal("imei-modal");
		paintImei();
		// The gun is the fast path, so the caret waits there — a scanner types
		// into whatever has focus.
		$("imei-scan").focus();
	}

	function paintImei() {
		const rows = state.imei.rows;
		$("imei-empty").hidden = rows.length > 0;
		$("imei-rows").innerHTML = rows.map((row, i) => `
			<tr>
				<td><input class="sn" data-i="${i}" value="${esc(row.sn)}"
				           inputmode="numeric" autocomplete="off" spellcheck="false"></td>
				<td class="col-when">${esc(shortDate())}</td>
				<td class="col-x"><button class="drop" data-i="${i}"
					aria-label="Remove">×</button></td>
			</tr>`).join("");

		$("imei-rows").querySelectorAll(".sn").forEach((n) =>
			n.addEventListener("input", () => {
				state.imei.rows[Number(n.dataset.i)].sn = n.value.trim();
				countImei();
			}));
		$("imei-rows").querySelectorAll(".drop").forEach((n) =>
			n.addEventListener("click", () => {
				state.imei.rows.splice(Number(n.dataset.i), 1);
				paintImei();
			}));
		countImei();
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
		if (addSerial(imei)) flashImei(`${imei} added`, "ok");
	}

	/** A number onto the list, with the two mis-scans worth catching early. */
	function addSerial(sn) {
		if (state.imei.rows.some((r) => r.sn === sn)) {
			// Two scans of the same box is the commonest mis-scan there is, and
			// saying so now beats a refusal once the whole pallet is counted.
			flashImei(`${sn} — already on this list`, "warn");
			return false;
		}
		const elsewhere = state.lines.some(
			(l, i) => i !== state.imei.row && l.serials.includes(sn));
		if (elsewhere) {
			flashImei(`${sn} — already on another line of this bill`, "warn");
			return false;
		}
		state.imei.rows.push({ sn });
		// The quantity follows the cartons: scanning the twenty-first handset
		// means twenty-one arrived, not that the scan was wrong.
		if (state.imei.rows.length > num($("imei-qty").value)) {
			$("imei-qty").value = state.imei.rows.length;
		}
		paintImei();
		return true;
	}

	/** An empty row to type into, for a box whose barcode will not read. */
	function addBlankSerial() {
		state.imei.rows.push({ sn: "" });
		paintImei();
		const boxes = $("imei-rows").querySelectorAll(".sn");
		if (boxes.length) boxes[boxes.length - 1].focus();
	}

	const serialsNow = () => {
		const seen = [];
		for (const row of state.imei.rows) {
			if (row.sn && !seen.includes(row.sn)) seen.push(row.sn);
		}
		return seen;
	};

	function countImei() {
		const found = serialsNow();
		const want = num($("imei-qty").value);
		const filled = state.imei.rows.filter((r) => r.sn).length;
		const bits = [`${found.length} of ${want || 0}`];
		if (filled > found.length) bits.push(`${filled - found.length} repeated`);
		const clash = found.filter((sn) => state.lines.some(
			(l, i) => i !== state.imei.row && l.serials.includes(sn)));
		if (clash.length) bits.push(`${clash[0]} is already on another line`);
		else if (want && found.length < want) bits.push(`${want - found.length} still to scan`);
		$("imei-note").textContent = bits.join(" · ");
		$("imei-tally").textContent = `${found.length}/${want || 0}`;
		$("imei-tally").classList.toggle("is-done", !!want && found.length === want);
	}

	/** Onto the line. The quantity follows the numbers, because the numbers are
	 *  the handsets — a count that disagrees with them is the count that is
	 *  wrong, and the save would refuse it anyway. */
	function commitImei() {
		const line = state.lines[state.imei.row];
		if (!line) return closeModal("imei-modal");
		const found = serialsNow();
		line.serials = found;
		line.qty = found.length || num($("imei-qty").value);
		closeModal("imei-modal");
		paintLines();
	}

	// ======================================================== Create New Item
	/* Name and price are all it takes to get the line on the bill. The code,
	   the HSN and the opening count are there for whoever has them to hand,
	   behind their own headings — which is what keeps the first screen short
	   enough to fill in with a rep waiting at the counter. */

	/** The same figure asked for on two panes stays one figure. */
	function bindMirrors() {
		document.querySelectorAll("#ni-modal [data-bind]").forEach((node) => {
			node.addEventListener("input", () => {
				document.querySelectorAll(
					`#ni-modal [data-bind="${node.dataset.bind}"]`).forEach((twin) => {
					if (twin !== node) twin.value = node.value;
				});
				if (node.dataset.bind === "uom") paintUomLabels();
				paintMargin();
			});
		});
	}

	function paintUomLabels() {
		const uom = $("ni-uom").value || "PCS";
		document.querySelectorAll("#ni-modal [data-uom-label]").forEach((node) => {
			node.textContent = uom.toUpperCase().slice(0, 6);
		});
	}

	const gstNow = () => num($("ni-gst").value);

	/** Both figures brought to the same footing before they are compared: the
	 *  shop quotes selling prices with the tax in and buying prices without. */
	function exTax(value, basis) {
		const g = gstNow();
		return basis === "with" && g ? value / (1 + g / 100) : value;
	}

	function paintMargin() {
		const sell = exTax(num($("ni-price").value), $("ni-price-tax").value);
		const cost = exTax(num($("ni-cost").value), $("ni-cost-tax").value);
		const node = $("ni-margin");
		node.classList.remove("is-thin", "is-loss");
		if (!sell || !cost) {
			node.textContent = "—";
			$("ni-exgst").textContent = "";
			return;
		}
		const pct = ((sell - cost) / cost) * 100;
		node.textContent = `${pct.toFixed(1)}%  ·  ${money(sell - cost)} a piece`;
		if (pct < 0) node.classList.add("is-loss");
		else if (pct < 3) node.classList.add("is-thin");
		$("ni-exgst").textContent =
			`Before GST: cost ${money(cost)}, sells for ${money(sell)}.`
			+ (gstNow() ? ` At ${gstNow()}% GST.` : "");
	}

	function openNewItem(name) {
		["ni-name", "ni-cost", "ni-price", "ni-open", "ni-code", "ni-hsn",
		 "ni-desc", "ni-reorder", "ni-cost2", "ni-price2", "ni-open2"].forEach((id) => {
			$(id).value = "";
		});
		$("ni-serial").checked = false;
		$("ni-note").textContent = "";
		markGap("");
		document.querySelector('#ni-modal input[value="product"]').checked = true;
		showPane("basic");
		if (name) $("ni-name").value = name;
		paintUomLabels();
		paintMargin();
		openModal("ni-modal");
		$("ni-name").focus();
	}

	/** Mark the heading that is hiding whatever the save refused. */
	function markGap(which) {
		document.querySelectorAll("#ni-modal .ni-tab").forEach((tab) =>
			tab.classList.toggle("has-gap", tab.dataset.tab === which));
	}

	function showPane(which) {
		document.querySelectorAll("#ni-modal .ni-tab").forEach((tab) =>
			tab.classList.toggle("is-on", tab.dataset.tab === which));
		document.querySelectorAll("#ni-modal .ni-pane").forEach((pane) => {
			pane.hidden = pane.dataset.pane !== which;
		});
	}

	/** A code for a box that never had one printed on it. */
	function generateCode() {
		const stamp = Date.now().toString(36).toUpperCase().slice(-6);
		$("ni-code").value = "ITM" + stamp;
	}

	async function saveNewItem() {
		const name = $("ni-name").value.trim();
		if (!name) {
			showPane("basic");
			$("ni-name").focus();
			$("ni-note").textContent = "Give the item a name.";
			return;
		}
		if (!$("ni-group").value) {
			showPane("basic");
			$("ni-group").focus();
			$("ni-note").textContent = "Choose the category it belongs in.";
			return;
		}
		const service = document.querySelector(
			'#ni-modal input[name="ni-type"]:checked').value === "service";
		const gst = gstNow();
		const costIn = num($("ni-cost").value);
		const priceIn = num($("ni-price").value);
		// Stored the way each side of the shop keeps it: the buying rate without
		// tax, because that is what the purchase posts at, and the selling price
		// with it, because the price list is the MRP on the box.
		const cost = $("ni-cost-tax").value === "with" && gst
			? costIn / (1 + gst / 100) : costIn;
		const price = $("ni-price-tax").value === "without" && gst
			? priceIn * (1 + gst / 100) : priceIn;

		$("ni-save").disabled = true;
		$("ni-note").textContent = "Saving…";
		try {
			const made = await A3.call("a3_retail.api.stock_control.create_item", {
				payload: {
					item_name: name,
					item_group: $("ni-group").value,
					item_code: $("ni-code").value.trim(),
					barcode: $("ni-code").value.trim(),
					hsn_code: $("ni-hsn").value.trim(),
					uom: $("ni-uom").value,
					tax_template: $("ni-gst").selectedOptions[0]
						? $("ni-gst").selectedOptions[0].dataset.template || "" : "",
					description: $("ni-desc").value.trim(),
					selling_rate: Math.round(price * 100) / 100,
					purchase_rate: Math.round(cost * 100) / 100,
					reorder_level: num($("ni-reorder").value),
					has_serial: $("ni-serial").checked ? 1 : 0,
					is_service: service ? 1 : 0,
					opening_qty: num($("ni-open").value),
					warehouse: $("ni-wh").value,
				},
			});
			closeModal("ni-modal");
			say(name + " added to the catalogue.", "ok");
			// Straight onto the bill: the item was created because the rep is
			// standing there with it.
			const index = addLine({
				item_code: made.item_code,
				item_name: made.item_name || name,
				barcode: $("ni-code").value.trim(),
				purchase_price: Math.round(cost * 100) / 100,
				sales_price: Math.round(price * 100) / 100,
				has_serial: $("ni-serial").checked,
			}, 1);
			if (!$("pick-modal").hidden) { closeModal("pick-modal"); }
			paintLines();
			if ($("ni-serial").checked) openImei(index);
		} catch (error) {
			const message = error.message || "Could not add the item.";
			$("ni-note").textContent = message;
			// The HSN is required but it lives behind a heading, so a refusal
			// over it has to take you to the box rather than leaving you on a
			// pane where nothing looks wrong.
			if (/hsn|sac/i.test(message)) {
				showPane("stock");
				markGap("stock");
				$("ni-hsn").focus();
			}
		} finally {
			$("ni-save").disabled = false;
		}
	}

	// ----------------------------------------------------------------- saving
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
					paid_amount: num($("paid").value),
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
			state.meta.warehouse = boot.warehouse || "";
			state.meta.canCreateItem = !!(stock.can && stock.can.create_item);

			$("p-mode").innerHTML = (boot.modes || [])
				.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");

			const groups = stock.item_groups || [];
			// No default: whatever sorts first is not where this item belongs,
			// and a silently miscategorised item is hard to find again.
			$("ni-group").innerHTML = '<option value="">Choose a category…</option>'
				+ groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
			$("pick-group").innerHTML = '<option value="">All categories</option>'
				+ groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");

			const uoms = stock.uoms && stock.uoms.length ? stock.uoms : ["Nos"];
			const uomOptions = uoms
				.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join("");
			$("ni-uom").innerHTML = uomOptions;
			$("ni-uom2").innerHTML = uomOptions;
			if (uoms.includes("Nos")) { $("ni-uom").value = "Nos"; $("ni-uom2").value = "Nos"; }

			// Offered as the number on the invoice; stored as the template that
			// carries it, which is what ERPNext reads when it works out the tax.
			$("ni-gst").innerHTML = '<option value="">None</option>'
				+ (stock.tax_templates || []).map((t) =>
					`<option value="${t.rate}" data-template="${esc(t.name)}"
						>${t.rate}% — ${esc(t.name)}</option>`).join("");
			$("ni-gst2").innerHTML = $("ni-gst").innerHTML;

			$("ni-wh").innerHTML = (stock.warehouses || [])
				.map((w) => `<option value="${esc(w)}">${esc(w)}</option>`).join("");
			if (state.meta.warehouse) $("ni-wh").value = state.meta.warehouse;

			if (!state.meta.canCreateItem) $("pick-new").hidden = true;
			paintUomLabels();
		} catch (error) {
			note(error.message || "Could not start the screen.", "error");
		}

		// --- supplier
		$("toggle-supplier").addEventListener("click", () => {
			$("supplier-new").hidden = !$("supplier-new").hidden;
		});
		$("s-cancel").addEventListener("click", () => { $("supplier-new").hidden = true; });
		$("s-fetch").addEventListener("click", fetchGstin);
		$("s-gstin").addEventListener("change", fetchGstin);
		$("s-save").addEventListener("click", saveSupplier);
		$("supplier-q").addEventListener("input", () => {
			clearTimeout(supplierTimer);
			supplierTimer = setTimeout(findSuppliers, 220);
		});
		$("supplier-hits").addEventListener("click", (event) => {
			const pick = event.target.closest(".pick");
			if (pick) pickSupplier(pick.dataset.name, pick.dataset.label,
			                       pick.dataset.registered === "1");
		});

		// --- the picker
		$("open-pick").addEventListener("click", () => openPicker(false));
		$("open-scan").addEventListener("click", () => openPicker(true));
		$("pick-gun").addEventListener("click", () => $("pick-q").focus());
		$("pick-q").addEventListener("input", () => {
			clearTimeout(pickTimer);
			pickTimer = setTimeout(loadPicker, 220);
		});
		$("pick-group").addEventListener("change", loadPicker);
		$("pick-new").addEventListener("click", () => openNewItem($("pick-q").value.trim()));
		$("pick-done").addEventListener("click", commitPicker);
		$("pick-count").addEventListener("click", () => {
			// What has been gathered so far, without leaving the list.
			const names = [];
			state.pick.chosen.forEach(({ item, qty }) =>
				names.push(`${item.item_name} × ${qty}`));
			say(names.join(" · "), "ok");
		});
		$("pick-q").addEventListener("keydown", (event) => {
			if (event.key !== "Enter") return;
			event.preventDefault();
			// A gun sends the digits then Enter. One match is a scan that found
			// its box, so it goes straight on; anything else adds whatever row
			// the cursor is resting on.
			if (state.pick.hits.length === 1) {
				bump(0, 1);
				$("pick-q").value = "";
				loadPicker();
			} else if (state.pick.cursor >= 0) {
				bump(state.pick.cursor, 1);
			}
		});

		// --- serial numbers
		$("imei-done").addEventListener("click", commitImei);
		$("imei-add").addEventListener("click", addBlankSerial);
		$("imei-gun").addEventListener("click", () => $("imei-scan").focus());
		$("imei-qty").addEventListener("input", countImei);
		$("imei-scan").addEventListener("keydown", (event) => {
			if (event.key === "Enter") { event.preventDefault(); scanImei(); }
		});

		// --- the new item
		document.querySelectorAll("#ni-modal .ni-tab").forEach((tab) =>
			tab.addEventListener("click", () => showPane(tab.dataset.tab)));
		$("ni-gen").addEventListener("click", generateCode);
		$("ni-save").addEventListener("click", saveNewItem);
		["ni-cost-tax", "ni-price-tax", "ni-gst"].forEach((id) =>
			$(id).addEventListener("change", () => {
				document.querySelectorAll(
					`#ni-modal [data-bind="${$(id).dataset.bind}"]`).forEach((twin) => {
					twin.value = $(id).value;
				});
				paintMargin();
			}));
		$("ni-uom").addEventListener("change", () => {
			$("ni-uom2").value = $("ni-uom").value;
			paintUomLabels();
		});
		$("ni-uom2").addEventListener("change", () => {
			$("ni-uom").value = $("ni-uom2").value;
			paintUomLabels();
		});
		bindMirrors();

		// --- every dialog closes the same way
		document.querySelectorAll("[data-close]").forEach((node) =>
			node.addEventListener("click", () => {
				const modal = node.closest(".modal");
				if (modal) modal.hidden = true;
			}));
		document.addEventListener("keydown", (event) => {
			const modal = topModal();
			if (!modal) return;
			if (event.key === "Escape") { event.preventDefault(); modal.hidden = true; return; }
			if (event.key === "F7") {
				event.preventDefault();
				if (modal.id === "pick-modal") commitPicker();
				else if (modal.id === "imei-modal") commitImei();
				else if (modal.id === "ni-modal") saveNewItem();
				return;
			}
			if (modal.id !== "pick-modal") return;
			if (event.key === "ArrowDown" || event.key === "ArrowUp") {
				event.preventDefault();
				const last = state.pick.hits.length - 1;
				if (last < 0) return;
				const step = event.key === "ArrowDown" ? 1 : -1;
				state.pick.cursor = Math.min(last, Math.max(0, state.pick.cursor + step));
				markCursor();
			}
		});

		$("p-save").addEventListener("click", save);
		paintLines();
	}

	window.PURCHASE_ENTRY = { start };
})();
