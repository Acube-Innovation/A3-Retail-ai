// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Stock Availability Explorer (scope 6.1).
 *
 * Answers the counter's question — "do we have it, and if not, who does?" —
 * without leaving the page, and turns the answer into a transfer request.
 */

frappe.pages["a3-stock-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Stock Explorer"),
		single_column: true,
	});
	new a3_retail.StockExplorer(page);
};

a3_retail.StockExplorer = class StockExplorer {
	constructor(page) {
		this.page = page;
		this.filters = { only_in_stock: 0 };
		this.branch = frappe.defaults.get_user_default("branch");
		this.render();
		this.search("");
	}

	render() {
		this.page.main.html(`
			<div class="a3-explorer">
				<div class="a3-explorer-bar">
					<input type="search" id="a3-ex-search" class="form-control"
						placeholder="${__("Item code, name, barcode, IMEI or model")}">
					<label class="a3-check">
						<input type="checkbox" id="a3-ex-instock"> ${__("Only in stock")}
					</label>
				</div>
				<div class="a3-explorer-body">
					<div class="a3-explorer-left">
						<h4>${__("My branch")}</h4>
						<div id="a3-ex-items" class="a3-item-grid"></div>
					</div>
					<div class="a3-explorer-right">
						<h4>${__("Other branches")}</h4>
						<div id="a3-ex-matrix" class="a3-card">
							<div class="a3-muted">${__("Pick an item on the left.")}</div>
						</div>
						<div id="a3-ex-serials"></div>
					</div>
				</div>
			</div>
		`);

		const search = document.getElementById("a3-ex-search");
		// 300 ms debounce so a scanner burst is one query, not fifteen.
		search.addEventListener("input", frappe.utils.debounce((e) => this.search(e.target.value), 300));
		document.getElementById("a3-ex-instock").addEventListener("change", (e) => {
			this.filters.only_in_stock = e.target.checked ? 1 : 0;
			this.search(search.value);
		});
	}

	async search(query) {
		const { message: rows } = await frappe.call({
			method: "a3_retail.api.stock.search_items",
			args: { query, filters: this.filters, branch: this.branch },
		});

		document.getElementById("a3-ex-items").innerHTML = (rows || [])
			.map((r) => this.item_card(r))
			.join("") || `<div class="a3-muted">${__("Nothing matched.")}</div>`;

		document.querySelectorAll(".a3-item-card").forEach((card) =>
			card.addEventListener("click", () => this.show_matrix(card.dataset.item))
		);
	}

	item_card(row) {
		const qty = flt(row.branch_qty);
		const tone = qty > 5 ? "green" : qty > 0 ? "amber" : "red";
		return `
		<div class="a3-item-card" data-item="${frappe.utils.escape_html(row.item_code)}">
			<div class="a3-item-name">${frappe.utils.escape_html(row.item_name)}</div>
			<div class="a3-muted">${row.item_code}${row.brand ? " · " + row.brand : ""}</div>
			<span class="a3-pill ${tone}">${__("Qty")}: ${qty}</span>
		</div>`;
	}

	async show_matrix(item_code) {
		this.selected = item_code;
		const { message: rows } = await frappe.call({
			method: "a3_retail.api.stock.availability_matrix",
			args: { item_code },
		});

		const body = (rows || [])
			.map(
				(r) => `<tr>
					<td>${r.branch || "—"}</td>
					<td>${r.warehouse}</td>
					<td class="num">${flt(r.actual_qty)}</td>
					<td class="num">${flt(r.reserved_qty)}</td>
					<td class="num"><b>${flt(r.available)}</b></td>
					<td>${
						r.branch && r.branch !== this.branch && flt(r.available) > 0
							? `<button class="btn btn-xs btn-default" data-src="${r.branch}">${__("Request")}</button>`
							: ""
					}</td>
				</tr>`
			)
			.join("");

		document.getElementById("a3-ex-matrix").innerHTML = `
			<div class="a3-muted">${item_code}</div>
			<table class="a3-table">
				<thead><tr>
					<th>${__("Branch")}</th><th>${__("Warehouse")}</th>
					<th class="num">${__("Qty")}</th><th class="num">${__("Reserved")}</th>
					<th class="num">${__("Available")}</th><th></th>
				</tr></thead>
				<tbody>${body || `<tr><td colspan="6">${__("No stock anywhere.")}</td></tr>`}</tbody>
			</table>`;

		document.querySelectorAll("#a3-ex-matrix button[data-src]").forEach((btn) =>
			btn.addEventListener("click", () => this.request_transfer(item_code, btn.dataset.src))
		);

		this.show_serials(item_code);
	}

	async show_serials(item_code) {
		const { message: serials } = await frappe.call({
			method: "a3_retail.api.stock.serial_list",
			args: { item_code, limit: 20 },
		});
		if (!serials || !serials.length) {
			document.getElementById("a3-ex-serials").innerHTML = "";
			return;
		}

		document.getElementById("a3-ex-serials").innerHTML = `
			<div class="a3-card">
				<h4>${__("Serial numbers")}</h4>
				<table class="a3-table">
					<thead><tr>
						<th>${__("IMEI")}</th><th>${__("Warehouse")}</th>
						<th class="num">${__("Age (days)")}</th><th>${__("State")}</th>
					</tr></thead>
					<tbody>${serials
						.map(
							(s) => `<tr><td>${s.a3_imei_1 || s.name}</td><td>${s.warehouse || "—"}</td>
								<td class="num">${s.age_days}</td><td>${s.a3_warranty_state || ""}</td></tr>`
						)
						.join("")}</tbody>
				</table>
			</div>`;
	}

	request_transfer(item_code, source_branch) {
		frappe.prompt(
			[
				{ fieldname: "qty", fieldtype: "Float", label: __("Quantity"), default: 1, reqd: 1 },
				{
					fieldname: "purpose",
					fieldtype: "Select",
					label: __("Purpose"),
					options: ["Customer Sale", "Service Job Card", "Stock Balancing", "Display Unit"],
					default: "Customer Sale",
				},
			],
			({ qty, purpose }) =>
				frappe
					.call({
						method: "a3_retail.a3_retail_sales.doctype.stock_request.stock_request.create_from_explorer",
						args: { item_code, qty, source_branch, purpose },
					})
					.then(({ message }) => {
						frappe.show_alert({ message: __("Raised {0}", [message]), indicator: "green" });
						frappe.set_route("Form", "Stock Request", message);
					}),
			__("Request from {0}", [source_branch]),
			__("Raise Request")
		);
	}
};
