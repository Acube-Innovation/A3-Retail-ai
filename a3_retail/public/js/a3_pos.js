// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Counter billing for the branch app.
 *
 * The rules the screen enforces are the shop's, not the browser's: a device
 * cannot go on the bill without its IMEI, an item with no stock here shows where
 * it *is* instead of failing, and every total on screen is a preview — the
 * server prices the invoice and re-checks all of it.
 */

window.POS = (function () {
	const state = {
		branch: "", groups: [], group: "", view: "grid",
		items: [], cart: [], customer: null, mode: "Cash", editing: null,
	};
	const HOLD_KEY = "a3_pos_holds";
	const $ = (id) => document.getElementById(id);

	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);
	const moneyShort = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value || 0);

	function esc(value) {
		const node = document.createElement("div");
		node.textContent = value == null ? "" : String(value);
		return node.innerHTML;
	}

	function say(text, kind) {
		const box = $("pos-msg");
		box.textContent = text || "";
		box.className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------ catalogue
	let searchTimer;
	async function loadCatalogue() {
		try {
			state.items = await A3.call("a3_retail.api.pos.catalogue", {
				query: $("q").value.trim(),
				item_group: state.group,
				only_in_stock: $("in-stock").checked ? 1 : 0,
			});
			paintCatalogue();
		} catch (error) {
			$("grid").innerHTML = '<div class="pos-loading">Could not load the catalogue.</div>';
		}
	}

	/** A photograph fills its tile; a drawing sits inside it. */
	function isPhoto(image) {
		return String(image || "").indexOf("/photos/") !== -1;
	}

	function thumb(item) {
		if (item.image) {
			return `<img class="${isPhoto(item.image) ? "is-photo" : ""}"
			             src="${esc(item.image)}" alt="">`;
		}
		const initials = (item.item_name || "?").replace(/[^A-Za-z0-9 ]/g, "")
			.split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
		return `<span class="thumb-fallback">${esc(initials || "?")}</span>`;
	}

	function badge(item) {
		if (item.is_new) return '<span class="badge-new">NEW</span>';
		if (item.low_stock) return '<span class="badge-low">LOW STOCK</span>';
		return "";
	}

	/** The card reads brand, then model, then what the line will need. */
	function cardLines(item) {
		const brand = item.brand || "";
		let name = item.item_name || item.item_code;
		if (brand && name.toLowerCase().startsWith(brand.toLowerCase() + " ")) {
			name = name.slice(brand.length + 1);
		}
		let tag = "";
		if (item.is_device) tag = "IMEI";
		else if (item.is_plan) tag = item.item_group || "Plan";
		else if (!item.is_stock_item) tag = "Service";
		else tag = item.item_group || "";

		return `${brand ? `<div class="card-brand">${esc(brand)}</div>` : ""}
			<div class="card-name">${esc(name)}</div>
			${tag ? `<div class="card-tag">${esc(tag)}</div>` : ""}
			${item.sellable ? "" : '<div class="card-tag out">Not here</div>'}`;
	}

	function paintCatalogue() {
		const grid = $("grid");
		grid.className = "pos-grid" + (state.view === "list" ? " is-list" : "");

		if (!state.items.length) {
			grid.innerHTML = '<div class="pos-loading">Nothing matches that search.</div>';
			return;
		}

		grid.innerHTML = state.items.map((item) => `
			<article class="card ${item.sellable ? "" : "is-out"}" data-code="${esc(item.item_code)}"
			         title="${esc(item.item_name)}${item.is_stock_item
					? " · " + (item.branch_qty > 0 ? item.branch_qty + " in stock here" : "none here")
					: ""}">
				${badge(item)}
				<div class="card-main">
					<div class="card-thumb">${thumb(item)}</div>
					<div class="card-body">${cardLines(item)}</div>
				</div>
				<div class="card-foot">
					<span class="card-rate">${moneyShort(item.rate)}</span>
					<button class="card-add" data-code="${esc(item.item_code)}" aria-label="Add">+</button>
				</div>
			</article>`).join("");

		grid.querySelectorAll(".card, .card-add").forEach((node) => {
			node.addEventListener("click", (event) => {
				event.stopPropagation();
				pick(node.dataset.code);
			});
		});
	}

	function pick(code) {
		const item = state.items.find((row) => row.item_code === code);
		if (!item) return;
		if (!item.sellable) return showElsewhere(item);
		if (item.has_serial) return askSerial(item);
		addLine(item, null);
	}

	// --------------------------------------------------------------- scan
	async function handleScan(code) {
		try {
			const found = await A3.call("a3_retail.api.pos.scan", { code });
			if (!found || !found.item) return say("Nothing found for " + code + ".", "error");

			if (found.kind === "serial") {
				addLine(found.item, found.serial_no);
				say("Added " + found.item.item_name + " · " + (found.imei || found.serial_no), "ok");
			} else if (found.item.has_serial) {
				askSerial(found.item);
			} else {
				addLine(found.item, null);
			}
			$("q").value = "";
			loadCatalogue();
		} catch (error) {
			say(error.message, "error");
		}
	}

	// ------------------------------------------------------------- serials
	async function askSerial(item, lineIndex) {
		const modal = $("serial-modal");
		$("serial-title").textContent = item.item_name;
		$("serial-list").innerHTML = '<li class="pos-loading">Loading IMEIs…</li>';
		$("serial-scan").value = "";
		modal.hidden = false;
		$("serial-scan").focus();

		const available = await A3.call("a3_retail.api.pos.serials", { item_code: item.item_code });
		const taken = new Set(state.cart.flatMap((line) => line.serials));
		const free = available.filter((row) => !taken.has(row.serial_no));

		if (!free.length) {
			$("serial-list").innerHTML = '<li class="pos-loading">No free IMEI for this model here.</li>';
			return;
		}

		$("serial-list").innerHTML = free.map((row) => `
			<li><button data-serial="${esc(row.serial_no)}">
				<span>${esc(row.imei || row.serial_no)}</span>
				<small>${row.age_days} days in stock</small>
			</button></li>`).join("");

		$("serial-list").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				modal.hidden = true;
				addLine(item, node.dataset.serial, lineIndex);
			});
		});

		$("serial-scan").onkeydown = (event) => {
			if (event.key !== "Enter") return;
			const scanned = $("serial-scan").value.trim();
			const match = free.find((row) => row.serial_no === scanned || row.imei === scanned);
			if (!match) return say("That IMEI is not in this branch's stock.", "error");
			modal.hidden = true;
			addLine(item, match.serial_no, lineIndex);
		};
	}

	// -------------------------------------------------------- cross-branch
	async function showElsewhere(item) {
		const modal = $("elsewhere-modal");
		$("elsewhere-title").textContent = item.item_name;
		$("elsewhere-note").textContent = "Not in " + state.branch + " right now. Checking the others…";
		$("elsewhere-list").innerHTML = "";
		modal.hidden = false;

		const rows = await A3.call("a3_retail.api.pos.stock_elsewhere", { item_code: item.item_code });
		const others = rows.filter((row) => !row.is_mine);

		if (!others.length) {
			$("elsewhere-note").textContent = "No branch has this model in stock.";
			return;
		}

		$("elsewhere-note").textContent = "Available at:";
		$("elsewhere-list").innerHTML = others.map((row) => `
			<li>
				<div><strong>${esc(row.branch)}</strong><small>${row.available} in stock</small></div>
				<button class="btn btn-quiet" data-branch="${esc(row.branch)}">Request transfer</button>
			</li>`).join("");

		$("elsewhere-list").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", async () => {
				node.disabled = true;
				node.textContent = "Requesting…";
				try {
					const result = await A3.call("a3_retail.api.pos.request_transfer", {
						item_code: item.item_code, source_branch: node.dataset.branch,
					});
					node.textContent = result.stock_request;
					say("Transfer requested from " + node.dataset.branch + ".", "ok");
				} catch (error) {
					node.disabled = false;
					node.textContent = "Request transfer";
					say(error.message, "error");
				}
			});
		});
	}

	// ----------------------------------------------------------------- cart
	function addLine(item, serial, lineIndex) {
		if (typeof lineIndex === "number") {
			state.cart[lineIndex].serials.push(serial);
			state.cart[lineIndex].qty = state.cart[lineIndex].serials.length;
			return paintCart();
		}

		const existing = state.cart.find((line) => line.item_code === item.item_code);
		if (existing && !item.has_serial) {
			existing.qty += 1;
		} else if (existing && serial) {
			if (existing.serials.includes(serial)) return say("That IMEI is already on the bill.", "error");
			existing.serials.push(serial);
			existing.qty = existing.serials.length;
		} else {
			state.cart.push({
				item_code: item.item_code, item_name: item.item_name, image: item.image,
				rate: item.rate, min_price: item.min_price, gst_rate: item.gst_rate || 18,
				qty: 1, has_serial: item.has_serial, is_device: item.is_device,
				serials: serial ? [serial] : [],
			});
		}
		paintCart();
	}

	function paintCart() {
		const rows = $("lines");
		if (!state.cart.length) {
			rows.innerHTML = '<div class="bill-empty">Tap an item to start the bill.</div>';
		} else {
			rows.innerHTML = state.cart.map((line, index) => `
				<div class="bill-row">
					<div class="bill-item">
						<div class="bill-thumb">${line.image
						? `<img class="${isPhoto(line.image) ? "is-photo" : ""}" src="${esc(line.image)}" alt="">`
						: ""}</div>
						<div>
							<div class="bill-name">${esc(line.item_name)}</div>
							${line.serials.length
								? `<div class="bill-imei">IMEI: ${line.serials.map(esc).join(", ")}</div>` : ""}
						</div>
					</div>
					<div class="qty">
						<button data-act="minus" data-i="${index}">−</button>
						<span>${line.qty}</span>
						<button data-act="plus" data-i="${index}">+</button>
					</div>
					<input class="rate" data-i="${index}" inputmode="decimal"
					       value="${moneyShort(line.rate)}" aria-label="Rate">
					<span class="amount">${moneyShort(line.rate * line.qty)}</span>
					<button class="row-x" data-act="remove" data-i="${index}" aria-label="Remove">×</button>
				</div>`).join("");
		}

		rows.querySelectorAll("[data-act]").forEach((node) => {
			node.addEventListener("click", () => {
				const index = Number(node.dataset.i);
				const line = state.cart[index];
				if (node.dataset.act === "remove") state.cart.splice(index, 1);
				if (node.dataset.act === "minus") {
					if (line.has_serial) line.serials.pop();
					line.qty = Math.max(line.qty - 1, 0);
					if (line.qty === 0) state.cart.splice(index, 1);
				}
				if (node.dataset.act === "plus") {
					if (line.has_serial) {
						const item = state.items.find((row) => row.item_code === line.item_code);
						return askSerial(item || line, index);
					}
					line.qty += 1;
				}
				paintCart();
			});
		});

		rows.querySelectorAll(".rate").forEach((node) => {
			node.addEventListener("change", () => {
				const line = state.cart[Number(node.dataset.i)];
				// The cell reads like the printed bill (₹79,999), so strip the
				// formatting back off before believing the number.
				const rate = Number(String(node.value).replace(/[^0-9.]/g, ""));
				if (line.min_price && rate < line.min_price) {
					say(line.item_name + " cannot go below " + moneyShort(line.min_price)
						+ " — a manager has to approve that.", "error");
				}
				line.rate = rate;
				paintCart();
			});
		});

		paintTotals();
	}

	function totals() {
		const subtotal = state.cart.reduce((sum, line) => sum + line.rate * line.qty, 0);
		const value = Number($("discount-value").value) || 0;
		const discount = $("discount-type").value === "%"
			? subtotal * Math.min(value, 100) / 100
			: Math.min(value, subtotal);
		const taxable = subtotal - discount;
		const rate = state.cart.length
			? Math.max(...state.cart.map((line) => line.gst_rate || 18)) : 18;
		const gst = taxable * rate / 100;
		return { subtotal, discount, taxable, rate, gst, grand: taxable + gst };
	}

	function paintTotals() {
		const sums = totals();
		const count = state.cart.reduce((sum, line) => sum + line.qty, 0);

		$("count").textContent = count;
		$("items-total").textContent = moneyShort(sums.subtotal);
		$("subtotal").textContent = moneyShort(sums.subtotal);
		$("discount-amount").textContent = "- " + moneyShort(sums.discount);
		$("taxable").textContent = moneyShort(sums.taxable);
		$("gst-rate").textContent = sums.rate;
		$("gst").textContent = money(sums.gst);
		$("grand").textContent = money(sums.grand);

		// Change belongs to the drawer. A card or a UPI collection is charged the
		// bill exactly, so showing change there would have the counter hand out
		// money it never took.
		const received = Number($("received").value) || 0;
		const change = state.mode === "Cash" ? Math.max(received - sums.grand, 0) : 0;
		$("change").textContent = money(change);
		$("checkout").disabled = !state.cart.length || !state.customer;
	}

	// ------------------------------------------------------------ customer
	async function findCustomer() {
		const mobile = $("mobile").value.trim();
		if (mobile.length !== 10) return say("Enter the ten-digit mobile number.", "error");

		const found = await A3.call("a3_retail.api.pos.find_customer", { mobile_no: mobile });
		if (found) return fillCustomer(found);

		state.customer = null;
		$("customer-name").value = "";
		setChip("New customer", "warn");
		$("customer-history").innerHTML = "";
		say("New number — add the name and save.");
		paintTotals();
	}

	function fillCustomer(found) {
		state.customer = found.name;
		$("mobile").value = found.a3_mobile_no || found.mobile_no || $("mobile").value;
		$("customer-name").value = found.customer_name || "";
		$("customer-email").value = found.email_id || "";
		const address = found.address || {};
		$("customer-address").value = address.address_line1 || "";
		$("customer-city").value = address.city || "";
		if (address.state) $("customer-state").value = address.state;
		$("customer-pin").value = address.pincode || "";
		setChip("Known customer", "good");

		const history = found.history || {};
		$("customer-history").innerHTML =
			`<span>${history.invoices || 0} purchases</span><span>${history.repairs || 0} repairs</span>` +
			(history.last_seen ? `<span>last seen ${esc(history.last_seen)}</span>` : "");
		say("");
		paintTotals();
	}

	/** The chip and the save row stay out of the way until there is a customer
	 *  in play — a resting counter shows the plain panel. */
	function setChip(text, tone) {
		const chip = $("customer-chip");
		chip.textContent = text || "";
		chip.className = "chip" + (tone ? " " + tone : "");
		chip.hidden = !text;
		$("cust-foot").hidden = !text;
	}

	async function saveCustomer() {
		const name = $("customer-name").value.trim();
		if (!name) return say("The customer needs a name.", "error");

		try {
			const saved = await A3.call("a3_retail.api.pos.save_customer", {
				mobile_no: $("mobile").value.trim(),
				customer_name: name,
				email: $("customer-email").value.trim(),
				address_line1: $("customer-address").value.trim(),
				city: $("customer-city").value.trim(),
				state: $("customer-state").value.trim(),
				pincode: $("customer-pin").value.trim(),
			});
			state.customer = saved.name;
			setChip("Ready to bill", "good");
			say("Customer saved.", "ok");
			paintTotals();
		} catch (error) {
			say(error.message, "error");
		}
	}

	let custTimer;
	async function searchCustomers() {
		const query = $("cust-q").value.trim();
		const box = $("cust-results");
		if (query.length < 3) { box.hidden = true; return; }

		const rows = await A3.call("a3_retail.api.pos.search_customers", { query });
		if (!rows.length) { box.hidden = true; return; }

		box.hidden = false;
		box.innerHTML = rows.map((row) => `
			<li><button data-mobile="${esc(row.mobile_no || "")}" data-name="${esc(row.name)}">
				<strong>${esc(row.customer_name)}</strong>
				<small>${esc(row.mobile_no || row.email_id || "")}</small>
			</button></li>`).join("");

		box.querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", async () => {
				box.hidden = true;
				$("cust-q").value = "";
				if (node.dataset.mobile) {
					$("mobile").value = node.dataset.mobile;
					return findCustomer();
				}
				state.customer = node.dataset.name;
				$("customer-name").value = node.textContent.trim();
				setChip("Ready to bill", "good");
				paintTotals();
			});
		});
	}

	function newCustomer() {
		state.customer = null;
		["mobile", "customer-name", "customer-email", "customer-address",
		 "customer-city", "customer-pin"].forEach((id) => { $(id).value = ""; });
		$("customer-history").innerHTML = "";
		setChip("New customer", "warn");
		$("mobile").focus();
		paintTotals();
	}

	// ------------------------------------------------------- quick actions
	function holds() {
		try { return JSON.parse(localStorage.getItem(HOLD_KEY) || "[]"); }
		catch (error) { return []; }
	}

	function holdBill() {
		if (!state.cart.length) return say("Nothing to hold.", "error");
		const list = holds();
		list.unshift({
			at: new Date().toISOString(), customer: state.customer,
			mobile: $("mobile").value, cart: state.cart,
		});
		localStorage.setItem(HOLD_KEY, JSON.stringify(list.slice(0, 20)));
		state.cart = [];
		paintCart();
		say("Bill held. Press F6 to bring it back.", "ok");
	}

	function openDrafts() {
		const list = holds();
		showList("Held bills", list.length ? "" : "Nothing is on hold.",
			list.map((hold, index) => ({
				title: (hold.cart[0] ? hold.cart[0].item_name : "Empty") +
					(hold.cart.length > 1 ? ` +${hold.cart.length - 1} more` : ""),
				meta: new Date(hold.at).toLocaleString("en-IN") + (hold.mobile ? " · " + hold.mobile : ""),
				action: "Resume", index,
			})),
			(index) => {
				const list2 = holds();
				const hold = list2.splice(index, 1)[0];
				localStorage.setItem(HOLD_KEY, JSON.stringify(list2));
				state.cart = hold.cart;
				if (hold.mobile) { $("mobile").value = hold.mobile; findCustomer(); }
				paintCart();
				$("list-modal").hidden = true;
			});
	}

	async function recentBills() {
		const rows = await A3.call("a3_retail.api.pos.recent_invoices", { limit: 15 });
		showList("Today's bills", rows.length ? "" : "Nothing billed yet.",
			rows.map((row) => ({
				title: row.name + " · " + (row.customer_name || ""),
				meta: moneyShort(row.grand_total), link: row.print_url, action: "PDF",
			})));
	}

	async function showLoyalty() {
		if (!state.customer) return say("Find the customer first.", "error");
		const data = await A3.call("a3_retail.api.pos.loyalty", { customer: state.customer });
		showList("Loyalty · " + state.customer, `Tier: ${data.tier}`, [
			{ title: "Bills", meta: String(data.bills) },
			{ title: "Lifetime spend", meta: moneyShort(data.spend) },
			{ title: "Repairs", meta: String(data.repairs) },
			{ title: "Last bill", meta: data.last_bill || "—" },
		]);
	}

	function priceCheck() {
		$("q").focus();
		$("q").select();
		say("Scan or type to check a price — nothing is added until you tap the item.");
	}

	function showList(title, note, rows, onPick) {
		$("list-title").textContent = title;
		$("list-note").textContent = note || "";
		$("list-body").innerHTML = rows.map((row, index) => `
			<li>
				<div><strong>${esc(row.title)}</strong><small>${esc(row.meta || "")}</small></div>
				${row.link ? `<a class="btn btn-quiet" href="${esc(row.link)}" target="_blank" rel="noopener">${esc(row.action)}</a>`
					: (row.action ? `<button class="btn btn-quiet" data-i="${row.index ?? index}">${esc(row.action)}</button>` : "")}
			</li>`).join("");

		if (onPick) {
			$("list-body").querySelectorAll("button[data-i]").forEach((node) => {
				node.addEventListener("click", () => onPick(Number(node.dataset.i)));
			});
		}
		$("list-modal").hidden = false;
	}

	// ------------------------------------------------------------ checkout
	async function checkout(draft) {
		const missing = state.cart.find((line) => line.has_serial && line.serials.length !== line.qty);
		if (missing) return say(missing.item_name + " still needs its IMEI.", "error");

		const sums = totals();
		$("checkout").disabled = true;
		say("Billing…");

		try {
			const result = await A3.call(
				draft ? "a3_retail.api.pos.save_draft" : "a3_retail.api.pos.checkout", {
				payload: {
					invoice: state.editing,
					customer: state.customer,
					mode_of_payment: state.mode,
					notes: $("notes").value.trim(),
					received_amount: Number($("received").value) || 0,
					discount_percent: $("discount-type").value === "%"
						? Number($("discount-value").value) || 0 : 0,
					discount_amount: $("discount-type").value === "₹"
						? Number($("discount-value").value) || 0 : 0,
					items: state.cart.map((line) => ({
						item_code: line.item_code, qty: line.qty, rate: line.rate,
						serials: line.serials,
					})),
				},
			});
			if (draft) {
				state.editing = result.invoice;
				markEditing(result.invoice);
				say(result.invoice + " saved as a draft — it is waiting in Bills.", "ok");
				$("checkout").disabled = false;
				return;
			}
			done(result, sums);
		} catch (error) {
			say(error.message || "Could not complete the sale.", "error");
			$("checkout").disabled = false;
		}
	}

	function done(result, sums) {
		$("done-note").textContent = `${result.invoice} · ${result.customer_name} · `
			+ money(result.grand_total) + (result.change ? ` · change ${money(result.change)}` : "");
		$("print-invoice").href = result.print_url;
		$("done-modal").hidden = false;
		$("bill-no").textContent = result.invoice;

		state.cart = [];
		state.customer = null;
		newCustomer();
		setChip("");
		$("notes").value = "";
		$("received").value = "";
		$("discount-value").value = "";
		say("");
		paintCart();
	}

	// ------------------------------------------------------- editing a draft
	/** A draft from Bills is the counter's own cart again: same lines, same
	 *  customer, same discount — so saving it updates that bill rather than
	 *  writing a second one. */
	async function editDraft(name) {
		try {
			const bill = await A3.call("a3_retail.api.pos.load_invoice", { invoice: name });
			state.editing = bill.invoice;
			state.customer = bill.customer;
			state.cart = (bill.items || []).map((line) => ({ ...line }));
			state.mode = bill.mode_of_payment || "Cash";

			$("customer-name").value = bill.customer_name || "";
			if (bill.mobile_no) $("mobile").value = bill.mobile_no;
			$("notes").value = bill.notes || "";
			if (bill.discount_percent) {
				$("discount-type").value = "%";
				$("discount-value").value = bill.discount_percent;
			} else if (bill.discount_amount) {
				$("discount-type").value = "₹";
				$("discount-value").value = bill.discount_amount;
			}
			setChip("Editing " + bill.invoice, "warn");
			markEditing(bill.invoice);
			paintCart();
			say("Editing " + bill.invoice + ". Saving replaces that bill.", "ok");
		} catch (error) {
			say(error.message, "error");
		}
	}

	function markEditing(name) {
		$("bill-no").textContent = name;
		const heading = document.querySelector(".topbar-branch h1");
		if (heading) heading.textContent = "Editing Invoice #" + name;
		$("checkout").innerHTML = 'Update &amp; Submit <span class="key">F9</span>';
		const hold = document.querySelector('.quick[data-action="hold"] .quick-label');
		if (hold) hold.textContent = "Save Draft";
	}

	// ----------------------------------------------------------------- EMI
	/**
	 * What this basket can be financed on.
	 *
	 * The schemes come from the EMI module's own service — the same one the
	 * financing desk uses — so a counter is never offered a scheme the
	 * application would refuse. Nothing is charged here: the sale completes only
	 * once the financier has approved, which the invoice itself enforces.
	 */
	async function emiSchemes() {
		if (!state.cart.length) {
			return say("Put the products in the basket first — the schemes depend on what is "
				+ "being bought and what it comes to.", "error");
		}

		const sums = totals();
		const first = state.cart[0] || {};
		showList("Loading the schemes…", money(sums.grand), []);

		try {
			const schemes = await A3.call("a3_retail.api.emi.eligible_schemes", {
				invoice_total: sums.grand,
				item_code: first.item_code || null,
			});

			if (!schemes.length) {
				return showList("No finance for this basket", money(sums.grand), [{
					title: "No active scheme covers this purchase",
					meta: "Try a different basket, or ask head office to configure a scheme.",
				}]);
			}

			showList(
				"EMI schemes for " + money(sums.grand),
				"Indicative — the financier decides the real instalment",
				schemes.map((scheme) => ({
					title: `${scheme.finance_partner} · ${scheme.tenure_months} months · ${
						money(scheme.emi_amount)}/month`,
					meta: `down payment ${money(scheme.suggested_down_payment)} · ${
						scheme.scheme_name}`,
					action: "Apply",
				})),
				(index) => {
					$("list-modal").hidden = true;
					startEmiApplication(schemes[index], sums);
				});
		} catch (error) {
			showList("Could not read the schemes", "", [{ title: error.message, meta: "" }]);
		}
	}

	async function startEmiApplication(scheme, sums) {
		if (!state.customer) {
			return say("Pick the customer first — a loan is made to a person, not to a basket.",
				"error");
		}

		try {
			const result = await A3.call("a3_retail.api.emi.save_application", {
				payload: {
					customer: state.customer,
					partner: scheme.finance_partner,
					scheme: scheme.name,
					down_payment: scheme.suggested_down_payment,
					invoice_total: sums.grand,
					items: state.cart.map((row) => ({
						item_code: row.item_code, item_name: row.item_name,
						qty: row.qty, rate: row.rate, serial_no: (row.serials || [])[0] || null,
					})),
				},
			});
			window.location = "/retail/emi?application=" + encodeURIComponent(result.application);
		} catch (error) {
			// The KYC a financier needs is asked for on the financing desk, which
			// is where the counter is sent with the basket already attached.
			window.location = "/retail/emi?tab=applications&customer="
				+ encodeURIComponent(state.customer);
		}
	}

	// --------------------------------------------------------------- start
	function start(options) {
		state.branch = options.branch;
		state.groups = options.groups || [];

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(loadCatalogue, 220);
		});
		$("q").addEventListener("keydown", (event) => {
			// A scanner types fast and ends with Enter — treat that as a scan.
			if (event.key === "Enter" && $("q").value.trim()) handleScan($("q").value.trim());
		});
		$("in-stock").addEventListener("change", loadCatalogue);

		// Listen on the row, not the strip: "+ N More" sits outside the scrolling
		// strip so it cannot be pushed off the edge.
		document.querySelector(".pos-tabsrow").addEventListener("click", (event) => {
			const tab = event.target.closest(".tab");
			if (!tab) return;
			if (tab.id === "more-groups") return showAllGroups();
			$("groups").querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
			tab.classList.add("is-active");
			state.group = tab.dataset.group || "";
			loadCatalogue();
		});

		document.querySelectorAll(".view").forEach((node) => {
			node.addEventListener("click", () => {
				document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
				node.classList.add("is-active");
				state.view = node.dataset.view;
				paintCatalogue();
			});
		});

		$("find-customer").addEventListener("click", findCustomer);
		$("mobile").addEventListener("keydown", (e) => { if (e.key === "Enter") findCustomer(); });
		$("save-customer").addEventListener("click", saveCustomer);
		$("new-customer").addEventListener("click", newCustomer);
		$("cust-q").addEventListener("input", () => {
			clearTimeout(custTimer);
			custTimer = setTimeout(searchCustomers, 250);
		});

		$("clear-cart").addEventListener("click", () => { state.cart = []; paintCart(); });
		$("discount-type").addEventListener("change", paintTotals);
		$("discount-value").addEventListener("input", paintTotals);
		$("received").addEventListener("input", paintTotals);
		$("checkout").addEventListener("click", checkout);

		$("pay-tiles").addEventListener("click", (event) => {
			const tile = event.target.closest(".pay");
			if (!tile) return;
			$("pay-tiles").querySelectorAll(".pay").forEach((t) => t.classList.remove("is-active"));
			tile.classList.add("is-active");
			state.mode = tile.dataset.mode;
			paintTotals();
			// EMI is not a way of taking money at the till — it is a loan somebody
			// else has to approve first. Picking it opens the financing desk's own
			// scheme list rather than pretending the sale is done.
			if (state.mode === "EMI") emiSchemes();
		});

		const actions = {
			recent: recentBills, hold: () => checkout(true), drafts: openDrafts,
			loyalty: showLoyalty, price: priceCheck,
			clear: () => { state.cart = []; paintCart(); },
		};
		document.querySelectorAll(".quick").forEach((node) => {
			node.addEventListener("click", () => actions[node.dataset.action]());
		});

		document.addEventListener("keydown", (event) => {
			const keys = { F3: "recent", F4: "hold", F5: "clear", F6: "drafts",
			               F7: "loyalty", F8: "price" };
			if (keys[event.key]) { event.preventDefault(); actions[keys[event.key]](); }
			if (event.key === "F9") { event.preventDefault(); if (!$("checkout").disabled) checkout(); }
			if (event.key === "Escape") {
				document.querySelectorAll(".modal:not([hidden])").forEach((m) => { m.hidden = true; });
			}
		});

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => { node.closest(".modal").hidden = true; });
		});
		document.querySelectorAll(".modal").forEach((modal) => {
			modal.addEventListener("click", (event) => {
				if (event.target === modal) modal.hidden = true;
			});
		});

		const collapse = document.getElementById("side-collapse");
		if (collapse) {
			collapse.addEventListener("click", () => {
				document.body.classList.toggle("side-collapsed");
				collapse.textContent = document.body.classList.contains("side-collapsed") ? "›" : "‹";
			});
		}

		loadCatalogue();
		paintCart();

		// Bills hands a draft back here to be edited, and Customers hands over a
		// person to sell to.
		const params = new URLSearchParams(window.location.search);
		// Parts & Accessories hands an item over to be sold; the counter still
		// picks the customer and takes the money.
		if (params.get("item")) {
			$("q").value = params.get("item");
			state.filters = state.filters || {};
			loadCatalogue().then(() => {
				const item = state.items.find((row) => row.item_code === params.get("item"));
				if (item) pick(item.item_code);
			});
		}
		if (params.get("invoice")) editDraft(params.get("invoice"));
		else if (params.get("customer")) {
			state.customer = params.get("customer");
			$("customer-name").value = params.get("customer");
			setChip("Ready to bill", "good");
			paintTotals();
		}
	}

	function showAllGroups() {
		showList("Item groups", "", state.groups.map((group, index) => ({
			title: group, meta: "", action: "Show", index,
		})), (index) => {
			state.group = state.groups[index];
			$("list-modal").hidden = true;
			$("groups").querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
			loadCatalogue();
		});
	}

	return { start };
})();
