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
		window.location.href = "/branch";
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

	return { call, login, logout, money, shortTime, csrfToken, plain, toast };
})();
