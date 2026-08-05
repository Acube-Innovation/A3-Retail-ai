// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * Reception Desk (scope 3.9).
 *
 * Design goal: a walk-in becomes a submitted job card in under 60 seconds, on a
 * touch screen, with one API round trip at the end. Vue 3 via frappe.ui.Page,
 * no build step — the app ships Vue with the desk bundle.
 */

frappe.pages["a3-reception-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Reception Desk"),
		single_column: true,
	});

	new a3_retail.ReceptionDesk(page);
};

a3_retail.ReceptionDesk = class ReceptionDesk {
	constructor(page) {
		this.page = page;
		this.state = this.blank_state();
		this.render();
		this.bind_realtime();
		this.refresh_counters();
		this.refresh_today();
	}

	blank_state() {
		return {
			branch: frappe.defaults.get_user_default("branch") || null,
			customer: null,
			customer_name: "",
			mobile_no: "",
			marketing_optin: 1,
			device_type: "Mobile",
			brand: null,
			device_model: null,
			imei_1: "",
			imei_2: "",
			serial_info: null,
			issues: [],
			complaint: "",
			repair_category: null,
			priority: "Normal",
			accessories: [],
			physical_condition: "",
			photos: [],
			device_password: "",
			data_backup_required: 0,
			data_loss_consent: 0,
			signature: null,
			advance_amount: 0,
			advance_mode: "Cash",
			delivery_mode: "Counter Pickup",
		};
	}

	// ------------------------------------------------------------------ render
	render() {
		this.page.main.html(`
			<div class="a3-reception">
				<div class="a3-counter-strip" id="a3-counters"></div>

				<div class="a3-reception-body">
					<div class="a3-steps">
						${this.step_customer()}
						${this.step_device()}
						${this.step_complaint()}
						${this.step_condition()}
						${this.step_consent()}
						${this.step_advance()}
						<div class="a3-actionbar">
							<button class="btn btn-primary btn-lg" id="a3-create-print">
								${__("Create & Print")}
							</button>
							<button class="btn btn-default btn-lg" id="a3-create-whatsapp">
								${__("Create & WhatsApp")}
							</button>
							<button class="btn btn-default" id="a3-reset">${__("Clear")}</button>
						</div>
					</div>

					<div class="a3-rail">
						<div class="a3-card">
							<h4>${__("Today at this branch")}</h4>
							<input type="search" class="form-control input-sm" id="a3-rail-search"
								placeholder="${__("Filter by name, IMEI or JC no")}">
							<div id="a3-today-list" class="a3-today-list"></div>
						</div>
					</div>
				</div>
			</div>
		`);

		this.bind_events();
		this.load_issue_chips();
		this.load_accessories();
		this.mount_signature_pad();
	}

	step_customer() {
		return `
		<section class="a3-card a3-step" data-step="1">
			<h4>${__("1 · Customer")}</h4>
			<div class="a3-row">
				<input type="tel" id="a3-mobile" class="a3-bigin" maxlength="10" inputmode="numeric"
					placeholder="${__("Mobile number")}" autocomplete="off">
				<span id="a3-customer-badge" class="a3-pill grey">${__("Enter 10 digits")}</span>
			</div>
			<div id="a3-customer-new" style="display:none">
				<input type="text" id="a3-customer-name" class="form-control"
					placeholder="${__("Customer name")}">
				<label class="a3-check">
					<input type="checkbox" id="a3-optin" checked> ${__("Marketing opt-in")}
				</label>
			</div>
			<div id="a3-customer-context" class="a3-context"></div>
		</section>`;
	}

	step_device() {
		return `
		<section class="a3-card a3-step" data-step="2">
			<h4>${__("2 · Device")}</h4>
			<div id="a3-brand-tiles" class="a3-tiles"></div>
			<div class="a3-row">
				<input type="text" id="a3-model" class="form-control" placeholder="${__("Model")}">
				<select id="a3-device-type" class="form-control a3-narrow">
					<option>Mobile</option><option>Tablet</option>
					<option>Smartwatch</option><option>Earbuds</option><option>Other</option>
				</select>
			</div>
			<div class="a3-row">
				<input type="tel" id="a3-imei" class="a3-bigin" maxlength="15" inputmode="numeric"
					placeholder="${__("IMEI 1 — dial *#06# on the device")}">
				<button class="btn btn-default" id="a3-scan-imei" title="${__("Scan barcode")}">⛶</button>
			</div>
			<div id="a3-imei-badge"></div>
		</section>`;
	}

	step_complaint() {
		return `
		<section class="a3-card a3-step" data-step="3">
			<h4>${__("3 · Complaint")}</h4>
			<div id="a3-issue-chips" class="a3-chips"></div>
			<textarea id="a3-complaint" class="form-control" rows="2"
				placeholder="${__("What is the customer reporting?")}"></textarea>
			<div class="a3-row">
				<select id="a3-priority" class="form-control a3-narrow">
					<option>Low</option><option selected>Normal</option>
					<option>High</option><option>Urgent (Same Day)</option>
				</select>
				<select id="a3-delivery-mode" class="form-control a3-narrow">
					<option>Counter Pickup</option><option>Home Delivery</option><option>Courier</option>
				</select>
			</div>
		</section>`;
	}

	step_condition() {
		return `
		<section class="a3-card a3-step" data-step="4">
			<h4>${__("4 · Condition")}</h4>
			<div id="a3-accessories" class="a3-accessories"></div>
			<textarea id="a3-condition" class="form-control" rows="2"
				placeholder="${__("Scratches, dents, cracked back…")}"></textarea>
			<div class="a3-photos">
				<input type="file" accept="image/*" capture="environment" id="a3-photo-input" hidden multiple>
				<button class="btn btn-default" id="a3-add-photo">📷 ${__("Add photo")}</button>
				<div id="a3-photo-strip" class="a3-photo-strip"></div>
			</div>
		</section>`;
	}

	step_consent() {
		return `
		<section class="a3-card a3-step" data-step="5">
			<h4>${__("5 · Consent")}</h4>
			<div class="a3-row">
				<input type="text" id="a3-lock" class="form-control"
					placeholder="${__("Lock code / pattern")}">
			</div>
			<label class="a3-check"><input type="checkbox" id="a3-backup">
				${__("Data backup required")}</label>
			<label class="a3-check"><input type="checkbox" id="a3-consent">
				${__("Customer consents to possible data loss")}</label>
			<div class="a3-signature-wrap">
				<canvas id="a3-signature" class="a3-signature-pad"></canvas>
				<button class="btn btn-xs btn-default" id="a3-clear-sign">${__("Clear signature")}</button>
			</div>
		</section>`;
	}

	step_advance() {
		return `
		<section class="a3-card a3-step" data-step="6">
			<h4>${__("6 · Advance (optional)")}</h4>
			<div class="a3-row">
				<input type="number" id="a3-advance" class="form-control a3-narrow" min="0" placeholder="0">
				<select id="a3-advance-mode" class="form-control a3-narrow">
					<option>Cash</option><option>UPI</option>
					<option>Credit Card</option><option>Debit Card</option>
				</select>
			</div>
		</section>`;
	}

	// ------------------------------------------------------------------ events
	bind_events() {
		const $ = (id) => document.getElementById(id);

		// Mobile lookup fires as soon as 10 digits are in.
		$("a3-mobile").addEventListener("input", (e) => {
			const value = e.target.value.replace(/\D/g, "").slice(-10);
			e.target.value = value;
			this.state.mobile_no = value;
			if (value.length === 10) this.lookup_customer(value);
		});

		$("a3-customer-name").addEventListener("input", (e) => {
			this.state.customer_name = e.target.value;
		});
		$("a3-optin").addEventListener("change", (e) => {
			this.state.marketing_optin = e.target.checked ? 1 : 0;
		});

		// Keyboard-wedge scanners type fast and end with Enter.
		a3_retail.bind_scanner($("a3-imei"), (value) => this.on_imei(value));
		$("a3-imei").addEventListener("change", (e) => this.on_imei(e.target.value));
		$("a3-scan-imei").addEventListener("click", () => this.scan_with_camera());

		$("a3-model").addEventListener("change", (e) => (this.state.device_model = e.target.value));
		$("a3-device-type").addEventListener("change", (e) => (this.state.device_type = e.target.value));
		$("a3-complaint").addEventListener("input", (e) => (this.state.complaint = e.target.value));
		$("a3-priority").addEventListener("change", (e) => (this.state.priority = e.target.value));
		$("a3-delivery-mode").addEventListener("change", (e) => (this.state.delivery_mode = e.target.value));
		$("a3-condition").addEventListener("input", (e) => (this.state.physical_condition = e.target.value));
		$("a3-lock").addEventListener("input", (e) => (this.state.device_password = e.target.value));
		$("a3-backup").addEventListener("change", (e) => {
			this.state.data_backup_required = e.target.checked ? 1 : 0;
		});
		$("a3-consent").addEventListener("change", (e) => {
			this.state.data_loss_consent = e.target.checked ? 1 : 0;
		});
		$("a3-advance").addEventListener("input", (e) => (this.state.advance_amount = e.target.value));
		$("a3-advance-mode").addEventListener("change", (e) => (this.state.advance_mode = e.target.value));

		$("a3-add-photo").addEventListener("click", () => $("a3-photo-input").click());
		$("a3-photo-input").addEventListener("change", (e) => this.add_photos(e.target.files));

		$("a3-create-print").addEventListener("click", () => this.submit({ print: true }));
		$("a3-create-whatsapp").addEventListener("click", () => this.submit({ whatsapp: true }));
		$("a3-reset").addEventListener("click", () => this.reset());
		$("a3-rail-search").addEventListener("input", (e) => this.filter_today(e.target.value));

		this.load_brands();
	}

	async lookup_customer(mobile) {
		const badge = document.getElementById("a3-customer-badge");
		const { message } = await frappe.call({
			method: "a3_retail.api.service.lookup_customer",
			args: { mobile_no: mobile },
		});

		if (message && message.name) {
			this.state.customer = message.name;
			this.state.customer_name = message.customer_name;
			badge.className = "a3-pill green";
			badge.textContent = message.customer_name;
			document.getElementById("a3-customer-new").style.display = "none";
			this.render_customer_context(message);
		} else {
			this.state.customer = null;
			badge.className = "a3-pill amber";
			badge.textContent = __("New customer");
			document.getElementById("a3-customer-new").style.display = "block";
			document.getElementById("a3-customer-context").innerHTML = "";
		}
	}

	render_customer_context(profile) {
		const jobs = (profile.past_jobs || [])
			.slice(0, 3)
			.map((j) => `<div>${j.name} · ${j.status}</div>`)
			.join("");
		document.getElementById("a3-customer-context").innerHTML = `
			<div class="a3-muted">
				${__("Devices")}: ${profile.device_count || 0} ·
				${__("LTV")}: ${a3_retail.money(profile.lifetime_value)} ·
				${__("Outstanding")}: ${a3_retail.money(profile.outstanding)}
			</div>
			${jobs ? `<div class="a3-past">${jobs}</div>` : ""}`;
	}

	async on_imei(value) {
		const imei = String(value || "").replace(/\D/g, "");
		this.state.imei_1 = imei;
		document.getElementById("a3-imei").value = imei;

		const badge = document.getElementById("a3-imei-badge");
		if (imei.length !== 15) {
			badge.innerHTML = "";
			return;
		}

		const { message } = await frappe.call({
			method: "a3_retail.api.service.lookup_imei",
			args: { imei },
		});

		if (message && message.found) {
			this.state.serial_info = message;
			const covered = (message.warranty_state || "").includes("Warranty");
			badge.innerHTML = `<span class="a3-pill ${covered ? "green" : "amber"}">
				${message.item_name} — ${message.warranty_state}
				${message.brand_warranty_expiry ? "· till " + message.brand_warranty_expiry : ""}
			</span>`;
			if (message.brand) this.select_brand(message.brand);
			if (message.device_model) {
				this.state.device_model = message.device_model;
				document.getElementById("a3-model").value = message.device_model;
			}
		} else {
			this.state.serial_info = null;
			badge.innerHTML = `<span class="a3-pill grey">${__("Not sold by us")}</span>`;
		}
	}

	async scan_with_camera() {
		// Frappe ships a scanner dialog; fall back to manual entry when absent.
		if (frappe.ui.Scanner) {
			new frappe.ui.Scanner({
				dialog: true,
				multiple: false,
				on_scan: (data) => this.on_imei(data.decodedText || data.result?.text),
			});
		} else {
			frappe.prompt(
				{ fieldname: "imei", label: __("IMEI"), fieldtype: "Data", reqd: 1 },
				(v) => this.on_imei(v.imei)
			);
		}
	}

	async load_brands() {
		const brands = await frappe.db.get_list("Brand", { limit: 12, pluck: "name" });
		const html = brands
			.map((b) => `<button class="a3-tile" data-brand="${frappe.utils.escape_html(b)}">${b}</button>`)
			.join("");
		const holder = document.getElementById("a3-brand-tiles");
		holder.innerHTML = html;
		holder.querySelectorAll(".a3-tile").forEach((tile) =>
			tile.addEventListener("click", () => this.select_brand(tile.dataset.brand))
		);
	}

	select_brand(brand) {
		this.state.brand = brand;
		document.querySelectorAll("#a3-brand-tiles .a3-tile").forEach((t) =>
			t.classList.toggle("selected", t.dataset.brand === brand)
		);
	}

	async load_issue_chips() {
		const issues = await frappe.db.get_list("Service Issue Type", {
			filters: { is_active: 1 },
			fields: ["name", "category"],
			limit: 30,
		});
		const holder = document.getElementById("a3-issue-chips");
		holder.innerHTML = issues
			.map(
				(i) =>
					`<button class="a3-chip" data-issue="${frappe.utils.escape_html(i.name)}"
						data-category="${frappe.utils.escape_html(i.category || "")}">${i.name}</button>`
			)
			.join("");

		holder.querySelectorAll(".a3-chip").forEach((chip) =>
			chip.addEventListener("click", () => {
				chip.classList.toggle("selected");
				this.state.issues = Array.from(holder.querySelectorAll(".a3-chip.selected")).map(
					(c) => c.dataset.issue
				);
				const first = holder.querySelector(".a3-chip.selected");
				this.state.repair_category = first ? this.map_category(first.dataset.category) : null;
			})
		);
	}

	map_category(category) {
		const map = {
			Display: "Display",
			Battery: "Battery",
			Software: "Software",
			"Board Level": "Hardware - Board Level",
			"Liquid Damage": "Liquid Damage",
			"Physical Damage": "Physical Damage",
		};
		return map[category] || "Hardware - Component";
	}

	load_accessories() {
		const items = ["Charger", "Cable", "Earphone", "Box", "SIM Card", "SIM Tray",
			"Memory Card", "Back Cover", "Screen Guard", "Bill Copy"];
		const holder = document.getElementById("a3-accessories");
		holder.innerHTML = items
			.map(
				(a) => `<label class="a3-acc">
					<input type="checkbox" data-accessory="${a}"> ${a}
					<select data-condition="${a}" class="a3-acc-cond">
						<option>Good</option><option>Damaged</option><option>Missing</option>
					</select>
				</label>`
			)
			.join("");

		holder.addEventListener("change", () => {
			this.state.accessories = Array.from(holder.querySelectorAll("input:checked")).map((cb) => ({
				accessory: cb.dataset.accessory,
				received: 1,
				condition: holder.querySelector(`[data-condition="${cb.dataset.accessory}"]`).value,
			}));
		});
	}

	async add_photos(files) {
		for (const file of Array.from(files).slice(0, 4 - this.state.photos.length)) {
			// Compressed client-side to <=300 KB before it ever hits the network.
			const data = await a3_retail.compress_image(file, 300);
			this.state.photos.push(data);
		}
		document.getElementById("a3-photo-strip").innerHTML = this.state.photos
			.map((p) => `<img src="${p}" class="a3-thumb">`)
			.join("");
	}

	mount_signature_pad() {
		const canvas = document.getElementById("a3-signature");
		if (!canvas) return;

		const ctx = canvas.getContext("2d");
		const resize = () => {
			canvas.width = canvas.offsetWidth;
			canvas.height = canvas.offsetHeight;
			ctx.lineWidth = 2;
			ctx.lineCap = "round";
			ctx.strokeStyle = "#111827";
		};
		resize();
		window.addEventListener("resize", resize);

		let drawing = false;
		const pos = (e) => {
			const rect = canvas.getBoundingClientRect();
			const point = e.touches ? e.touches[0] : e;
			return { x: point.clientX - rect.left, y: point.clientY - rect.top };
		};
		const start = (e) => {
			drawing = true;
			const p = pos(e);
			ctx.beginPath();
			ctx.moveTo(p.x, p.y);
			e.preventDefault();
		};
		const move = (e) => {
			if (!drawing) return;
			const p = pos(e);
			ctx.lineTo(p.x, p.y);
			ctx.stroke();
			e.preventDefault();
		};
		const end = () => {
			if (!drawing) return;
			drawing = false;
			this.state.signature = canvas.toDataURL("image/png");
		};

		["mousedown", "touchstart"].forEach((ev) => canvas.addEventListener(ev, start));
		["mousemove", "touchmove"].forEach((ev) => canvas.addEventListener(ev, move));
		["mouseup", "mouseleave", "touchend"].forEach((ev) => canvas.addEventListener(ev, end));

		document.getElementById("a3-clear-sign").addEventListener("click", () => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			this.state.signature = null;
		});
	}

	// ------------------------------------------------------------------ submit
	validate() {
		const s = this.state;
		if (!s.customer && (!s.mobile_no || !s.customer_name)) {
			return __("Enter the customer's mobile number and name.");
		}
		if (!s.brand || !s.device_model) return __("Pick the brand and model.");
		if (["Mobile", "Tablet"].includes(s.device_type) && s.imei_1.length !== 15) {
			return __("A 15-digit IMEI is required for a phone or tablet.");
		}
		if (!s.complaint) return __("Record the customer's complaint.");
		if (!s.data_backup_required && !s.data_loss_consent) {
			return __("Tick data backup required, or capture the data-loss consent.");
		}
		if (!s.signature) return __("Capture the customer's signature.");
		if (!s.photos.length) return __("Capture at least one device photo.");
		return null;
	}

	async submit({ print = false, whatsapp = false } = {}) {
		const error = this.validate();
		if (error) {
			frappe.show_alert({ message: error, indicator: "orange" });
			return;
		}

		const s = this.state;
		const payload = {
			branch: s.branch,
			customer: s.customer,
			mobile_no: s.mobile_no,
			customer_name: s.customer_name,
			marketing_optin: s.marketing_optin,
			device_type: s.device_type,
			brand: s.brand,
			device_model: s.device_model,
			imei_1: s.imei_1,
			imei_2: s.imei_2,
			complaint_description: s.complaint,
			repair_category: s.repair_category,
			priority: s.priority,
			delivery_mode: s.delivery_mode,
			physical_condition: s.physical_condition,
			device_password: s.device_password,
			data_backup_required: s.data_backup_required,
			data_loss_consent: s.data_loss_consent,
			customer_signature: s.signature,
			reported_issues: s.issues,
			accessories: s.accessories,
			advance_amount: s.advance_amount,
			advance_mode: s.advance_mode,
		};
		s.photos.forEach((photo, index) => (payload[`device_photo_${index + 1}`] = photo));

		const { message } = await frappe.call({
			method: "a3_retail.api.service.create_job_card",
			args: { payload },
			freeze: true,
			freeze_message: __("Creating job card…"),
		});

		frappe.show_alert({
			message: __("{0} created", [message.job_card]),
			indicator: "green",
		});

		if (print) {
			frappe.utils.print(
				"Service Job Card",
				message.job_card,
				"A3 Job Card Receipt (Thermal)",
				frappe.boot.lang
			);
		}
		if (whatsapp) {
			frappe.call({
				method: "a3_retail.api.service.resend_delivery_otp",
				args: { job_card: message.job_card },
			});
		}

		this.reset();
		this.refresh_counters();
		this.refresh_today();
	}

	reset() {
		this.state = this.blank_state();
		this.render();
	}

	// ------------------------------------------------------------------- rail
	async refresh_counters() {
		const { message } = await frappe.call({
			method: "a3_retail.api.service.dashboard_counters",
			args: { branch: this.state.branch },
		});
		const cards = [
			[__("Today In"), message.today_in, false],
			[__("Delivered"), message.delivered_today, false],
			[__("Pending"), message.pending, false],
			[__("Ready"), message.ready, false],
			[__("Delayed"), message.delayed, message.delayed > 0],
		];
		document.getElementById("a3-counters").innerHTML = cards
			.map(
				([label, value, alert]) => `
				<div class="a3-counter ${alert ? "is-alert" : ""}">
					<div class="a3-counter-label">${label}</div>
					<div class="a3-counter-value">${value}</div>
				</div>`
			)
			.join("");
	}

	async refresh_today() {
		const rows = await frappe.db.get_list("Service Job Card", {
			filters: { docstatus: 1 },
			fields: ["name", "customer_name", "device_model", "imei_1", "status", "is_delayed"],
			order_by: "received_on desc",
			limit: 25,
		});
		this._today = rows;
		this.paint_today(rows);
	}

	paint_today(rows) {
		document.getElementById("a3-today-list").innerHTML = rows
			.map(
				(r) => `
			<div class="a3-today-row" data-jc="${r.name}">
				<div>
					<b>${r.name}</b>
					<div class="a3-muted">${r.customer_name || ""} · ${r.device_model || ""}</div>
				</div>
				<span class="a3-pill ${r.is_delayed ? "red" : "grey"}">${r.status}</span>
			</div>`
			)
			.join("");

		document.querySelectorAll(".a3-today-row").forEach((row) =>
			row.addEventListener("click", () =>
				frappe.set_route("Form", "Service Job Card", row.dataset.jc)
			)
		);
	}

	filter_today(query) {
		const q = (query || "").toLowerCase();
		this.paint_today(
			(this._today || []).filter((r) =>
				[r.name, r.customer_name, r.imei_1].join(" ").toLowerCase().includes(q)
			)
		);
	}

	bind_realtime() {
		frappe.realtime.on("a3_retail_dashboard_update", () => {
			frappe.utils.debounce(() => {
				this.refresh_counters();
				this.refresh_today();
			}, 2000)();
		});
	}
};
