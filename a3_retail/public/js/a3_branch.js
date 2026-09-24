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

		if (heading) {
			heading.replaceWith(select);
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
	});

	return {
		call, login, logout, money, shortTime, csrfToken, plain, toast,
		mountBranchPicker,
	};
})();
