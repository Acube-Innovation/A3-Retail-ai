# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Shared helpers for the standalone branch pages."""

import os

import frappe

ASSETS = (
	("css", "a3_branch.css"),
	("js", "a3_branch.js"),
	("js", "a3_pos.js"),
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


def _stamp() -> str:
	newest = 0.0
	for folder, name in ASSETS:
		path = frappe.get_app_path("a3_retail", "public", folder, name)
		if os.path.exists(path):
			newest = max(newest, os.path.getmtime(path))
	return str(int(newest))
