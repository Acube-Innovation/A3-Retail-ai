// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
/**
 * A3 Retail — Branch App client.
 *
 * These pages are standalone: no ERPNext desk bundle, no jQuery, no frappe
 * global. Everything the app needs from the server goes through one helper that
 * calls a whitelisted method and carries the CSRF token Frappe expects once a
 * session exists.
 */

window.A3 = (function () {
	function csrfToken() {
		const tag = document.querySelector('meta[name="csrf-token"]');
		return tag ? tag.getAttribute("content") : "";
	}

	async function call(method, args) {
		const response = await fetch("/api/method/" + method, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": csrfToken(),
			},
			body: JSON.stringify(args || {}),
		});

		let payload = {};
		try {
			payload = await response.json();
		} catch (error) {
			payload = {};
		}

		if (!response.ok) {
			// Frappe puts the readable reason in _server_messages or exception.
			const error = new Error(firstMessage(payload) || plain(response.statusText));
			error.title = payloadTitle(payload);
			throw error;
		}
		return payload.message;
	}

	/**
	 * The reason, in words somebody behind a counter can act on.
	 *
	 * Frappe answers with HTML in `_server_messages`, and when nothing threw a
	 * message of its own it answers with the exception's class name — "
	 * ValidationError" on a screen tells a counter nothing at all, so the bare
	 * class names are translated here instead of being shown raw.
	 */
	function firstMessage(payload) {
		const messages = serverMessages(payload);
		if (messages.length) return messages.map((row) => plain(row.message)).join(" ");
		return plain(payload.exception || payload.exc_type || payload.message || "");
	}

	function payloadTitle(payload) {
		const messages = serverMessages(payload);
		const title = messages.length ? plain(messages[0].title || "") : "";
		return title && title !== "Message" && title !== "Error" ? title : "";
	}

	function serverMessages(payload) {
		try {
			return JSON.parse(payload._server_messages || "[]")
				.map((row) => (typeof row === "string" ? JSON.parse(row) : row))
				.filter((row) => row && row.message);
		} catch (error) {
			return [];
		}
	}

	// What Frappe's own exception classes mean to the person at the counter.
	const PLAIN = {
		ValidationError: "Something on this entry is not right — check the highlighted field "
			+ "and try again.",
		MandatoryError: "Something the system needs is still empty.",
		LinkValidationError: "One of the things picked here no longer exists.",
		PermissionError: "You are not allowed to do that. Ask a manager.",
		DoesNotExistError: "That record is not there any more.",
		DuplicateEntryError: "There is already one of these.",
		TimestampMismatchError: "Somebody else changed this while it was open here. "
			+ "Reload the page and try again.",
		CSRFTokenError: "This page has been open too long. Reload it and try again.",
		SessionExpired: "The session has expired. Sign in again.",
	};

	/** HTML out, entities decoded, bare exception names turned into sentences. */
	function plain(text) {
		let value = String(text == null ? "" : text);
		value = value.replace(/<br\s*\/?>/gi, " ").replace(/<\/(p|div|li)>/gi, " ");
		const node = document.createElement("div");
		node.innerHTML = value;
		value = (node.textContent || "").replace(/\s+/g, " ").trim();

		// "frappe.exceptions.ValidationError" and friends, with nothing to say.
		const bare = value.split(".").pop();
		if (PLAIN[bare]) return PLAIN[bare];
		for (const name of Object.keys(PLAIN)) {
			if (value === name || value === "frappe.exceptions." + name) return PLAIN[name];
		}
		return value;
	}

	async function login(usr, pwd) {
		const response = await fetch("/api/method/login", {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: new URLSearchParams({ usr, pwd }),
		});
		const payload = await response.json().catch(() => ({}));

		// Frappe answers "Logged In" for desk users and "No App" for website
		// users — both mean the session is open.
		const ok = payload.message === "Logged In" || payload.message === "No App";
		if (!response.ok || !ok) throw new Error("wrong-credentials");
		return payload;
	}

	async function logout() {
		await fetch("/api/method/logout", { method: "POST" });
		window.location.href = "/retail";
	}

	function money(value) {
		return new Intl.NumberFormat("en-IN", {
			style: "currency", currency: "INR", maximumFractionDigits: 0,
		}).format(value || 0);
	}

	function shortTime(value) {
		if (!value) return "";
		const date = new Date(value.replace(" ", "T"));
		if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
		return date.toLocaleString("en-IN", {
			day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
		});
	}

	/** An alert every page raises the same way: loud, readable, and gone by itself. */
	function toast(text, kind, title) {
		const box = document.createElement("div");
		box.className = "toast" + (kind ? " " + kind : "");
		box.setAttribute("role", kind === "error" ? "alert" : "status");
		if (title) {
			const head = document.createElement("b");
			head.textContent = title;
			box.appendChild(head);
		}
		const body = document.createElement("span");
		body.textContent = plain(text);
		box.appendChild(body);
		document.body.appendChild(box);
		setTimeout(() => box.remove(), kind === "error" ? 6000 : 3600);
		return box;
	}

	/**
	 * Branch picker.
	 *
	 * Shop-floor staff work at one counter and see no picker at all. Head-office
	 * roles are branch-agnostic, so for them the topbar branch name becomes a
	 * selector. Injected here rather than into each of the ten page templates,
	 * which all render the same `.topbar-branch` block.
	 */
	async function mountBranchPicker() {
		const host = document.querySelector(".topbar-branch");
		if (!host || host.querySelector(".branch-picker")) return;

		let ctx;
		try {
			ctx = await call("a3_retail.api.staff.session_context");
		} catch (error) {
			return; // the page already renders a branch name; leave it alone
		}
		if (!ctx || !ctx.can_switch_branch || !Array.isArray(ctx.branches)) return;

		const heading = host.querySelector("h1");
		const select = document.createElement("select");
		select.className = "branch-picker";
		select.setAttribute("aria-label", "Switch branch");
		ctx.branches.forEach(function (name) {
			const option = document.createElement("option");
			option.value = name;
			option.textContent = name;
			if (name === ctx.branch) option.selected = true;
			select.appendChild(option);
		});

		select.addEventListener("change", async function () {
			const target = select.value;
			select.disabled = true;
			try {
				await call("a3_retail.api.staff.switch_branch", { branch: target });
				window.location.reload();
			} catch (error) {
				select.disabled = false;
				select.value = ctx.branch;
				toast(error.message || "Could not switch branch", "error", error.title);
			}
		});

		// Never take the heading out. Four screens write their own title into
		// it once their data arrives — the booking, the invoice, the parts list
		// and the reports — and replacing it left them setting textContent on
		// nothing, so for anybody who can see two branches those pages died with
		// "Cannot set properties of null". The branch chip inside the heading is
		// what the picker is really replacing; where there is no chip it simply
		// sits alongside.
		const chip = heading && heading.querySelector(".chip");
		if (chip) {
			chip.replaceWith(select);
		} else if (heading) {
			heading.insertAdjacentElement("afterend", select);
		} else {
			host.prepend(select);
		}
	}

	/**
	 * Phone navigation.
	 *
	 * The sidebar is twelve destinations in a column — right on a desk, wrong in
	 * a hand. On a phone the four most-used become a fixed bottom bar, thumb
	 * height, and everything else lives behind More. Built from the sidebar that
	 * is already on the page, so no template has to know about it.
	 */
	const PRIMARY = ["/retail/dashboard", "/retail/sales", "/retail/bills", "/retail/stock"];

	function mountMobileNav() {
		if (document.querySelector(".tabbar")) return;
		const side = document.querySelector(".side .side-nav");
		if (!side) return;

		const links = [...side.querySelectorAll("a")];
		if (!links.length) return;

		const bar = document.createElement("nav");
		bar.className = "tabbar";
		bar.setAttribute("aria-label", "Main");

		const pick = (href) => links.find((a) => (a.getAttribute("href") || "") === href);
		const chosen = PRIMARY.map(pick).filter(Boolean);
		// Fall back to the first four if this build renames its routes.
		const tabs = chosen.length ? chosen : links.slice(0, 4);

		tabs.forEach((link) => {
			const a = document.createElement("a");
			a.href = link.getAttribute("href");
			a.innerHTML = link.innerHTML;
			if (link.classList.contains("is-active")) a.classList.add("is-active");
			bar.appendChild(a);
		});

		const more = document.createElement("button");
		more.type = "button";
		more.className = "tabbar-more";
		more.setAttribute("aria-expanded", "false");
		more.innerHTML =
			'<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
			+ ' stroke-width="2" stroke-linecap="round"><circle cx="5" cy="12" r="1"/>'
			+ '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg><span>More</span>';
		bar.appendChild(more);

		const sheet = document.createElement("div");
		sheet.className = "navsheet";
		sheet.hidden = true;
		const card = document.createElement("div");
		card.className = "navsheet-card";
		card.innerHTML = '<div class="navsheet-grip"></div>';
		// Clone the sidebar's own blocks, wrappers and all. Copying the links
		// alone would drop the `.side-nav` container the sheet is styled through.
		const aside = side.closest(".side") || side.parentElement;
		[...aside.children].forEach((node) => card.appendChild(node.cloneNode(true)));
		sheet.appendChild(card);

		const close = () => {
			sheet.hidden = true;
			more.setAttribute("aria-expanded", "false");
			document.body.classList.remove("navsheet-open");
		};
		more.addEventListener("click", () => {
			const open = sheet.hidden;
			sheet.hidden = !open;
			more.setAttribute("aria-expanded", String(open));
			document.body.classList.toggle("navsheet-open", open);
		});
		sheet.addEventListener("click", (event) => { if (event.target === sheet) close(); });
		document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

		document.body.append(bar, sheet);
		document.body.classList.add("has-tabbar");
	}

	document.addEventListener("DOMContentLoaded", () => {
		mountBranchPicker();
		mountMobileNav();
		watchForDates();
	});

	/* ------------------------------------------------------------------ dates
	 * A calendar the counter can drive with a thumb.
	 *
	 * The browser's own date box makes you walk a month at a time, which is a
	 * long walk when a bill is dated last April. This is the calendar the shop
	 * already knows from its old software: the month and the year step on their
	 * own, nothing is committed until OK, and Cancel leaves the date alone.
	 *
	 * The real <input type="date"> stays in the form holding an ISO value, so
	 * everything that reads `.value` keeps working; it is just not what the
	 * counter touches any more.
	 */
	const MONTHS = ["January", "February", "March", "April", "May", "June",
		"July", "August", "September", "October", "November", "December"];
	const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

	const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1)
		.padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
	const parseIso = (v) => {
		const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v || ""));
		return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
	};
	const pretty = (d) => d
		? `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getFullYear()}`
		: "";

	function datePicker(input) {
		if (!input) return;
		// Mounted already *and* its face still on the page. Screens redraw their
		// own markup all day; when a redraw takes the face with it the hidden
		// input would be left with nothing to click, so it is mounted again.
		const face = input.nextElementSibling;
		if (input.dataset.a3dp && face && face.classList.contains("dp-face")) return;
		input.dataset.a3dp = "1";
		input.hidden = true;

		const button = document.createElement("button");
		button.type = "button";
		button.className = "dp-face";
		input.parentNode.insertBefore(button, input.nextSibling);

		const show = () => {
			const d = parseIso(input.value);
			button.textContent = d ? pretty(d) : "Choose a date";
			button.classList.toggle("is-empty", !d);
		};
		show();

		// The bounds are read when the calendar opens, not when it is mounted:
		// a screen often fills in the date and its limits after the box is on
		// the page — the payment dialog sets both as it opens — and bounds read
		// once at mount would be the ones that were not there yet.
		button.addEventListener("click", () => open(
			input, button,
			input.max ? parseIso(input.max) : null,
			input.min ? parseIso(input.min) : null,
			show));
		// Something else set the date — keep the face honest.
		input.addEventListener("change", show);
		// A value written straight into .value fires nothing, so the face is
		// refreshed on the way in as well.
		show();
	}

	function open(input, face, limit, floor, show) {
		const chosen = parseIso(input.value) || new Date();
		let year = chosen.getFullYear();
		let month = chosen.getMonth();
		let picked = parseIso(input.value) || new Date();

		const wrap = document.createElement("div");
		wrap.className = "dp-backdrop";
		wrap.innerHTML = `<div class="dp-card" role="dialog" aria-label="Pick a date">
			<div class="dp-title"></div>
			<div class="dp-steppers">
				<div class="dp-step"><button type="button" data-m="-1">&lsaquo;</button>
					<span class="dp-month"></span>
					<button type="button" data-m="1">&rsaquo;</button></div>
				<div class="dp-step"><button type="button" data-y="-1">&lsaquo;</button>
					<span class="dp-year"></span>
					<button type="button" data-y="1">&rsaquo;</button></div>
			</div>
			<div class="dp-grid dp-names">${DAYS.map((d) =>
				`<span class="dp-name">${d}</span>`).join("")}</div>
			<div class="dp-grid dp-days"></div>
			<div class="dp-actions">
				<button type="button" class="dp-flat" data-cancel>CANCEL</button>
				<button type="button" class="dp-flat dp-ok" data-ok>OK</button>
			</div>
		</div>`;
		document.body.appendChild(wrap);

		const q = (sel) => wrap.querySelector(sel);
		const close = () => wrap.remove();

		function paint() {
			q(".dp-title").textContent = pretty(picked);
			q(".dp-month").textContent = MONTHS[month];
			q(".dp-year").textContent = year;

			const first = new Date(year, month, 1);
			const start = first.getDay();
			const cells = [];
			// A month reads as a block of weeks, so the days either side of it
			// are shown greyed rather than left as holes.
			for (let i = 0; i < 42; i++) {
				const d = new Date(year, month, 1 - start + i);
				const out = d.getMonth() !== month;
				const beyond = (limit && d > limit) || (floor && d < floor);
				const on = picked && iso(d) === iso(picked);
				cells.push(`<button type="button" class="dp-day${out ? " is-out" : ""}${
					on ? " is-on" : ""}" data-iso="${iso(d)}"${
					beyond ? " disabled" : ""}>${d.getDate()}</button>`);
			}
			q(".dp-days").innerHTML = cells.join("");
		}
		paint();

		wrap.addEventListener("click", (event) => {
			const step = event.target.closest("[data-m], [data-y]");
			if (step) {
				if (step.dataset.m) {
					month += Number(step.dataset.m);
					if (month < 0) { month = 11; year -= 1; }
					if (month > 11) { month = 0; year += 1; }
				} else {
					year += Number(step.dataset.y);
				}
				return paint();
			}
			const day = event.target.closest(".dp-day");
			if (day && !day.disabled) {
				picked = parseIso(day.dataset.iso);
				month = picked.getMonth();
				year = picked.getFullYear();
				return paint();
			}
			if (event.target.closest("[data-ok]")) {
				input.value = iso(picked);
				input.dispatchEvent(new Event("change", { bubbles: true }));
				show();
				return close();
			}
			// Cancel, and the backdrop itself, leave the date as it was.
			if (event.target.closest("[data-cancel]") || event.target === wrap) close();
		});
		document.addEventListener("keydown", function esc(event) {
			if (event.key !== "Escape") return;
			document.removeEventListener("keydown", esc);
			close();
		});
	}

	/** Every date box on the page gets the calendar, not the browser's own.
	 *
	 * Screens build their rows and dialogs as they go, so this runs again
	 * whenever the page grows. Cheap: the work is one attribute check per box.
	 */
	function mountDates(root) {
		(root || document).querySelectorAll('input[type="date"]').forEach(datePicker);
	}

	function watchForDates() {
		mountDates();
		if (typeof MutationObserver !== "function") return;
		let queued = false;
		new MutationObserver(() => {
			if (queued) return;
			queued = true;
			// One pass after the screen has finished redrawing, rather than one
			// per node it happens to add.
			requestAnimationFrame(() => { queued = false; mountDates(); });
		}).observe(document.body, { childList: true, subtree: true });
	}

	// ------------------------------------------------------------- photos
	/**
	 * Ask for pictures, from the camera or from the machine.
	 *
	 * Built after Frappe's own upload window — drop area, and a tile per place
	 * a file can come from — because that is the dialog anyone who has seen the
	 * desk already knows. Resolves to an array of File; an empty one means the
	 * counter changed their mind.
	 *
	 * The camera tile only appears where the browser will actually hand one
	 * over: `getUserMedia` exists and the page is a secure context. Over plain
	 * http on a LAN address it is neither, and a tile that opens nothing is
	 * worse than no tile.
	 */
	function photoPicker(options) {
		const settings = Object.assign({
			title: "Add photo", note: "", accept: "image/*",
			multiple: true, max: 0,
		}, options || {});

		return new Promise((resolve) => {
			const picked = [];
			let stream = null;

			const modal = document.createElement("div");
			modal.className = "modal";
			modal.innerHTML = `
				<div class="modal-card fup">
					<h3>${escapeHtml(settings.title)}</h3>
					<p class="modal-note">${escapeHtml(settings.note
						|| "Drag a picture here, or add one from")}</p>
					<div class="fup-sources">
						<button type="button" class="fup-source" data-src="camera" hidden>
							<span class="fup-ico">${CAMERA_GLYPH}</span>Camera</button>
						<button type="button" class="fup-source" data-src="device">
							<span class="fup-ico">${DEVICE_GLYPH}</span>My Device</button>
					</div>
					<div class="fup-stage" data-drop>
						<p class="fup-hint">Drop a picture here</p>
					</div>
					<div class="fup-strip"></div>
					<div class="msg" data-msg></div>
					<div class="modal-actions">
						<button type="button" class="btn btn-quiet" data-cancel>Cancel</button>
						<button type="button" class="btn btn-primary" data-done disabled>Add</button>
					</div>
				</div>`;
			document.body.appendChild(modal);

			const q = (sel) => modal.querySelector(sel);
			const stage = q("[data-drop]");
			const strip = q(".fup-strip");
			const done = q("[data-done]");
			const msg = q("[data-msg]");

			function say(text, kind) {
				msg.textContent = text || "";
				msg.className = "msg" + (kind ? " " + kind : "");
			}

			function room() {
				return settings.max ? settings.max - picked.length : Infinity;
			}

			function paint() {
				strip.innerHTML = picked.map((file, index) =>
					`<span class="fup-thumb"><img src="${URL.createObjectURL(file)}" alt="">
						<button type="button" data-drop-i="${index}" aria-label="Remove">×</button>
					</span>`).join("");
				strip.querySelectorAll("[data-drop-i]").forEach((node) => {
					node.addEventListener("click", () => {
						picked.splice(Number(node.dataset.dropI), 1);
						paint();
					});
				});
				done.disabled = !picked.length;
				done.textContent = picked.length > 1
					? `Add ${picked.length} photos` : "Add";
			}

			function take(files) {
				const images = [...files].filter((f) => f.type.startsWith("image/")
					|| settings.accept !== "image/*");
				if (!images.length) return say("That is not a picture.", "error");
				const space = room();
				if (space <= 0) return say(`That is already ${settings.max}.`, "error");
				picked.push(...images.slice(0, settings.multiple ? space : 1));
				if (images.length > space) say(`Only ${settings.max} fit — the rest were left.`);
				else say("");
				paint();
			}

			// ---- from the machine
			function fromDevice() {
				const input = document.createElement("input");
				input.type = "file";
				input.accept = settings.accept;
				input.multiple = Boolean(settings.multiple);
				input.addEventListener("change", () => take(input.files));
				input.click();
			}

			// ---- from the camera
			async function fromCamera() {
				say("");
				stage.innerHTML = `<video autoplay playsinline muted></video>
					<div class="fup-shoot">
						<button type="button" class="btn btn-primary" data-snap>Take photo</button>
						<button type="button" class="btn btn-quiet" data-stop>Stop camera</button>
					</div>`;
				try {
					stream = await navigator.mediaDevices.getUserMedia({
						video: { facingMode: { ideal: "environment" } }, audio: false });
				} catch (error) {
					stopCamera();
					// A shop tablet refuses for one of two reasons and the fix
					// differs, so the browser's own words are more use than ours.
					say(error && error.name === "NotAllowedError"
						? "The browser blocked the camera. Allow it for this site, then try again."
						: "No camera the browser will open: " + (error.message || error.name),
						"error");
					return;
				}
				const video = stage.querySelector("video");
				video.srcObject = stream;
				stage.querySelector("[data-snap]").addEventListener("click", () => snap(video));
				stage.querySelector("[data-stop]").addEventListener("click", stopCamera);
			}

			function snap(video) {
				const canvas = document.createElement("canvas");
				canvas.width = video.videoWidth;
				canvas.height = video.videoHeight;
				canvas.getContext("2d").drawImage(video, 0, 0);
				canvas.toBlob((blob) => {
					if (!blob) return say("The camera gave nothing back.", "error");
					const stamp = new Date().toISOString().replace(/[:.]/g, "-");
					take([new File([blob], `photo-${stamp}.jpg`, { type: "image/jpeg" })]);
					if (room() <= 0) stopCamera();
				}, "image/jpeg", 0.9);
			}

			function stopCamera() {
				if (stream) {
					stream.getTracks().forEach((track) => track.stop());
					stream = null;
				}
				stage.innerHTML = '<p class="fup-hint">Drop a picture here</p>';
			}

			// ---- wiring
			if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia
					&& window.isSecureContext) {
				q('[data-src="camera"]').hidden = false;
				q('[data-src="camera"]').addEventListener("click", fromCamera);
			}
			q('[data-src="device"]').addEventListener("click", fromDevice);

			["dragenter", "dragover"].forEach((name) =>
				stage.addEventListener(name, (event) => {
					event.preventDefault();
					stage.classList.add("is-over");
				}));
			["dragleave", "drop"].forEach((name) =>
				stage.addEventListener(name, () => stage.classList.remove("is-over")));
			stage.addEventListener("drop", (event) => {
				event.preventDefault();
				take(event.dataTransfer.files);
			});

			function close(result) {
				stopCamera();
				modal.remove();
				document.removeEventListener("keydown", onKey);
				resolve(result);
			}
			function onKey(event) {
				if (event.key === "Escape") close([]);
			}
			document.addEventListener("keydown", onKey);
			q("[data-cancel]").addEventListener("click", () => close([]));
			done.addEventListener("click", () => close(picked.slice()));
			modal.addEventListener("mousedown", (event) => {
				if (event.target === modal) close([]);
			});

			paint();
		});
	}

	function escapeHtml(value) {
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
	}

	const CAMERA_GLYPH =
		'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
		+ '<path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.1-2h8.4l1.1 2h2.2A1.5 1.5 0 0 1 21 8.5v9A1.5'
		+ ' 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z"/><circle cx="12" cy="13" r="3.6"/></svg>';
	const DEVICE_GLYPH =
		'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
		+ '<path d="M12 16V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/>'
		+ '<path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"/></svg>';

	return {
		call, login, logout, money, shortTime, csrfToken, plain, toast,
		mountBranchPicker, datePicker, mountDates, photoPicker,
	};
})();
