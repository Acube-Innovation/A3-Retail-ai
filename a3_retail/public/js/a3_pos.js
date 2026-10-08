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
		// Split tender: the customer settles one bill in more than one form.
		// `splits` is only read while `split` is on, so the ordinary one-tile
		// path is untouched.
		split: false, splits: [],
		// The assistant serving this customer at a shared till.
		soldBy: "",
		// Which bank approved the purchase, when the bill is financed.
		financier: "",
		// The accounts a non-cash collection can be banked into, and the one the
		// counter picked for this bill.
		bankAccounts: [],
		bankAccount: "",
		// The banks this shop sells on EMI through.
		financiers: [],
		// Whether the price list already carries GST — set from the branch's tax
		// template so the running total matches the invoice that gets posted.
		pricesIncludeTax: false,
		// Set once the cashier types their own tendered figure, so the bill stops
		// overwriting it as the cart changes.
		receivedTyped: false,
		// Which discount box was typed in last; the other one follows it.
		discountBy: "amt",
	};
	// The tiles a counter can split across. EMI is absent on purpose — it is a
	// loan somebody else approves, not money taken at the till.
	const SPLIT_MODES = ["Cash", "UPI", "Card", "Wallet", "Other"];
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
		const rate = state.cart.length
			? Math.max(...state.cart.map((line) => line.gst_rate || 18)) : 18;
		const factor = 1 + rate / 100;

		// Where the price list is an all-in price, the GST is already inside the
		// rate and has to be backed out; where it is not, it is added on top. Which
		// one applies comes from the branch's own tax template, so this screen and
		// the posted invoice always agree.
		const gross = state.pricesIncludeTax ? subtotal : subtotal * factor;

		// "Grand Total" takes the discount off what the customer actually hands
		// over; "Net Total" takes it off the pre-tax figure, so the bill moves by
		// the discount plus the tax on it. Either way the base the percentage
		// applies to is the same figure the rupee box is measured against.
		const onGrand = $("discount-on").value === "Grand Total";
		const base = onGrand ? gross : gross / factor;
		const discount = Math.min(discountAmount(base), base);

		if (onGrand) {
			const grand = gross - discount;
			const taxable = grand / factor;
			return { subtotal, discount, taxable, rate, gst: grand - taxable, grand };
		}

		const net = gross / factor;
		const taxable = net - discount;
		const gst = taxable * rate / 100;
		return { subtotal, discount, taxable, rate, gst, grand: taxable + gst };
	}

	/** What the discount comes to in rupees, from whichever box was typed in. */
	function discountAmount(base) {
		if (state.discountBy === "pct") {
			const pct = Math.min(Number($("discount-pct").value) || 0, 100);
			return base * pct / 100;
		}
		return Number($("discount-amt").value) || 0;
	}

	/** Fill the box the cashier did not type in, so both read the same deal. */
	function mirrorDiscount(base) {
		if (state.discountBy === "pct") {
			const pct = Math.min(Number($("discount-pct").value) || 0, 100);
			$("discount-amt").value = pct ? (base * pct / 100).toFixed(2) : "";
		} else {
			const amt = Number($("discount-amt").value) || 0;
			$("discount-pct").value = amt && base ? (amt / base * 100).toFixed(2) : "";
		}
	}

	/** Which of the shop's accounts this collection reached. */
	function askBankAccount() {
		if (!state.bankAccounts.length) {
			return say("No bank account is set up for this company.", "error");
		}
		showList(
			"Into which account?",
			state.mode + " collection",
			state.bankAccounts.map((a) => ({
				title: a.label,
				meta: a.kind === "Cash" ? "cash in hand" : "bank account",
				action: "Select",
			})),
			(index) => {
				$("list-modal").hidden = true;
				const picked = state.bankAccounts[index];
				state.bankAccount = picked.account;
				$("bank-pick").textContent = picked.label;
				paintTotals();
			});
	}

	/** A card or UPI collection has to say which bank it reached. */
	function paintBankRow() {
		const row = $("bank-row");
		if (!row) return;
		// EMI settles through the financier's own receivable, and cash goes in the
		// drawer — neither needs an account chosen.
		const wants = state.bankAccounts.length && !state.split
			&& state.mode !== "Cash" && state.mode !== "EMI"
			&& !String(state.mode || "").startsWith("EMI");
		row.hidden = !wants;
	}

	function paintTotals() {
		const sums = totals();
		const count = state.cart.reduce((sum, line) => sum + line.qty, 0);

		$("count").textContent = count;
		$("items-total").textContent = moneyShort(sums.subtotal);
		$("subtotal").textContent = moneyShort(sums.subtotal);
		$("discount-amount").textContent = "- " + moneyShort(sums.discount);
		mirrorDiscount($("discount-on").value === "Grand Total"
			? sums.subtotal * (state.pricesIncludeTax ? 1 : 1 + sums.rate / 100)
			: sums.subtotal * (state.pricesIncludeTax ? 1 : 1 + sums.rate / 100) / (1 + sums.rate / 100));
		$("taxable").textContent = moneyShort(sums.taxable);
		$("gst-rate").textContent = sums.rate;
		$("gst").textContent = money(sums.gst);
		$("grand").textContent = money(sums.grand);

		// The amount due is the normal case — a card or UPI is charged exactly, and
		// most cash customers hand over the round figure. Filling it in means the
		// payment is recorded without anyone retyping the total; the moment the
		// cashier types something else, that is left alone.
		const due = Math.round(sums.grand);
		if (!state.receivedTyped && !state.split) {
			$("received").value = state.cart.length ? due : "";
		}

		// Change belongs to the drawer. A card or a UPI collection is charged the
		// bill exactly, so showing change there would have the counter hand out
		// money it never took.
		const received = Number($("received").value) || 0;
		const change = state.mode === "Cash" ? Math.max(received - sums.grand, 0) : 0;
		$("change").textContent = money(change);

		paintBankRow();
		const shortOnSplit = state.split ? paintSplit(sums.grand) : false;
		// Once the till offers a list of assistants, the bill needs one chosen —
		// an unattributed sale pays nobody their incentive.
		const needSeller = !$("seller-row").hidden && !state.soldBy;
		$("checkout").disabled = !state.cart.length || !state.customer
			|| shortOnSplit || needSeller;
		// A bill can be put down before the customer is known — that is often why
		// it is being put down — so Hold only asks for something in the cart.
		$("hold").disabled = !state.cart.length;
	}

	// --------------------------------------------------------------- split
	/** Draw the split lines and the running tally. Returns true while short. */
	function paintSplit(payable) {
		const host = $("split-lines");
		if (host.childElementCount !== state.splits.length) {
			host.textContent = "";
			state.splits.forEach((line, index) => host.appendChild(splitRow(line, index)));
		}

		const entered = state.splits.reduce((sum, line) => sum + (Number(line.amount) || 0), 0);
		const gap = payable - entered;
		const cash = state.splits
			.filter((line) => line.mode === "Cash")
			.reduce((sum, line) => sum + (Number(line.amount) || 0), 0);

		$("split-entered").textContent = money(entered);

		// Over-tendering is only real money if a cash line covers it; anything
		// else is a typing error, so it is named as one rather than as change.
		let label = "Still to pay";
		let value = Math.max(gap, 0);
		let tone = "";
		if (gap <= 0.5) {
			const over = -gap;
			if (over <= 0.5) {
				label = "Balanced"; value = 0; tone = "is-ok";
			} else if (over <= cash + 0.5) {
				label = "Change from cash"; value = over; tone = "is-ok";
			} else {
				label = "Over the bill"; value = over; tone = "is-bad";
			}
		}
		$("split-gap-label").textContent = label;
		$("split-gap").textContent = money(value);
		$("split-tally").className = "split-tally " + tone;

		return gap > 0.5 || (-gap > cash + 0.5);
	}

	function splitRow(line, index) {
		const row = document.createElement("div");
		row.className = "split-line";

		// On a financed line the first cell is the bank the money is credited
		// into — that is what the counter is looking for — and the financier
		// itself is named underneath. On every other line it is the tender.
		const select = line.kind === "emi"
			? accountSelect(index)
			: modeSelect(line, index);
		if (line.kind === "emi") select.classList.add("is-account");

		const wrap = document.createElement("div");
		wrap.className = "input-rupee";
		const rupee = document.createElement("span");
		rupee.textContent = "₹";
		const amount = document.createElement("input");
		amount.type = "number";
		amount.min = "0";
		amount.step = "1";
		amount.placeholder = "0";
		amount.value = line.amount || "";
		amount.setAttribute("aria-label", "Amount paid by " + line.mode);
		amount.addEventListener("input", () => {
			state.splits[index].amount = Number(amount.value) || 0;
			// Whatever the customer puts down is money the financier no longer
			// has to lend, so the financed line absorbs the difference.
			rebalanceAgainstEmi(index);
			paintTotals();
		});
		wrap.append(rupee, amount);

		const remove = document.createElement("button");
		remove.type = "button";
		remove.className = "split-drop";
		remove.textContent = "×";
		remove.title = "Remove this payment";
		remove.setAttribute("aria-label", "Remove this payment");
		remove.disabled = state.splits.length <= 1;
		remove.addEventListener("click", () => {
			state.splits.splice(index, 1);
			$("split-lines").textContent = "";
			paintTotals();
		});

		row.append(select, wrap, remove);

		// Under the amount, in words rather than another table row: which bank
		// this money reaches, and for the financed line which bank it came from.
		// Both are selectable, because a counter should be able to correct them.
		const caption = document.createElement("div");
		caption.className = "split-bank";
		if (line.kind === "emi") {
			caption.append(captionLabel("financed by "), financierSelect(index));
		} else if (line.mode !== "Cash") {
			const named = state.bankAccounts.find((a) => a.account === line.account);
			const pick = document.createElement("button");
			pick.type = "button";
			pick.className = "split-bank-pick";
			pick.textContent = named ? named.label : "choose account";
			pick.addEventListener("click", () => askSplitAccount(index));
			caption.append(captionLabel("into "), pick);
		}
		if (caption.childElementCount) row.append(caption);
		return row;
	}

	function modeSelect(line, index) {
		const select = document.createElement("select");
		select.setAttribute("aria-label", "Payment type");
		SPLIT_MODES.forEach((name) => {
			const option = document.createElement("option");
			option.value = name;
			option.textContent = name;
			if (name === line.mode) option.selected = true;
			select.appendChild(option);
		});
		select.addEventListener("change", () => {
			state.splits[index].mode = select.value;
			// Cash goes in the drawer; anything else has to say which bank, and
			// is asked for it there and then rather than left to be noticed.
			const wasCash = select.value === "Cash";
			if (wasCash) state.splits[index].account = "";
			$("split-lines").textContent = "";
			paintTotals();
			if (!wasCash && !state.splits[index].account) askSplitAccount(index);
		});
		return select;
	}

	/** The same dialog a single tender uses, for one line of a split. */
	function askSplitAccount(index) {
		if (!state.bankAccounts.length) {
			return say("No bank account is set up for this company.", "error");
		}
		showList(
			"Into which account?",
			state.splits[index].mode + " · " + money(state.splits[index].amount || 0),
			state.bankAccounts.map((a) => ({
				title: a.label,
				meta: a.kind === "Cash" ? "cash in hand" : "bank account",
				action: "Select",
			})),
			(picked) => {
				$("list-modal").hidden = true;
				state.splits[index].account = state.bankAccounts[picked].account;
				$("split-lines").textContent = "";
				paintTotals();
			});
	}

	function captionLabel(text) {
		const span = document.createElement("span");
		span.textContent = text;
		return span;
	}

	/** Which of the shop's accounts this line reaches. */
	function accountSelect(index) {
		const select = document.createElement("select");
		select.setAttribute("aria-label", "Bank account for this payment");
		const blank = document.createElement("option");
		blank.value = "";
		blank.textContent = "choose account";
		select.appendChild(blank);
		state.bankAccounts.forEach((a) => {
			const option = document.createElement("option");
			option.value = a.account;
			option.textContent = a.label;
			if (a.account === state.splits[index].account) option.selected = true;
			select.appendChild(option);
		});
		select.addEventListener("change", () => {
			state.splits[index].account = select.value;
			paintTotals();
		});
		return select;
	}

	/** Which bank financed the line, and therefore which account it credits. */
	function financierSelect(index) {
		const select = document.createElement("select");
		select.setAttribute("aria-label", "Financier");
		state.financiers.forEach((p) => {
			const option = document.createElement("option");
			option.value = p.partner;
			option.textContent = p.mode_of_payment || ("EMI - " + p.label);
			if (p.partner === state.splits[index].financier) option.selected = true;
			select.appendChild(option);
		});
		select.addEventListener("change", () => {
			const picked = state.financiers.find((p) => p.partner === select.value);
			applyFinancier(index, picked);
			$("split-lines").textContent = "";
			paintTotals();
		});
		return select;
	}

	function applyFinancier(index, partner) {
		if (!partner) return;
		const line = state.splits[index];
		line.financier = partner.partner;
		line.mode = partner.mode_of_payment || line.mode;
		line.account = partner.bank_account || "";
		state.financier = partner.partner;
	}

	/** The financed line carries whatever the customer has not put down. */
	function rebalanceAgainstEmi(changedIndex) {
		const emi = state.splits.findIndex((l) => l.kind === "emi");
		if (emi < 0 || emi === changedIndex) return;
		const payable = totals().grand;
		const others = state.splits.reduce(
			(sum, l, i) => i === emi ? sum : sum + (Number(l.amount) || 0), 0);
		state.splits[emi].amount = Math.max(payable - others, 0);
		const box = $("split-lines").children[emi];
		const input = box && box.querySelector("input");
		if (input) input.value = state.splits[emi].amount || "";
	}

	/** Seed the split with the balance still owing on the next unused mode. */
	function addSplitLine() {
		const used = state.splits.map((line) => line.mode);
		const next = SPLIT_MODES.find((name) => !used.includes(name)) || "Cash";
		const payable = totals().grand;
		const entered = state.splits.reduce((sum, line) => sum + (Number(line.amount) || 0), 0);
		state.splits.push({ mode: next, amount: Math.max(payable - entered, 0) || 0 });
		$("split-lines").textContent = "";
		paintTotals();
	}

	function setSplit(on) {
		state.split = on;
		$("split-toggle").setAttribute("aria-pressed", String(on));
		$("split-toggle").classList.toggle("is-active", on);
		$("pay-single").hidden = on;
		$("pay-split").hidden = !on;
		$("pay-tiles").classList.toggle("is-muted", on);

		if (on && state.splits.length) {
			$("split-lines").textContent = "";
		} else if (on && !state.splits.length) {
			// Open with the amount already on the bill against the selected tile,
			// so the usual case is one keystroke: change it, and add the balance.
			const payable = totals().grand;
			const first = state.mode === "EMI" ? "Cash" : (state.mode || "Cash");
			state.splits = [{ mode: first, amount: payable }];
		}
		$("split-lines").textContent = "";
		paintTotals();
	}

	// ------------------------------------------------------------ customer
	/** The panel fields that a saved record fills, and that a new sale clears. */
	const FILLED_FIELDS = ["customer-name", "customer-email", "customer-address",
	                       "customer-city", "customer-state", "customer-pin",
	                       "customer-gstin"];

	async function findCustomer() {
		const mobile = $("mobile").value.trim();
		if (mobile.length !== 10) return say("Enter the ten-digit mobile number.", "error");

		const found = await A3.call("a3_retail.api.pos.find_customer", { mobile_no: mobile });
		if (found) return fillCustomer(found);

		// Not on file. Take the new customer deliberately in one dialog rather
		// than letting the counter type into a panel that looks like a record.
		state.customer = null;
		clearCustomerFields();
		setChip("New customer", "warn");
		$("customer-history").innerHTML = "";
		say("");
		paintTotals();
		openNewCustomer(mobile);
	}

	/** A saved customer is shown, not edited: the till is for billing, and a
	 *  correction belongs in Customers where it is recorded against the record
	 *  rather than typed over mid-sale. */
	function lockCustomerFields(locked) {
		FILLED_FIELDS.forEach((id) => {
			const node = $(id);
			node.readOnly = locked;
			node.classList.toggle("is-locked", locked);
		});
		$("customer-gstin-fetch").disabled = locked;
		$("cust-edit").hidden = !locked;
	}

	function clearCustomerFields() {
		FILLED_FIELDS.forEach((id) => { $(id).value = ""; });
		$("customer-note").textContent = "";
		lockCustomerFields(false);
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
		$("customer-gstin").value = found.gstin || address.gstin || "";
		setChip(found.gstin ? "Known business" : "Known customer", "good");
		lockCustomerFields(true);
		$("customer-note").textContent =
			"On file — open Customers to change these details.";

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

	function openNewCustomer(mobile) {
		["nc-name", "nc-email", "nc-address", "nc-city", "nc-pin", "nc-gstin"]
			.forEach((id) => { $(id).value = ""; });
		$("nc-mobile").value = mobile;
		$("nc-note").textContent = "";
		$("new-customer-modal").hidden = false;
		$("nc-name").focus();
	}

	async function saveNewCustomer() {
		const name = $("nc-name").value.trim();
		if (!name) { $("nc-note").textContent = "The customer needs a name."; return; }
		try {
			const saved = await A3.call("a3_retail.api.pos.save_customer", {
				mobile_no: $("nc-mobile").value.trim(),
				customer_name: name,
				email: $("nc-email").value.trim(),
				address_line1: $("nc-address").value.trim(),
				city: $("nc-city").value.trim(),
				state: $("nc-state").value.trim(),
				pincode: $("nc-pin").value.trim(),
				gstin: $("nc-gstin").value.trim().toUpperCase(),
			});
			$("new-customer-modal").hidden = true;
			fillCustomer(saved);
			say(name + " added.", "ok");
		} catch (error) {
			$("nc-note").textContent = error.message || "Could not add that customer.";
		}
	}

	/** Look the firm up from its GST number, into whichever form asked. */
	async function gstinInto(gstinId, fields, noteId) {
		const gstin = $(gstinId).value.trim().toUpperCase();
		if (!gstin) return;
		const note = noteId ? $(noteId) : null;
		if (note) note.textContent = "Checking\u2026";
		try {
			const info = await A3.call("a3_retail.api.customer.gstin_info", { gstin });
			if (info.customer_name && !$(fields.name).value.trim())
				$(fields.name).value = info.customer_name;
			if (info.address_line1) $(fields.address).value = info.address_line1;
			if (info.city) $(fields.city).value = info.city;
			if (info.state) $(fields.state).value = info.state;
			if (info.pincode) $(fields.pin).value = info.pincode;
			const message = info.note
				|| ("Found " + (info.customer_name || gstin) + " on the GST portal.");
			if (note) note.textContent = message; else say(message, "ok");
		} catch (error) {
			const message = error.message || "Could not check that number.";
			if (note) note.textContent = message; else say(message, "error");
		}
	}

	const POS_GSTIN_FIELDS = { name: "customer-name", address: "customer-address",
	                           city: "customer-city", state: "customer-state",
	                           pin: "customer-pin" };

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
				gstin: $("customer-gstin").value.trim().toUpperCase(),
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
		 "customer-city", "customer-pin", "customer-gstin"]
			.forEach((id) => { $(id).value = ""; });
		lockCustomerFields(false);
		$("customer-note").textContent = "";
		$("customer-history").innerHTML = "";
		setChip("New customer", "warn");
		$("mobile").focus();
		paintTotals();
	}

	// ------------------------------------------------------- quick actions
	/** The branch's held bills — the drafts Hold (F4) saved on the server. Picking
	 *  one opens that bill at the counter, exactly as Edit does from Bills. */
	async function openDrafts() {
		showList("Held bills", "Loading…", []);
		try {
			const rows = await A3.call("a3_retail.api.pos.held_invoices");
			showList("Held bills", rows.length ? "" : "Nothing is on hold.",
				rows.map((row) => ({
					title: row.name + " · " + (row.customer_name || ""),
					meta: moneyShort(row.grand_total)
						+ (row.summary ? " · " + row.summary : "")
						+ " · " + new Date(String(row.modified).replace(" ", "T"))
							.toLocaleString("en-IN"),
					action: "Open",
				})),
				(index) => {
					window.location.href = "/retail/sales?invoice=" + encodeURIComponent(rows[index].name);
				});
		} catch (error) {
			showList("Held bills", error.message || "Could not load the held bills.", []);
		}
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
		// Guard against being wired straight to addEventListener: the click event
		// would arrive here as `draft` and, being truthy, would quietly turn every
		// completed sale into a saved draft.
		draft = draft === true;
		const missing = state.cart.find((line) => line.has_serial && line.serials.length !== line.qty);
		if (missing) return say(missing.item_name + " still needs its IMEI.", "error");

		const sums = totals();
		$("checkout").disabled = true;
		$("hold").disabled = true;
		say(draft ? "Holding…" : "Billing…");

		try {
			const result = await A3.call(
				draft ? "a3_retail.api.pos.save_draft" : "a3_retail.api.pos.checkout", {
				payload: {
					invoice: state.editing,
					customer: state.customer,
					mode_of_payment: state.mode,
					sold_by: state.soldBy || "",
					financier: state.financier || "",
					notes: $("notes").value.trim(),
					// An empty box and a typed zero mean different things: the first
					// is "the whole bill", the second is "nothing handed over". Sent
					// as null and 0 so the server can tell them apart.
					received_amount: $("received").value.trim() === ""
						? null : Number($("received").value) || 0,
					bank_account: $("bank-row").hidden ? "" : state.bankAccount,
					// Only sent when the counter is actually splitting; the server
					// falls back to the single tile otherwise.
					payments: (!draft && state.split)
						? state.splits
							.filter((line) => (Number(line.amount) || 0) > 0)
							.map((line) => ({
								mode_of_payment: line.mode, amount: Number(line.amount),
								account: line.account || "",
							}))
						: null,
					// A held bill keeps whatever is in the payment panel, so picking
					// it up again carries on from there instead of from Cash.
					tender: draft ? heldTender() : null,
					discount_percent: state.discountBy === "pct"
						? Number($("discount-pct").value) || 0 : 0,
					discount_amount: state.discountBy === "amt"
						? Number($("discount-amt").value) || 0 : 0,
					discount_on: $("discount-on").value,
					items: state.cart.map((line) => ({
						item_code: line.item_code, qty: line.qty, rate: line.rate,
						serials: line.serials,
					})),
				},
			});
			if (draft) {
				state.editing = result.invoice;
				markEditing(result.invoice);
				say(result.invoice + " is on hold — pick it up from Drafts (F6). "
					+ "It cannot be printed until it is completed.", "ok");
				$("checkout").disabled = false;
				$("hold").disabled = false;
				return;
			}
			done(result, sums);
		} catch (error) {
			say(error.message || (draft ? "Could not hold the bill."
				: "Could not complete the sale."), "error");
			$("checkout").disabled = false;
			$("hold").disabled = false;
		}
	}

	function done(result, sums) {
		// A split bill is worth spelling out on the confirmation — the counter has
		// just taken money in two forms and may need to reconcile the drawer.
		const tender = (result.payments && result.payments.length > 1)
			? " · " + result.payments
				.map((p) => `${p.mode_of_payment} ${money(p.amount)}`).join(" + ")
			: "";
		$("done-note").textContent = `${result.invoice} · ${result.customer_name} · `
			+ money(result.grand_total) + tender
			+ (result.change ? ` · change ${money(result.change)}` : "");
		$("print-invoice").href = result.print_url;
		$("done-modal").hidden = false;
		$("bill-no").textContent = result.invoice;

		state.cart = [];
		state.customer = null;
		newCustomer();
		setChip("");
		$("notes").value = "";
		$("received").value = "";
		state.receivedTyped = false;
		$("discount-pct").value = "";
		$("discount-amt").value = "";
		state.discountBy = "amt";
		state.splits = [];
		state.financier = "";
		state.bankAccount = "";
		if ($("bank-pick")) $("bank-pick").textContent = "Choose account";
		setSplit(false);
		say("");
		paintCart();
	}

	// ------------------------------------------------------- the held tender
	/** The payment panel as it stands, to park with a held bill. */
	function heldTender() {
		return {
			split: state.split,
			mode: state.mode,
			// Only a figure the cashier typed is kept; an untouched box means "the
			// whole bill", which may change by the time the bill is picked up.
			received_amount: state.receivedTyped && $("received").value.trim() !== ""
				? Number($("received").value) || 0 : null,
			bank_account: state.bankAccount || "",
			financier: state.financier || "",
			lines: state.split ? state.splits.map((line) => ({
				mode: line.mode, amount: Number(line.amount) || 0,
				account: line.account || "", financier: line.financier || "",
				kind: line.kind || "",
			})) : [],
		};
	}

	/** Put a held bill's payment panel back exactly as it was left. */
	function restoreTender(tender) {
		state.mode = tender.mode || "Cash";
		state.financier = tender.financier || "";
		state.bankAccount = tender.bank_account || "";

		// A financed bill was picked through the EMI tile; its mode is the
		// financier's own, which has no tile of its name.
		const tileMode = state.financier && !document.querySelector(
			`#pay-tiles .pay[data-mode="${CSS.escape(state.mode)}"]`) ? "EMI" : state.mode;
		$("pay-tiles").querySelectorAll(".pay").forEach((tile) => {
			tile.classList.toggle("is-active", tile.dataset.mode === tileMode);
		});

		if (tender.received_amount !== null && tender.received_amount !== undefined) {
			$("received").value = tender.received_amount;
			state.receivedTyped = true;
		}

		state.splits = (tender.lines || []).map((line) => ({
			mode: line.mode, amount: line.amount, account: line.account || "",
			financier: line.financier || "", ...(line.kind ? { kind: line.kind } : {}),
		}));
		setSplit(Boolean(tender.split && state.splits.length));
		paintBankLabel();
	}

	/** The single-tender bank button names the chosen account, once both are known. */
	function paintBankLabel() {
		if (!$("bank-pick")) return;
		const named = state.bankAccounts.find((a) => a.account === state.bankAccount);
		$("bank-pick").textContent = named ? named.label : "Choose account";
		paintBankRow();
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

			// A bill that was split stays split when it is reopened, or the counter
			// would silently re-tender the whole amount in one form. A bill held
			// from the counter brings back its whole payment panel.
			if (bill.tender) {
				restoreTender(bill.tender);
			} else if (bill.is_split && (bill.payments || []).length > 1) {
				state.splits = bill.payments.map((p) => ({
					mode: p.mode_of_payment, amount: p.amount,
				}));
				setSplit(true);
			} else {
				state.splits = [];
				setSplit(false);
			}

			$("customer-name").value = bill.customer_name || "";
			if (bill.mobile_no) $("mobile").value = bill.mobile_no;
			$("notes").value = bill.notes || "";
			if (bill.discount_percent) {
				state.discountBy = "pct";
				$("discount-pct").value = bill.discount_percent;
			} else if (bill.discount_amount) {
				state.discountBy = "amt";
				$("discount-amt").value = bill.discount_amount;
			}
			if (bill.discount_on) {
				$("discount-on").value = bill.discount_on;
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
	 * Which bank approved this purchase.
	 *
	 * The counter's part in an EMI sale is one answer: which financier. Tenure,
	 * interest and the instalment are decided on the bank's own machine before
	 * the customer reaches the till, so asking for them here would only be asking
	 * the cashier to copy numbers across.
	 */
	async function emiPartners() {
		if (!state.cart.length) {
			return say("Put the products in the basket first.", "error");
		}
		const sums = totals();
		showList("Loading the banks…", money(sums.grand), []);

		try {
			const partners = await A3.call("a3_retail.api.pos.finance_partners");
			if (!partners.length) {
				return showList("No bank set up", money(sums.grand), [{
					title: "No finance partner is configured",
					meta: "Ask head office to add the banks this shop sells through.",
				}]);
			}
			showList(
				"Which bank approved it?",
				money(sums.grand),
				partners.map((p) => ({ title: p.label, meta: p.mode_of_payment || "", action: "Select" })),
				(index) => {
					$("list-modal").hidden = true;
					pickFinancier(partners[index]);
				});
		} catch (error) {
			showList("Could not read the banks", "", [{ title: error.message, meta: "" }]);
		}
	}

	/**
	 * A financed sale is nearly always part paid, so picking the bank opens the
	 * split straight away with the bank's line already on it. The customer's own
	 * money then goes on a second line, and the financed line shrinks by it.
	 */
	function pickFinancier(partner) {
		state.financier = partner.partner;
		if (partner.mode_of_payment) state.mode = partner.mode_of_payment;

		const payable = totals().grand;
		const emi = state.splits.findIndex((l) => l.kind === "emi");
		if (emi >= 0) {
			applyFinancier(emi, partner);
		} else {
			const others = state.splits.reduce((sum, l) => sum + (Number(l.amount) || 0), 0);
			state.splits.unshift({
				kind: "emi",
				mode: partner.mode_of_payment || "Other",
				account: partner.bank_account || "",
				financier: partner.partner,
				amount: Math.max(payable - others, 0),
			});
		}
		setSplit(true);
		say("Financed by " + partner.label
			+ (partner.bank_label ? " — credited into " + partner.bank_label : "")
			+ ". Add what the customer is paying.", "ok");
	}

	// --------------------------------------------------------------- start
	/**
	 * Who is serving this customer.
	 *
	 * The till is shared, so the bill has to record the person, not the login.
	 * The choice sticks for the session because one assistant usually works a
	 * run of sales — re-picking on every bill would be a keystroke nobody makes.
	 */
	const SELLER_KEY = "a3_pos_sold_by";

	async function loadSellers() {
		let staff = [];
		try {
			staff = await A3.call("a3_retail.api.pos.branch_staff");
		} catch (error) {
			return;   // not permitted to list staff: leave the field hidden
		}
		if (!staff.length) return;

		let remembered = "";
		try {
			remembered = localStorage.getItem(SELLER_KEY) || "";
		} catch (error) {
			remembered = "";
		}
		if (!staff.some((row) => row.employee === remembered)) remembered = "";

		const select = $("sold-by");
		select.innerHTML = `<option value="">${staff.length > 1 ? "Who is serving?" : ""}</option>`
			+ staff.map((row) => `<option value="${esc(row.employee)}"${
				row.employee === remembered ? " selected" : ""}>${esc(row.employee_name)}${
				row.designation ? " · " + esc(row.designation) : ""}</option>`).join("");

		state.soldBy = remembered;
		select.addEventListener("change", () => {
			state.soldBy = select.value;
			try {
				localStorage.setItem(SELLER_KEY, select.value);
			} catch (error) { /* a private window is not a reason to block a sale */ }
			paintTotals();
		});
		$("seller-row").hidden = false;
		paintTotals();
	}

	function start(options) {
		state.branch = options.branch;
		state.groups = options.groups || [];
		state.pricesIncludeTax = Boolean(options.pricesIncludeTax);
		loadSellers();

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
		// Leaving the GSTIN box is the moment to check it, so a typo is caught
		// before the bill rather than at the portal; Fetch does the same on demand.
		const posGstin = () => gstinInto("customer-gstin", POS_GSTIN_FIELDS, "customer-note");
		$("customer-gstin").addEventListener("change", posGstin);
		$("customer-gstin-fetch").addEventListener("click", posGstin);
		$("cust-edit").addEventListener("click", () => {
			window.open("/retail/customers?customer=" + encodeURIComponent(state.customer), "_blank");
		});
		$("nc-save").addEventListener("click", saveNewCustomer);
		$("nc-fetch").addEventListener("click", () => gstinInto("nc-gstin", {
			name: "nc-name", address: "nc-address", city: "nc-city",
			state: "nc-state", pin: "nc-pin" }, "nc-note"));
		$("nc-gstin").addEventListener("change", () => gstinInto("nc-gstin", {
			name: "nc-name", address: "nc-address", city: "nc-city",
			state: "nc-state", pin: "nc-pin" }, "nc-note"));
		$("new-customer").addEventListener("click", newCustomer);
		$("cust-q").addEventListener("input", () => {
			clearTimeout(custTimer);
			custTimer = setTimeout(searchCustomers, 250);
		});

		$("clear-cart").addEventListener("click", () => { state.cart = []; paintCart(); });
		$("discount-pct").addEventListener("input", () => {
			state.discountBy = "pct"; paintTotals();
		});
		$("discount-amt").addEventListener("input", () => {
			state.discountBy = "amt"; paintTotals();
		});
		$("discount-on").addEventListener("change", paintTotals);
		$("received").addEventListener("input", () => {
			state.receivedTyped = true;
			paintTotals();
		});
		// A held bill opened straight from Bills can arrive before these lists;
		// repainting names its accounts and financier once they are known.
		const repaintSplit = () => {
			if (!state.split) return;
			$("split-lines").textContent = "";
			paintTotals();
		};
		A3.call("a3_retail.api.pos.bank_accounts").then((rows) => {
			state.bankAccounts = rows || [];
			paintBankLabel();
			repaintSplit();
		}).catch(() => { /* the tiles still work without it */ });

		A3.call("a3_retail.api.pos.finance_partners").then((rows) => {
			state.financiers = rows || [];
			repaintSplit();
		}).catch(() => { /* EMI simply will not be offered */ });

		$("bank-pick").addEventListener("click", askBankAccount);

		$("checkout").addEventListener("click", () => checkout(false));
		$("hold").addEventListener("click", () => checkout(true));

		$("split-toggle").addEventListener("click", () => setSplit(!state.split));
		$("split-add").addEventListener("click", addSplitLine);

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
			if (state.mode === "EMI") emiPartners();
			else if (!$("bank-row").hidden && !state.bankAccount) askBankAccount();
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
