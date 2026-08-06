// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * The service counter.
 *
 * Three steps live on one screen — book the device in, bill the repair, hand it
 * back — because that is how a reception counter works: the same customer walks
 * up three times and the person behind the desk should not have to go looking
 * for a different page each time.
 *
 * Every total here is a preview. The Service Job Card prices the repair, decides
 * what warranty covers and owns the status transitions.
 */

window.SVC = (function () {
	const state = {
		branch: "", step: "booking", jobCard: null, status: "Booking",
		customer: null, device: null, serviceType: "general", priority: "Normal",
		leadSource: "Walk-in", lines: [], issues: [], technicians: [], types: [], signed: false, photos: [],
		brands: [], models: [], canAddModel: false,
		requirePhotos: false, minPhotos: 1,
	};
	const $ = (id) => document.getElementById(id);
	const money = (value) =>
		"₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
			.format(value || 0);

	function esc(value) {
		const node = document.createElement("div");
		node.textContent = value == null ? "" : String(value);
		return node.innerHTML;
	}

	function say(text, kind) {
		const box = $("svc-msg");
		box.textContent = text || "";
		box.className = "msg" + (kind ? " " + kind : "");
	}

	// ------------------------------------------------------------- device
	async function lookupDevice(code) {
		if (!code) return;
		try {
			const found = await A3.call("a3_retail.api.service_pos.device", { code });
			if (!found) return say("Nothing found for " + code + ".", "error");
			if (found.job_card) return loadBooking(found);
			state.device = found;
			if (!found.known) state.device.imei_1 = found.imei_1 || code;
			paintDevice();
			say(found.known ? "" : "Not a handset we sold — name the make and model below.");
		} catch (error) {
			say(error.message, "error");
		}
	}

	function paintDevice() {
		const box = $("device-card");
		// The form writes straight into `state.device`, so there has to be one
		// before it is drawn. Handing it a throwaway object meant every make and
		// model the counter picked went nowhere, and saving asked for a model
		// that was already on the screen.
		if (!state.device) {
			state.device = { known: false, device_type: "Mobile", warranty_type: "Out of Warranty" };
		}
		const device = state.device;

		// The device answers the "Service Type" question, not the counter.
		if (device.warranty_type && $("warranty-type")) {
			$("warranty-type").value = device.warranty_type;
			paintTotals();
		}

		if (!device.known) return paintDeviceForm(box, device);
		paintDeviceFacts(box, device);
	}

	/** A handset this shop sold: its own sale answers every question. */
	function paintDeviceFacts(box, device) {
		const out = device.warranty_type === "Out of Warranty";
		const rows = [
			["Device", device.device_name || device.device_model || "—"],
			["IMEI", device.imei_1 || "—"],
			["Model / Variant", device.device_model || "—"],
			["Warranty Status", device.warranty_type || "Out of Warranty"],
			["Purchase Date", device.purchase_date || "—"],
			["Accessories", device.accessories || "—"],
		];

		box.innerHTML = `
			<div class="device-photo">${device.image
				? `<img src="${esc(device.image)}" alt="">`
				: '<span class="thumb-fallback">?</span>'}</div>
			<dl class="device-facts">
				${rows.map(([label, value]) => `
					<dt>${esc(label)}</dt>
					<dd class="${label === "Warranty Status" ? (out ? "warn-red" : "warn-good") : ""}">
						${esc(value)}</dd>`).join("")}
			</dl>
			<div class="device-foot">
				${(device.history || []).length
					? `<button class="linkish" id="history">${device.history.length} earlier repair(s)</button>`
					: '<span class="device-none">No earlier repairs on this device.</span>'}
				<button class="linkish" id="edit-device">Not this device? Enter it by hand</button>
			</div>`;

		const history = $("history");
		if (history) {
			history.addEventListener("click", () => showList(
				"Earlier repairs on this device", "",
				device.history.map((row) => ({
					title: row.name + " · " + row.status,
					sub: row.complaint_description || "",
				}))));
		}
		$("edit-device").addEventListener("click", () => {
			state.device = { known: false, imei_1: device.imei_1, brand: device.brand,
			                 device_model: device.device_model,
			                 device_type: device.device_type || "Mobile",
			                 warranty_type: "Out of Warranty" };
			paintDevice();
		});
	}

	/** Anything else — a handset from another shop, or one bought online. The
	 *  counter types the IMEI and names the make and model itself. */
	function paintDeviceForm(box, device) {
		const brands = state.brands || [];
		box.innerHTML = `
			<div class="device-form">
				<div class="device-form-head">
					<h3>Device</h3>
					<span class="device-hint">Scan the IMEI above to fill this in, or type it here.</span>
				</div>
				<label class="field"><span>IMEI / Serial</span>
					<input id="d-imei" inputmode="numeric" maxlength="15"
					       value="${esc(device.imei_1 || "")}" placeholder="15 digits"
					       ${device.imei_unreadable ? "disabled" : ""}></label>
				<label class="tickbox"><input type="checkbox" id="d-noimei"
					${device.imei_unreadable ? "checked" : ""}>
					<span>The device cannot show its IMEI</span></label>
				<label class="field" id="d-condition-field"
				       ${device.imei_unreadable ? "" : "hidden"}>
					<span>Describe the device</span>
					<input id="d-condition" value="${esc(device.condition || "")}"
					       placeholder="Colour, marks, what came with it"></label>
				<div class="field-grid">
					<label class="field"><span>Make</span>
						<select id="d-brand">
							<option value="">Pick the make…</option>
							${brands.map((brand) => `<option value="${esc(brand)}"${
								brand === device.brand ? " selected" : ""}>${esc(brand)}</option>`).join("")}
						</select></label>
					<label class="field"><span>Model / Variant</span>
						<select id="d-model"><option value="">Pick the model…</option></select></label>
				</div>
				<div class="device-form-foot">
					${state.canAddModel
						? '<button class="linkish" id="new-model">+ The model is not listed</button>'
						: '<span class="device-none">Ask a manager to add a model that is not listed.</span>'}
				</div>
			</div>`;

		fillModels(device.brand, device.device_model);

		$("d-imei").addEventListener("input", () => {
			state.device.imei_1 = $("d-imei").value.trim();
		});
		$("d-noimei").addEventListener("change", () => {
			const off = $("d-noimei").checked;
			state.device.imei_unreadable = off;
			if (off) state.device.imei_1 = "";
			$("d-imei").value = "";
			$("d-imei").disabled = off;
			$("d-condition-field").hidden = !off;
			if (off) $("d-condition").focus();
		});
		$("d-condition").addEventListener("input", () => {
			state.device.condition = $("d-condition").value;
		});
		$("d-brand").addEventListener("change", () => {
			state.device.brand = $("d-brand").value;
			state.device.device_model = "";
			fillModels(state.device.brand, "");
		});
		if ($("new-model")) $("new-model").addEventListener("click", askNewModel);
	}

	/** Models for the chosen make — every model when no make is picked yet. */
	function fillModels(brand, selected) {
		const picker = $("d-model");
		if (!picker) return;
		const models = (state.models || []).filter((row) => !brand || row.brand === brand);

		picker.innerHTML = '<option value="">Pick the model…</option>'
			+ models.map((row) => `<option value="${esc(row.name)}"${
				row.name === selected ? " selected" : ""}>${esc(row.model_name || row.name)}</option>`).join("");

		picker.onchange = () => {
			const model = models.find((row) => row.name === picker.value);
			state.device.device_model = picker.value;
			if (model) {
				state.device.brand = model.brand;
				state.device.device_type = model.device_type || "Mobile";
				if ($("d-brand")) $("d-brand").value = model.brand;
			}
		};
	}

	async function askNewModel() {
		const brand = ($("d-brand") && $("d-brand").value) || "";
		if (!brand) return say("Pick the make first, then add the model under it.", "error");

		const model = window.prompt("Model name, without the make (e.g. Galaxy A15)");
		if (!model) return;

		try {
			const created = await A3.call("a3_retail.api.service_pos.create_device_model",
				{ brand, model_name: model.trim(), device_type: "Mobile" });
			state.models.push({ name: created.name, model_name: model.trim(),
			                    brand, device_type: created.device_type || "Mobile" });
			state.device.brand = brand;
			state.device.device_model = created.name;
			state.device.device_type = created.device_type || "Mobile";
			fillModels(brand, created.name);
			say(created.created ? created.name + " added." : created.name + " was already listed.", "ok");
		} catch (error) {
			say(error.message, "error");
		}
	}

	// ----------------------------------------------------------- customer
	async function findCustomer() {
		const mobile = $("mobile").value.trim();
		if (mobile.length !== 10) return say("Enter the ten-digit mobile number.", "error");

		const found = await A3.call("a3_retail.api.pos.find_customer", { mobile_no: mobile });
		if (!found) {
			state.customer = null;
			$("customer-name").value = "";
			return say("New number — add the name and it will be created on save.");
		}
		fillCustomer(found);
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
		say("");
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
				<small>${esc(row.mobile_no || row.email_id || "")}</small></button></li>`).join("");

		box.querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				box.hidden = true;
				$("cust-q").value = "";
				if (node.dataset.mobile) {
					$("mobile").value = node.dataset.mobile;
					return findCustomer();
				}
				state.customer = node.dataset.name;
			});
		});
	}

	function newCustomer() {
		state.customer = null;
		["mobile", "customer-name", "customer-email", "customer-address",
		 "customer-city", "customer-pin"].forEach((id) => { $(id).value = ""; });
		$("mobile").focus();
	}

	// -------------------------------------------------------------- lines
	async function openLinePicker() {
		$("line-modal").hidden = false;
		$("line-q").value = "";
		$("line-q").focus();
		await paintLineResults("");
	}

	async function paintLineResults(query) {
		const rows = await A3.call("a3_retail.api.service_pos.search_items", { query });
		$("line-results").innerHTML = rows.length
			? rows.map((row, index) => `
				<li><button data-i="${index}">
					<span><b>${esc(row.item_name)}</b>
						<small>${esc(row.kind)} · HSN ${esc(row.hsn || "—")}${
							row.is_stock_item ? " · " + row.branch_qty + " in stock" : ""}</small></span>
					<span>${money(row.rate)}</span>
				</button></li>`).join("")
			: '<li class="pos-loading">Nothing matches that.</li>';

		$("line-results").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				addLine(rows[Number(node.dataset.i)]);
				$("line-modal").hidden = true;
			});
		});
	}

	function addLine(item) {
		const existing = state.lines.find((line) => line.item_code === item.item_code);
		if (existing) existing.qty += 1;
		else state.lines.push({
			item_code: item.item_code, item_name: item.item_name, kind: item.kind,
			hsn: item.hsn || "", qty: 1, rate: item.rate, discount: 0,
		});
		paintLines();
	}

	function paintLines() {
		const box = $("lines");
		if (!state.lines.length) {
			box.innerHTML = '<div class="bill-empty">No parts or labour on this repair yet.</div>';
		} else {
			box.innerHTML = state.lines.map((line, index) => `
				<div class="line-row">
					<span class="line-n">${index + 1}</span>
					<span class="line-name"><b>${esc(line.item_name)}</b>
						<small>${esc(line.item_code)}</small></span>
					<span><em class="kind kind-${line.kind.toLowerCase()}">${esc(line.kind)}</em></span>
					<span class="line-hsn">${esc(line.hsn || "—")}</span>
					<span class="qty">
						<button data-act="minus" data-i="${index}">−</button>
						<span>${line.qty}</span>
						<button data-act="plus" data-i="${index}">+</button></span>
					<input class="rate" data-i="${index}" inputmode="decimal" value="${line.rate}">
					<input class="disc" data-i="${index}" inputmode="decimal" value="${line.discount}">
					<span class="amount">${money(amountOf(line))}</span>
					<button class="row-x" data-act="remove" data-i="${index}" aria-label="Remove">
						🗑</button>
				</div>`).join("");
		}

		box.querySelectorAll("[data-act]").forEach((node) => {
			node.addEventListener("click", () => {
				const index = Number(node.dataset.i);
				if (node.dataset.act === "remove") state.lines.splice(index, 1);
				if (node.dataset.act === "plus") state.lines[index].qty += 1;
				if (node.dataset.act === "minus") {
					state.lines[index].qty -= 1;
					if (state.lines[index].qty <= 0) state.lines.splice(index, 1);
				}
				paintLines();
			});
		});
		box.querySelectorAll(".rate, .disc").forEach((node) => {
			node.addEventListener("change", () => {
				const line = state.lines[Number(node.dataset.i)];
				const value = Number(String(node.value).replace(/[^0-9.]/g, "")) || 0;
				if (node.classList.contains("rate")) line.rate = value;
				else line.discount = Math.min(value, 100);
				paintLines();
			});
		});

		paintTotals();
	}

	function amountOf(line) {
		return line.qty * line.rate * (1 - (line.discount || 0) / 100);
	}

	// ------------------------------------------------------------ totals
	const COVERED = ["Brand Warranty", "Extended Warranty", "Screen Protection Plan", "Goodwill/Free"];

	function totals() {
		const sub = state.lines.reduce((sum, line) => sum + amountOf(line), 0);
		const type = $("discount-type").value;
		const typed = Number($("discount-value").value) || 0;
		const discount = Math.min(type === "%" ? sub * typed / 100 : typed, sub);
		const taxable = sub - discount;
		const gst = taxable * 0.18;
		const total = taxable + gst;
		const advance = Number($("advance").value) || 0;
		// The job card decides this too, from the device's own warranty — the
		// screen just stops the counter asking for money it should not ask for.
		const covered = COVERED.indexOf($("warranty-type").value) !== -1;
		const payable = covered ? 0 : total;
		return { sub, discount, taxable, gst, total, advance, covered, payable,
		         balance: Math.max(payable - advance, 0) };
	}

	function paintTotals() {
		const sums = totals();
		const count = state.lines.reduce((sum, line) => sum + line.qty, 0);

		$("line-count").textContent = count;
		$("sub-total").textContent = money(sums.sub);
		$("r-sub").textContent = money(sums.sub);
		$("r-discount").textContent = "- " + money(sums.discount);
		$("r-taxable").textContent = money(sums.taxable);
		$("r-gst").textContent = money(sums.gst);
		$("r-total").textContent = money(sums.total);
		$("balance").textContent = money(sums.balance);
		$("warranty-row").hidden = !sums.covered;
		$("r-warranty").textContent = money(sums.covered ? sums.total : 0);
		$("advance").disabled = sums.covered;
	}

	// ------------------------------------------------------------- steps
	function setStep(step) {
		state.step = step;
		document.querySelectorAll(".step").forEach((node) => {
			node.classList.toggle("is-active", node.dataset.step === step);
		});
	}

	function setTrack(index) {
		document.querySelectorAll("#track li").forEach((node, n) => {
			node.classList.toggle("is-active", n <= index);
		});
	}

	// ------------------------------------------------------------ photos
	/** The shop photographs a device before it takes it in, so there is no
	 *  argument later about the scratch that was already there (scope 3.2). */
	function addPhoto() {
		const picker = document.createElement("input");
		picker.type = "file";
		picker.accept = "image/*";
		picker.capture = "environment";
		picker.multiple = true;
		picker.addEventListener("change", () => uploadPhotos([...picker.files]));
		picker.click();
	}

	async function uploadPhotos(files) {
		const room = 4 - state.photos.length;
		if (room <= 0) return say("Four photos is the most a job card holds.", "error");

		for (const file of files.slice(0, room)) {
			const body = new FormData();
			body.append("file", file, file.name);
			body.append("is_private", "1");
			try {
				const response = await fetch("/api/method/upload_file", {
					method: "POST",
					headers: { "X-Frappe-CSRF-Token": A3.csrfToken() },
					body,
				});
				const payload = await response.json();
				if (!response.ok) throw new Error(payload.exception || "Upload failed");
				state.photos.push(payload.message.file_url);
			} catch (error) {
				say(error.message, "error");
			}
		}
		paintPhotos();
	}

	function paintPhotos() {
		const box = $("photos");
		const short = state.requirePhotos && state.photos.length < state.minPhotos;
		box.hidden = !state.photos.length && !short;
		box.innerHTML = state.photos.map((url, index) => `
			<span class="shot"><img src="${esc(url)}" alt="">
				<button data-i="${index}" aria-label="Remove">×</button></span>`).join("")
			+ (short
				? `<button class="shot shot-add" id="shot-add">+<small>Device photo</small></button>`
				: "");
		if ($("shot-add")) $("shot-add").addEventListener("click", addPhoto);
		box.querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				state.photos.splice(Number(node.dataset.i), 1);
				paintPhotos();
			});
		});
	}

	// --------------------------------------------------------- signature
	/** A job card is a receipt for someone else's property; the shop asks for a
	 *  signature before it takes the device (scope 3.2). */
	function askSignature() {
		const pad = $("sign-pad");
		const context = pad.getContext("2d");
		context.clearRect(0, 0, pad.width, pad.height);
		context.lineWidth = 2.2;
		context.lineCap = "round";
		context.strokeStyle = "#2a3342";
		state.signed = false;

		let drawing = false;
		const point = (event) => {
			const box = pad.getBoundingClientRect();
			const touch = event.touches ? event.touches[0] : event;
			return [(touch.clientX - box.left) * pad.width / box.width,
			        (touch.clientY - box.top) * pad.height / box.height];
		};
		const down = (event) => {
			drawing = true; state.signed = true;
			context.beginPath(); context.moveTo(...point(event)); event.preventDefault();
		};
		const move = (event) => {
			if (!drawing) return;
			context.lineTo(...point(event)); context.stroke(); event.preventDefault();
		};
		const up = () => { drawing = false; };

		pad.onmousedown = down; pad.onmousemove = move;
		pad.onmouseup = up; pad.onmouseleave = up;
		pad.ontouchstart = down; pad.ontouchmove = move; pad.ontouchend = up;

		$("sign-modal").hidden = false;
	}

	// ------------------------------------------------------------ actions
	async function saveBooking() {
		if (!state.lines.length && !$("complaint").value.trim()) {
			return say("Write down what the customer says is wrong.", "error");
		}
		if (!$("backup-required").checked && !$("data-consent").checked) {
			return say("Tick either 'Data backup required' or 'Customer accepts data loss'.", "error");
		}

		const device = state.device || {};
		if (!device.imei_1 && !device.imei_unreadable) {
			if ($("d-imei")) $("d-imei").focus();
			return say("Scan or type the IMEI — or tick that the device cannot show one.", "error");
		}
		if (device.imei_unreadable && !(device.condition || "").trim()) {
			if ($("d-condition")) $("d-condition").focus();
			return say("Describe the device — with no IMEI, that description is all that "
				+ "identifies it.", "error");
		}
		if (!device.device_model) {
			if ($("d-model")) $("d-model").focus();
			return say("Pick the make and model of the device — or scan its IMEI.", "error");
		}

		if (state.requirePhotos && state.photos.length < state.minPhotos) {
			say(`This shop photographs a device before it takes it in — `
				+ `${state.minPhotos} photo(s), and there ${state.photos.length === 1 ? "is" : "are"} `
				+ `${state.photos.length}.`, "error");
			return addPhoto();
		}

		if (!state.signed) return askSignature();

		const sums = totals();
		$("save-booking").disabled = true;

		try {
			const result = await A3.call("a3_retail.api.service_pos.save_booking", {
				payload: {
					customer: state.customer,
					mobile_no: $("mobile").value.trim(),
					customer_name: $("customer-name").value.trim(),
					serial_no: device.serial_no,
					imei_1: device.imei_1 || "",
					imei_unreadable: device.imei_unreadable ? 1 : 0,
					device_condition: device.condition || "",
					brand: device.brand,
					device_model: device.device_model,
					device_type: device.device_type,
					purchase_date: device.purchase_date || null,
					warranty_type: $("warranty-type").value,
					warranty_expiry_date: device.warranty_expiry_date || null,
					warranty_registration: device.warranty_registration,
					service_type: state.serviceType,
					issues: $("issue").value ? [$("issue").value] : [],
					complaint_description: $("complaint").value.trim(),
					priority: state.priority,
					lead_source: state.leadSource,
					technician: $("technician").value || null,
					expected_delivery: $("promised").value || null,
					data_backup_required: $("backup-required").checked ? 1 : 0,
					data_loss_consent: $("data-consent").checked ? 1 : 0,
					notes: $("notes").value.trim(),
					signature: $("sign-pad").toDataURL("image/png"),
					photos: state.photos,
					discount_amount: sums.discount,
					advance_amount: sums.advance,
					items: state.lines,
				},
			});
			done(result);
		} catch (error) {
			say(error.message || "Could not save the booking.", "error");
		} finally {
			$("save-booking").disabled = false;
		}
	}

	function done(result) {
		state.jobCard = result.job_card;
		$("done-title").textContent = "Booked in";
		$("done-note").textContent = `${result.job_card} · ${result.customer_name || ""} · `
			+ (result.warranty_borne
				? `${result.warranty_type} — the warranty bears ${money(result.warranty_borne)}`
				: `balance ${money(result.balance)}`);
		$("done-print").href = result.print_url;
		$("done-modal").hidden = false;
		setTrack(0);
		say("Job card " + result.job_card + " is open.", "ok");
	}

	async function generateInvoice() {
		if (!state.jobCard) return say("Save the booking first.", "error");
		try {
			const result = await A3.call("a3_retail.api.service_pos.generate_invoice",
				{ job_card: state.jobCard });
			$("done-title").textContent = "Invoiced";
			$("done-note").textContent = `${result.sales_invoice} · ${money(result.grand_total || 0)}`;
			$("done-print").href = result.print_url;
			$("done-modal").hidden = false;
			setStep("invoice");
			setTrack(2);
		} catch (error) {
			say(error.message, "error");
		}
	}

	function askDelivery() {
		if (!state.jobCard) return say("Save the booking first.", "error");
		$("otp-modal").hidden = false;
		$("otp").value = "";
		$("otp").focus();
	}

	async function confirmDelivery() {
		try {
			await A3.call("a3_retail.api.service_pos.mark_delivered", {
				job_card: state.jobCard,
				otp: $("otp").value.trim(),
				receiver: $("receiver").value.trim() || null,
			});
			$("otp-modal").hidden = true;
			setStep("delivery");
			setTrack(3);
			say("Handed over. " + state.jobCard + " is closed.", "ok");
		} catch (error) {
			say(error.message, "error");
		}
	}

	async function communicate(channel) {
		if (channel === "Print") {
			if (!state.jobCard) return say("Save the booking first.", "error");
			return window.open("/api/method/frappe.utils.print_format.download_pdf"
				+ "?doctype=Service%20Job%20Card&name=" + encodeURIComponent(state.jobCard)
				+ "&format=Job%20Card%20Acknowledgement", "_blank");
		}
		if (!state.jobCard) return say("Save the booking first.", "error");
		try {
			const result = await A3.call("a3_retail.api.service_pos.notify",
				{ job_card: state.jobCard, channel });
			say(result.sent ? channel + " sent." : channel + " was not sent — check messaging settings.",
				result.sent ? "ok" : "error");
		} catch (error) {
			say(error.message, "error");
		}
	}

	function loadBooking(card) {
		state.jobCard = card.job_card;
		state.customer = card.customer;
		state.device = card;
		state.lines = (card.items || []).map((line) => ({ ...line, discount: 0 }));
		$("mobile").value = card.mobile_no || "";
		$("customer-name").value = card.customer_name || "";
		$("complaint").value = card.complaint_description || "";
		$("advance").value = card.advance || "";
		paintDevice();
		paintLines();
		setTrack(card.status === "Delivered" ? 3
			: card.status === "Ready for Delivery" ? 2
			: card.status === "In Progress" ? 1 : 0);
		say("Loaded " + card.job_card + " (" + card.status + ").");
	}

	// ------------------------------------------------------- quick actions
	async function recentBookings() {
		const rows = await A3.call("a3_retail.api.service_pos.recent_bookings", {});
		showList("Recent bookings", "", rows.map((row) => ({
			title: row.name + " · " + (row.customer_name || ""),
			sub: row.status + " · " + (row.device_model || ""),
			onPick: () => lookupDevice(row.name),
		})));
	}

	function showList(title, note, rows) {
		$("list-title").textContent = title;
		$("list-note").textContent = note || "";
		$("list-body").innerHTML = rows.length
			? rows.map((row, index) => `
				<li><button class="linkish" data-i="${index}">${esc(row.title)}</button>
					<small>${esc(row.sub || "")}</small></li>`).join("")
			: "<li>Nothing here yet.</li>";
		$("list-body").querySelectorAll("button").forEach((node) => {
			node.addEventListener("click", () => {
				const row = rows[Number(node.dataset.i)];
				$("list-modal").hidden = true;
				if (row.onPick) row.onPick();
			});
		});
		$("list-modal").hidden = false;
	}

	function clearAll() {
		state.jobCard = null;
		state.device = null;
		state.lines = [];
		state.customer = null;
		["mobile", "customer-name", "customer-email", "customer-address", "customer-city",
		 "customer-pin", "complaint", "notes", "advance", "discount-value", "promised"]
			.forEach((id) => { $(id).value = ""; });
		$("backup-required").checked = false;
		$("data-consent").checked = false;
		state.signed = false;
		state.photos = [];
		paintPhotos();
		paintDevice();
		paintLines();
		setStep("booking");
		setTrack(0);
		say("");
	}

	// --------------------------------------------------------------- start
	async function start(options) {
		state.branch = options.branch;
		$("promised").value = options.today;

		let boot;
		try {
			boot = await A3.call("a3_retail.api.service_pos.bootstrap", {});
		} catch (error) {
			// Without this the whole screen wires up no listeners and looks alive
			// while doing nothing at all.
			say("The counter could not start: " + error.message
				+ " — reload, and tell whoever runs the system.", "error");
			throw error;
		}
		state.types = boot.service_types;
		state.issues = boot.issues;
		state.technicians = boot.technicians;
		state.brands = boot.brands || [];
		state.canAddModel = !!boot.can_add_model;
		state.requirePhotos = !!boot.require_photos;
		state.minPhotos = boot.min_photos || 1;
		state.models = await A3.call("a3_retail.api.service_pos.device_models", { limit: 500 });

		// The tiles themselves are server-rendered so they carry the real icons.
		$("service-types").addEventListener("click", (event) => {
			const tile = event.target.closest(".type");
			if (!tile) return;
			$("service-types").querySelectorAll(".type").forEach((t) => t.classList.remove("is-active"));
			tile.classList.add("is-active");
			state.serviceType = tile.dataset.key;
		});

		$("issue").innerHTML = '<option value="">Select the problem…</option>'
			+ boot.issues.map((issue) =>
				`<option value="${esc(issue.name)}">${esc(issue.issue_name)}</option>`).join("");
		$("technician").innerHTML = '<option value="">Auto Assign</option>'
			+ boot.technicians.map((tech) =>
				`<option value="${esc(tech.employee)}">${esc(tech.employee_name)}</option>`).join("");
		$("warranty-type").innerHTML = boot.warranty_types.map((type) =>
			`<option value="${esc(type)}"${type === "Out of Warranty" ? " selected" : ""}>
				${esc(type === "Out of Warranty" ? "Paid" : type)}</option>`).join("");

		// ----------------------------------------------------------- wiring
		$("scan").addEventListener("keydown", (event) => {
			if (event.key === "Enter") { lookupDevice($("scan").value.trim()); $("scan").value = ""; }
		});
		$("cust-q").addEventListener("input", () => {
			clearTimeout(custTimer); custTimer = setTimeout(searchCustomers, 220);
		});
		$("find-customer").addEventListener("click", findCustomer);
		$("mobile").addEventListener("keydown", (e) => { if (e.key === "Enter") findCustomer(); });
		$("new-customer").addEventListener("click", newCustomer);
		$("another-device").addEventListener("click", () => {
			state.device = null; paintDevice(); $("scan").focus();
		});
		$("scan").addEventListener("blur", () => {
			// A counter that types the IMEI and tabs away should not lose it.
			const typed = $("scan").value.trim();
			if (typed && /^\d{15}$/.test(typed)) lookupDevice(typed);
		});

		$("add-line").addEventListener("click", openLinePicker);
		let lineTimer;
		$("line-q").addEventListener("input", () => {
			clearTimeout(lineTimer);
			lineTimer = setTimeout(() => paintLineResults($("line-q").value.trim()), 220);
		});

		$("warranty-type").addEventListener("change", paintTotals);
		$("discount-type").addEventListener("change", paintTotals);
		$("discount-value").addEventListener("input", paintTotals);
		$("advance").addEventListener("input", paintTotals);

		$("complaint").addEventListener("input", () => {
			$("complaint-count").textContent = $("complaint").value.length;
		});
		$("notes").addEventListener("input", () => {
			$("notes-count").textContent = $("notes").value.length;
		});

		document.querySelectorAll("#lead-source .seg-btn").forEach((node) => {
			node.addEventListener("click", () => {
				document.querySelectorAll("#lead-source .seg-btn")
					.forEach((b) => b.classList.remove("is-active"));
				node.classList.add("is-active");
				state.leadSource = node.dataset.value;
			});
		});
		document.querySelectorAll("#priority .seg-btn").forEach((node) => {
			node.addEventListener("click", () => {
				document.querySelectorAll("#priority .seg-btn")
					.forEach((b) => b.classList.remove("is-active"));
				node.classList.add("is-active");
				state.priority = node.dataset.value;
			});
		});
		document.querySelectorAll(".step").forEach((node) => {
			node.addEventListener("click", () => setStep(node.dataset.step));
		});
		document.querySelectorAll(".comm").forEach((node) => {
			node.addEventListener("click", () => communicate(node.dataset.channel));
		});

		$("save-booking").addEventListener("click", saveBooking);
		$("sign-clear").addEventListener("click", () => {
			const pad = $("sign-pad");
			pad.getContext("2d").clearRect(0, 0, pad.width, pad.height);
			state.signed = false;
		});
		$("sign-done").addEventListener("click", () => {
			if (!state.signed) return say("Ask the customer to sign first.", "error");
			$("sign-modal").hidden = true;
			saveBooking();
		});
		$("generate-invoice").addEventListener("click", generateInvoice);
		$("mark-delivered").addEventListener("click", askDelivery);
		$("confirm-delivery").addEventListener("click", confirmDelivery);
		$("resend-otp").addEventListener("click", async () => {
			try {
				await A3.call("a3_retail.api.service_pos.resend_otp", { job_card: state.jobCard });
				say("A fresh OTP is on its way to the customer.", "ok");
			} catch (error) { say(error.message, "error"); }
		});

		const quick = {
			clear: clearAll,
			hold: () => say("Held. The card stays on this screen until you save it."),
			diagnose: recentBookings,
			estimate: () => communicate("Print"),
			advance: () => $("advance").focus(),
			photo: addPhoto,
		};
		document.querySelectorAll(".quick").forEach((node) => {
			node.addEventListener("click", () => (quick[node.dataset.action] || (() => {}))());
		});

		document.querySelectorAll("[data-close]").forEach((node) => {
			node.addEventListener("click", () => {
				node.closest(".modal").hidden = true;
				if (node.closest("#done-modal")) clearAll();
			});
		});

		document.addEventListener("keydown", (event) => {
			if (event.key === "F5") { event.preventDefault(); saveBooking(); }
			if (event.key === "F6") { event.preventDefault(); generateInvoice(); }
			if (event.key === "F7") { event.preventDefault(); askDelivery(); }
			if (event.key === "Escape") {
				document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
			}
		});

		paintLines();
		paintDevice();
		paintPhotos();
		$("scan").focus();
	}

	return { start, state };
})();
