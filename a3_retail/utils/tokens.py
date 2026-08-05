# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Signed portal links (scope 13.1).

A customer opening /warranty/<token> is not logged in, so the link itself has to
carry the proof. Rather than storing a row per link, the token is the document
name plus an HMAC of it: `WR-26-00001.9f2c…`. Nothing to clean up, nothing to
leak, and a rotated site key invalidates every outstanding link at once.

Links that must be single-use — the estimate approval — keep their stored hash
instead; this module is for the read-mostly pages.
"""

import hashlib
import hmac

import frappe

SEPARATOR = "."
SIGNATURE_LENGTH = 32


def _secret() -> str:
	return (
		frappe.local.conf.get("encryption_key")
		or frappe.local.conf.get("secret")
		or frappe.local.site
	)


def _signature(doctype: str, name: str, purpose: str) -> str:
	payload = f"{doctype}|{name}|{purpose}".encode()
	return hmac.new(_secret().encode(), payload, hashlib.sha256).hexdigest()[:SIGNATURE_LENGTH]


def sign(doctype: str, name: str, purpose: str = "portal") -> str:
	return f"{name}{SEPARATOR}{_signature(doctype, name, purpose)}"


def verify(token: str, doctype: str, purpose: str = "portal") -> str | None:
	"""Return the document name when the signature matches, else None."""
	if not token or SEPARATOR not in token:
		return None

	name, _, signature = token.rpartition(SEPARATOR)
	if not name or not signature:
		return None

	if not hmac.compare_digest(signature, _signature(doctype, name, purpose)):
		return None
	if not frappe.db.exists(doctype, name):
		return None
	return name


def portal_url(doctype: str, name: str, route: str, purpose: str = "portal") -> str:
	from frappe.utils import get_url

	return f"{get_url().rstrip('/')}/{route.strip('/')}/{sign(doctype, name, purpose)}"
