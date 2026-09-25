# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Shared helpers for the standalone branch pages."""

import os

import frappe

ASSETS = (
	("css", "a3_branch.css"),
	("js", "a3_branch.js"),
	("js", "a3_pos.js"),
	("js", "a3_purchases.js"),
	("js", "a3_purchase_entry.js"),
	("js", "a3_cashbank.js"),
)


def asset_version() -> str:
	"""A token that changes whenever the app's own CSS or JS changes.

	The branch pages link their stylesheet by path rather than through the
	desk's bundler, so without this a browser can hold a stale — or, if it
	fetched mid-deploy, a half-written — copy and keep showing it after the
	file on disk is fixed. Cheap to compute and cached for the process.
	"""
	if frappe.local.dev_server:
		return _stamp()

	if not hasattr(frappe.local, "a3_asset_version"):
		frappe.local.a3_asset_version = _stamp()
	return frappe.local.a3_asset_version


def require_branch_kind(context, kind: str) -> None:
	"""Turn away a screen this branch has no use for.

	Hiding the menu entry is not enough — the address still works if somebody
	types it, and a repair screen at a shop with no technician would show empty
	panels and refuse every action. Send them back to the dashboard instead.

	`kind` is "sales" or "service", matching the Branch Profile's branch type.
	"""
	allowed = context.me.get("does_sales") if kind == "sales" else context.me.get("does_service")
	if allowed:
		return
	frappe.local.flags.redirect_location = "/retail/dashboard"
	raise frappe.Redirect


def _stamp() -> str:
	newest = 0.0
	for folder, name in ASSETS:
		path = frappe.get_app_path("a3_retail", "public", folder, name)
		if os.path.exists(path):
			newest = max(newest, os.path.getmtime(path))
	return str(int(newest))
