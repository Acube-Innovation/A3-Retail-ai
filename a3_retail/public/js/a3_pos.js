// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Counter billing for the branch app.
 *
 * The rules the screen enforces are the shop's, not the browser's: a device
 * cannot go on the bill without its IMEI, an item with no stock here shows where
 * it *is* instead of failing, and the totals shown are provisional until the
 * server prices the invoice. The server re-checks all of it.
 */

window.POS = (function () {
	const state = { branch: "", group: "", cart: [], customer: null, items: [] };
	const $ = (id) => document.getElementById(id);

	function money(value) {
		return "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 })
			.format(Math.round(value || 0));
	}

	function escapeHtml(value) {
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
		$("grid").innerHTML = '<div class="pos-loading">Loading…</div>';
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

	function paintCatalogue() {
		if (!state.items.length) {
			$("grid").innerHTML = '<div class="pos-loading">Nothing matches that search.</div>';
			return;
		}
		$("grid").innerHTML = state.items.map((item) => `
			<button class="pos-item ${item.sellable ? "" : "is-out"}" data-code="${escapeHtml(item.item_code)}">
				<div class="pos-item-top">
					<span class="pos-item-name">${escapeHtml(item.item_name)}</span>
					${item.is_device ? '<span class="tag">IMEI</span>' : ""}
					${item.is_plan ? '<span class="tag plan">Plan</span>' : ""}
				</div>
				<div class="pos-item-meta">${escapeHtml(item.brand || item.item_group || "")}</div>
				<div class="pos-item-foot">
					<span class="pos-item-rate">${money(item.rate)}</span>
					<span class="pos-item-qty ${item.sellable ? "" : "out"}">
						${item.is_stock_item ? (item.branch_qty > 0 ? item.branch_qty + " in stock" : "Not here") : "Service"}
					</span>
				</div>
			</button>`).join("");

		$("grid").querySelectorAll(".pos-item").forEach((node) => {
			node.addEventListener("click", () => pick(node.dataset.code));
		});
	}

	function pick(code) {
		const item = state.items.find((row) => row.item_code === code);
		if (!item) return;
		if (!item.sellable) return showElsewhere(item);
		if (item.has_serial) return askSerial(item);
		addLine(item, null);
	}

	// -------------------------------------------------------------- serials
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
			<li><button data-serial="${escapeHtml(row.serial_no)}">
				<span>${escapeHtml(row.imei || row.serial_no)}</span>
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

	// ------------------------------------------------------- cross-branch
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
				<div><strong>${escapeHtml(row.branch)}</strong><small>${row.available} in stock</small></div>
				<button class="btn btn-quiet" data-branch="${escapeHtml(row.branch)}">Request transfer</button>
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
			existing.serials.push(serial);
			existing.qty = existing.serials.length;
		} else {
			state.cart.push({
				item_code: item.item_code,
				item_name: item.item_name,
				rate: item.rate,
				min_price: item.min_price,
				qty: 1,
				has_serial: item.has_serial,
				is_device: item.is_device,
				serials: serial ? [serial] : [],
			});
		}
		paintCart();
	}

	function paintCart() {
		const lines = $("lines");
		if (!state.cart.length) {
			lines.innerHTML = '<li class="pos-empty">Tap an item to start the bill.</li>';
		} else {
			lines.innerHTML = state.cart.map((line, index) => `
				<li>
					<div class="line-main">
						<div class="line-name">${escapeHtml(line.item_name)}</div>
						${line.serials.length ? `<div class="line-serials">${line.serials.map(escapeHtml).join(", ")}</div>` : ""}
						<div class="line-controls">
							<button data-act="minus" data-i="${index}">−</button>
							<span>${line.qty}</span>
							<button data-act="plus" data-i="${index}">+</button>
							<input class="line-rate" data-i="${index}" type="number" value="${line.rate}"
							       min="0" step="1" aria-label="Rate">
						</div>
					</div>
					<div class="line-side">
						<div class="line-amount">${money(line.rate * line.qty)}</div>
						<button class="line-remove" data-act="remove" data-i="${index}">Remove</button>
					</div>
				</li>`).join("");
		}

		lines.querySelectorAll("[data-act]").forEach((node) => {
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
						return askSerial(item, index);
					}
					line.qty += 1;
				}
				paintCart();
			});
		});

		lines.querySelectorAll(".line-rate").forEach((node) => {
			node.addEventListener("change", () => {
				const line = state.cart[Number(node.dataset.i)];
				const rate = Number(node.value);
				if (line.min_price && rate < line.min_price) {
					say(line.item_name + " cannot go below " + money(line.min_price)
						+ " — a manager has to approve that.", "error");
				}
				line.rate = rate;
				paintCart();
			});
		});

		const count = state.cart.reduce((sum, line) => sum + line.qty, 0);
		const subtotal = state.cart.reduce((sum, line) => sum + line.rate * line.qty, 0);
		$("count").textContent = count;
		$("subtotal").textContent = money(subtotal);
		$("checkout").disabled = !state.cart.length || !state.customer;
	}

	// ------------------------------------------------------------ customer
	async function findCustomer() {
		const mobile = $("mobile").value.trim();
		if (mobile.length !== 10) return say("Enter the ten-digit mobile number.", "error");

		say("Looking…");
		const found = await A3.call("a3_retail.api.pos.find_customer", { mobile_no: mobile });
		$("customer-detail").hidden = false;

		if (found) {
			state.customer = found.name;
			$("customer-name").value = found.customer_name || "";
			$("customer-email").value = found.email_id || "";
			$("customer-address").value = (found.address && found.address.address_line1) || "";
			$("customer-city").value = (found.address && found.address.city) || "";
			if (found.address && found.address.state) $("customer-state").value = found.address.state;
			$("customer-pin").value = (found.address && found.address.pincode) || "";
			$("customer-chip").textContent = "Known customer";
			$("customer-chip").className = "chip good";
			$("customer-history").innerHTML =
				`<span>${found.history.invoices} purchases</span>
				 <span>${found.history.repairs} repairs</span>` +
				(found.history.last_seen ? `<span>last seen ${escapeHtml(found.history.last_seen)}</span>` : "");
			say("");
		} else {
			state.customer = null;
			$("customer-name").value = "";
			$("customer-chip").textContent = "New customer";
			$("customer-chip").className = "chip warn";
			$("customer-history").innerHTML = "";
			say("New number — add the name and save.");
		}
		paintCart();
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
			$("customer-chip").textContent = "Ready to bill";
			$("customer-chip").className = "chip good";
			say("Customer saved.", "ok");
			paintCart();
		} catch (error) {
			say(error.message, "error");
		}
	}

	// ------------------------------------------------------------ checkout
	async function checkout() {
		const missing = state.cart.find(
			(line) => line.has_serial && line.serials.length !== line.qty
		);
		if (missing) return say(missing.item_name + " still needs its IMEI.", "error");

		$("checkout").disabled = true;
		say("Billing…");

		try {
			const result = await A3.call("a3_retail.api.pos.checkout", {
				payload: {
					customer: state.customer,
					mode_of_payment: $("mode").value,
					items: state.cart.map((line) => ({
						item_code: line.item_code, qty: line.qty, rate: line.rate,
						serials: line.serials,
					})),
				},
			});
			done(result);
		} catch (error) {
			say(error.message || "Could not complete the sale.", "error");
			$("checkout").disabled = false;
		}
	}

	function done(result) {
		$("done-note").textContent =
			`${result.invoice} · ${result.customer_name} · ${money(result.grand_total)} paid`;
		$("print-invoice").href = result.print_url;
		$("done-modal").hidden = false;

		state.cart = [];
		state.customer = null;
		$("mobile").value = "";
		$("customer-detail").hidden = true;
		$("customer-history").innerHTML = "";
		$("customer-chip").textContent = "Walk-in";
		$("customer-chip").className = "chip";
		say("");
		paintCart();
		loadRecent();
	}

	async function loadRecent() {
		const rows = await A3.call("a3_retail.api.pos.recent_invoices");
		$("recent").innerHTML = rows.length
			? rows.map((row) => `<li>
				<div><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.customer_name || "")}</small></div>
				<div class="recent-side">${money(row.grand_total)}
					<a href="${row.print_url}" target="_blank" rel="noopener">PDF</a></div>
			</li>`).join("")
			: '<li class="pos-empty">Nothing billed yet.</li>';
	}

	// --------------------------------------------------------------- start
	function start(options) {
		state.branch = options.branch;

		$("q").addEventListener("input", () => {
			clearTimeout(searchTimer);
			searchTimer = setTimeout(loadCatalogue, 220);
		});
		$("in-stock").addEventListener("change", loadCatalogue);

		$("groups").querySelectorAll(".pill").forEach((node) => {
			node.addEventListener("click", () => {
				$("groups").querySelectorAll(".pill").forEach((p) => p.classList.remove("is-active"));
				node.classList.add("is-active");
				state.group = node.dataset.group;
				loadCatalogue();
			});
		});

		$("find-customer").addEventListener("click", findCustomer);
		$("mobile").addEventListener("keydown", (e) => { if (e.key === "Enter") findCustomer(); });
		$("save-customer").addEventListener("click", saveCustomer);
		$("clear-cart").addEventListener("click", () => { state.cart = []; paintCart(); });
		$("checkout").addEventListener("click", checkout);

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => {
				node.closest(".modal").hidden = true;
			});
		});
		document.querySelectorAll(".modal").forEach((modal) => {
			modal.addEventListener("click", (event) => {
				if (event.target === modal) modal.hidden = true;
			});
		});

		loadCatalogue();
		loadRecent();
	}

	return { start };
})();
