// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Debit notes — stock going back to a supplier.
 *
 * The rep is standing at the counter with the box, so the form is the box: who
 * is taking it, what is in it, and why. Only what the branch actually holds can
 * be offered, and only as much of it as is on the shelf.
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

	const state = { branch: "", supplier: null, lines: [], saving: false,
	                kind: "purchase", gstRates: [] };
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
			: '<p class="muted">No supplier by that name. Add them on the Purchases screen first.</p>';
	}

	function pickSupplier(name, label) {
		state.supplier = name;
		$("supplier-picked").textContent = "Going back to " + label;
		$("supplier-hits").innerHTML = "";
		$("supplier-q").value = label;
		paintLines();
	}

	// ------------------------------------------------------------------ kind
	/** Which note is being raised. Everything on the screen reads this. */
	function setKind(kind) {
		state.kind = kind === "scheme" ? "scheme" : "purchase";
		const scheme = state.kind === "scheme";

		$("dn-kind").querySelectorAll("[data-kind]").forEach((b) =>
			b.classList.toggle("is-active", b.dataset.kind === state.kind));

		$("kind-note").textContent = scheme
			? "A figure the brand has agreed. Nothing leaves the shelf \u2014 only what "
			  + "the supplier is owed changes."
			: "Goods go back to the supplier and leave the shelf.";
		$("party-head").textContent = scheme ? "Settled by" : "Going back to";
		$("lines-head").textContent = scheme ? "What the scheme comes to" : "What is going back";
		$("d-total-label").textContent = scheme ? "Scheme value" : "Value going back";
		$("d-explain").textContent = scheme
			? "The supplier's outstanding drops by the total, GST included. No stock moves."
			: "The stock leaves and what this supplier is owed drops by the same amount.";
		$("item-q").placeholder = scheme
			? "Search a scheme already set up\u2026" : "Search what this branch holds\u2026";
		$("dn-new-item").hidden = !scheme;
		$("d-bill").placeholder = scheme
			? "Their scheme reference, if any" : "Their note number, if any";
		$("d-reason").placeholder = scheme
			? "Which offer, and for what period?" : "Why is it going back?";
		// A scheme has no shelf behind it, so the stock column is noise; the
		// quantity column is counting offers rather than pieces.
		$("col-item").textContent = scheme ? "Scheme" : "Item";
		$("col-held").hidden = scheme;
		$("col-qty").textContent = scheme ? "Qty" : "Going back";

		// The two kinds cannot share lines: one has stock behind it and the
		// other has none, so switching starts the note again.
		state.lines = [];
		$("item-q").value = "";
		$("item-hits").innerHTML = "";
		paintLines();
	}

	// ----------------------------------------------------------------- items
	async function findItems() {
		const q = $("item-q").value.trim();
		if (q.length < 2) return ($("item-hits").innerHTML = "");
		const scheme = state.kind === "scheme";
		const hits = await A3.call("a3_retail.api.supplier_returns.stock_items",
			{ query: q, limit: 8, kind: state.kind });
		$("item-hits").innerHTML = (hits || []).length
			? hits.map((i) => `<button class="pick" data-code="${esc(i.item_code)}"
				data-label="${esc(i.item_name)}" data-qty="${i.qty}" data-rate="${i.rate}"
				data-gst="${i.gst_rate || 0}">
				${esc(i.item_name)}${scheme ? "" : " \u00b7 " + i.qty + " in stock"}</button>`).join("")
			: (scheme
				? '<p class="muted">No scheme by that name yet \u2014 make one with the button above.</p>'
				: '<p class="muted">Nothing by that name is in this branch\u2019s stock.</p>');
	}

	function addLine(code, label, held, rate, gst) {
		const scheme = state.kind === "scheme";
		const found = state.lines.find((l) => l.item_code === code);
		if (found) {
			// A scheme has no shelf to run out of; goods do.
			found.qty = scheme ? found.qty + 1 : Math.min(found.qty + 1, found.held);
		} else {
			state.lines.push({ item_code: code, item_name: label,
				held: scheme ? Infinity : Number(held) || 0,
				qty: 1, rate: Number(rate) || 0, gst: Number(gst) || 0 });
		}
		$("item-q").value = "";
		$("item-hits").innerHTML = "";
		paintLines();
	}

	function paintLines() {
		const scheme = state.kind === "scheme";
		const body = $("lines").querySelector("tbody");
		$("empty-note").hidden = state.lines.length > 0;
		body.innerHTML = state.lines.map((l, i) => `
			<tr>
				<td>${esc(l.item_name)}</td>
				<td class="num"${scheme ? " hidden" : ""}>${scheme ? "" : l.held}</td>
				<td><input class="qty" data-i="${i}" type="number" min="1" step="1"
					max="${l.held}" value="${l.qty}"></td>
				<td><input class="rate" data-i="${i}" type="number" min="0" step="0.01"
					value="${l.rate}"></td>
				<td class="num">${money(l.qty * l.rate)}</td>
				<td><button class="drop" data-i="${i}" aria-label="Remove">×</button></td>
			</tr>`).join("");

		body.querySelectorAll(".qty").forEach((n) => n.addEventListener("input", () => {
			const line = state.lines[Number(n.dataset.i)];
			const asked = Number(n.value) || 0;
			// Said here rather than after a failed save: the shelf is the limit.
			if (asked > line.held) {
				say(`Only ${line.held} of ${line.item_name} is in this branch.`, "error");
				n.value = line.held;
			}
			line.qty = Math.min(asked, line.held);
			paintLines();
		}));
		body.querySelectorAll(".rate").forEach((n) => n.addEventListener("input", () => {
			state.lines[Number(n.dataset.i)].rate = Number(n.value) || 0; paintLines();
		}));
		body.querySelectorAll(".drop").forEach((n) => n.addEventListener("click", () => {
			state.lines.splice(Number(n.dataset.i), 1); paintLines();
		}));

		const total = state.lines.reduce((sum, l) => sum + l.qty * l.rate, 0);
		// The GST the server will put on, shown before the save rather than
		// after it: a scheme is agreed at the figure *with* tax, so a counter
		// who cannot see the tax cannot tell whether they typed the right
		// number. Each line carries its own rate, as a mixed note may.
		const gst = state.lines.reduce(
			(sum, l) => sum + (l.qty * l.rate * (Number(l.gst) || 0)) / 100, 0);
		$("d-lines").textContent = state.lines.length;
		$("d-total").textContent = money(total);
		$("d-gst").textContent = money(gst);
		$("d-grand").textContent = money(total + gst);
		$("d-save").disabled = !state.lines.length || !state.supplier;
	}

	// ------------------------------------------------------------- the list
	// The filter icon over this list, and the window it is currently asking
	// for. Mounted on first load so the button exists before anyone can press it.
	let sheet = null;

	async function load() {
		if (!sheet) {
			sheet = A3.filterSheet(document.getElementById("list-head"), {
				label: "Filter", search: "Debit note no or the supplier",
				onApply: () => load(),
			});
		}
		try {
			const data = await A3.call("a3_retail.api.supplier_returns.recent",
				{ limit: 30, filters: sheet ? sheet.get() : {} });
			paint(data.rows || []);
		} catch (error) {
			$("rows").innerHTML =
				`<p class="muted">${esc(error.message || "Could not load debit notes.")}</p>`;
		}
	}

	function paint(rows) {
		if (!rows.length) {
			$("rows").innerHTML = '<p class="muted">Nothing has gone back yet.</p>';
			return;
		}
		$("rows").innerHTML = `
			<table class="bill-table">
				<thead><tr><th>Debit note</th><th>Supplier</th><th>Date</th>
					<th>Lines</th><th class="num">Value</th><th></th></tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td>${esc(r.name)}</td>
						<td>${esc(r.supplier_name || r.supplier)}</td>
						<td>${esc(r.posting_date)}</td>
						<td>${esc(r.line_count)}</td>
						<td class="num">${money(r.amount)}</td>
						<td class="num"><button class="btn btn-quiet dn-bill"
							data-name="${esc(r.name)}"
							data-who="${esc(r.supplier_name || r.supplier)}"
							data-amount="${esc(r.amount)}">Bill</button></td>
					</tr>`).join("")}
				</tbody>
			</table>`;
		$("rows").querySelectorAll(".dn-bill").forEach((node) =>
			node.addEventListener("click", () => openBill(node.dataset)));
	}

	/**
	 * The debit note as the supplier is given it.
	 *
	 * Printed on the shop's own purchase-bill format rather than ERPNext's
	 * standard one — a debit note is a Purchase Invoice underneath, and the
	 * supplier's accounts office is matching it against the bill it reverses.
	 * Both ways of opening it are offered because the two are different jobs:
	 * checking a figure before ringing the distributor, and putting a copy in
	 * the envelope with the goods.
	 */
	function openBill(row) {
		const doc = { doctype: "Purchase Invoice", name: row.name,
		              format: "A3 Purchase Invoice" };
		$("bill-title").textContent = row.name;
		$("bill-note").textContent = `${row.who} · ${money(Number(row.amount) || 0)}`;
		$("bill-print").onclick = () => { closeBill(); A3.printDoc(doc); };
		$("bill-view").onclick = () => { closeBill(); A3.viewDoc(doc); };
		$("bill-modal").hidden = false;
	}

	function closeBill() { $("bill-modal").hidden = true; }

	// ---------------------------------------------------------------- save
	async function save() {
		if (state.saving) return;
		const scheme = state.kind === "scheme";
		if (!state.supplier) return note(scheme
			? "Say which brand is settling the scheme."
			: "Choose which supplier it is going back to.", "error");
		if (!state.lines.length) return note(scheme
			? "Add the scheme line." : "Say what is going back.", "error");

		state.saving = true;
		$("d-save").disabled = true;
		note("Raising the debit note…");
		try {
			const result = await A3.call("a3_retail.api.supplier_returns.create", {
				payload: {
					kind: state.kind,
					supplier: state.supplier,
					bill_no: $("d-bill").value.trim(),
					date: $("d-date").value,
					reason: $("d-reason").value.trim(),
					items: state.lines.map((l) => ({
						item_code: l.item_code, qty: l.qty, rate: l.rate,
					})),
				},
			});
			note(`${result.debit_note} raised \u2014 ${money(result.amount)} off `
				+ `${result.supplier}. They now owe `
				+ `${money(Math.abs(result.supplier_outstanding))}`
				+ `${result.supplier_outstanding < 0 ? " to us" : " from us"}.`, "ok");
			A3.printDoc(result.print_url);
			reset();
			load();
		} catch (error) {
			note(error.message || "Could not raise the debit note.", "error");
		} finally {
			state.saving = false;
			$("d-save").disabled = false;
		}
	}

	function reset() {
		state.supplier = null;
		state.lines = [];
		state.schemeGst = null;
		$("supplier-q").value = "";
		$("supplier-picked").textContent = "";
		$("d-bill").value = "";
		$("d-reason").value = "";
		paintLines();
	}

	// --------------------------------------------------------- scheme item
	/** Make the item a scheme is billed under, then put it straight on the note.
	 *
	 *  Deliberately a short form rather than the purchase screen's full item
	 *  window: a scheme has no cost, no selling price, no reorder level and no
	 *  shelf. It has a name, a rate and a figure.
	 */
	function openSchemeItem() {
		$("si-name").value = $("item-q").value.trim();
		$("si-hsn").value = "85171300";
		$("si-amount").value = "";
		$("si-note").textContent = "";
		$("si-modal").hidden = false;
		$("si-name").focus();
	}

	async function saveSchemeItem() {
		const name = $("si-name").value.trim();
		if (!name) { $("si-note").textContent = "Name the scheme."; return; }
		const amount = Number($("si-amount").value) || 0;
		if (amount <= 0) { $("si-note").textContent = "What does it come to?"; return; }

		$("si-save").disabled = true;
		$("si-note").textContent = "Saving\u2026";
		try {
			const made = await A3.call(
				"a3_retail.api.supplier_returns.create_scheme_item", {
					payload: {
						item_name: name,
						hsn_code: $("si-hsn").value.trim(),
						tax_template: $("si-gst").selectedOptions[0]
							? $("si-gst").selectedOptions[0].dataset.template || "" : "",
					},
				});
			$("si-modal").hidden = true;
			addLine(made.item_code, made.item_name || name, Infinity, amount,
				Number($("si-gst").value) || 0);
		} catch (error) {
			$("si-note").textContent = error.message || "Could not save that.";
		} finally {
			$("si-save").disabled = false;
		}
	}

	async function start(options) {
		state.branch = options.branch;
		$("d-date").value = new Date().toISOString().slice(0, 10);

		try {
			const boot = await A3.call("a3_retail.api.supplier_returns.bootstrap");
			if (!boot.can_create) $("d-save").hidden = true;
			state.gstRates = boot.gst_rates || [];
			$("si-gst").innerHTML = state.gstRates.map((r) =>
				`<option value="${r.rate}" data-template="${esc(r.template || "")}"${
					Number(r.rate) === 18 ? " selected" : ""}>${r.rate}%</option>`).join("")
				|| '<option value="18">18%</option>';
		} catch (error) {
			note(error.message || "Could not start the screen.", "error");
		}

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
				pick.dataset.qty, pick.dataset.rate, pick.dataset.gst);
		});
		$("dn-kind").addEventListener("click", (event) => {
			const button = event.target.closest("[data-kind]");
			if (button) setKind(button.dataset.kind);
		});
		$("dn-new-item").addEventListener("click", openSchemeItem);
		$("si-save").addEventListener("click", saveSchemeItem);
		$("si-modal").querySelectorAll("[data-close]").forEach((b) =>
			b.addEventListener("click", () => { $("si-modal").hidden = true; }));
		$("bill-modal").querySelectorAll("[data-close]").forEach((b) =>
			b.addEventListener("click", closeBill));

		$("d-save").addEventListener("click", save);
		$("refresh").addEventListener("click", load);
		setKind("purchase");
		load();
	}

	window.DEBIT_NOTES = { start };
})();
