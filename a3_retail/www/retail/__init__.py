# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Shared helpers for the standalone branch pages."""

import os

import frappe

# Scanned rather than listed. This was a hand-kept tuple of eight files, and the
# thirteen scripts nobody remembered to add to it — the stock page, customers,
# suppliers, bills, EMI and the rest — never moved the stamp when they changed.
# A browser then kept the old copy indefinitely and the change simply never
# arrived, which is a miserable thing to debug from the shop floor.
ASSET_FOLDERS = (("css", ".css"), ("js", ".js"))


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
	for folder, suffix in ASSET_FOLDERS:
		root = frappe.get_app_path("a3_retail", "public", folder)
		if not os.path.isdir(root):
			continue
		for name in os.listdir(root):
			if name.endswith(suffix):
				newest = max(newest, os.path.getmtime(os.path.join(root, name)))
	return str(int(newest))
