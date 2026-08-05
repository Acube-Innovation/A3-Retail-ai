# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Shared hooks for core transaction doctypes.

Two jobs:

1. Stamp the Branch accounting dimension (and cost center) on every financial
   document, so branch-wise P&L works without users remembering to pick one
   (scope 1.1, 11.1).
2. Margin scheme for used devices under Rule 32(5) — GST is charged on
   (selling price - purchase price), not on the full selling price (scope 11.2).
"""

import frappe
from frappe import _
from frappe.utils import flt

from a3_retail.utils.branch import get_branch_profile, get_user_branch

# Doctypes that carry the Branch dimension.
BRANCH_STAMPED_DOCTYPES = (
	"Sales Invoice",
	"POS Invoice",
	"Purchase Invoice",
	"Journal Entry",
	"Payment Entry",
	"Stock Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Sales Order",
	"Purchase Order",
	"Material Request",
	"Stock Reconciliation",
	"Expense Claim",
)


def stamp_branch(doc, method=None):
	"""Set `branch` (the accounting dimension) and cost center where blank."""
	if doc.doctype not in BRANCH_STAMPED_DOCTYPES:
		return

	branch = doc.get("branch")
	if not branch:
		branch = _resolve_branch(doc)
		if branch and doc.meta.has_field("branch"):
			doc.branch = branch

	if not branch:
		return

	profile = get_branch_profile(branch)
	if not profile:
		return

	# Cost center: prefer the sales/service split so "is my service centre
	# profitable?" stays answerable (scope 11.1).
	cost_center = _pick_cost_center(doc, profile)
	if cost_center:
		if doc.meta.has_field("cost_center") and not doc.get("cost_center"):
			doc.cost_center = cost_center
		for row in doc.get("items", []) or []:
			if row.meta.has_field("cost_center") and not row.get("cost_center"):
				row.cost_center = cost_center

	# Child rows carry the dimension too, so GL entries inherit it.
	for table in ("items", "taxes", "accounts", "references"):
		for row in doc.get(table) or []:
			if row.meta.has_field("branch") and not row.get("branch"):
				row.branch = branch


def _resolve_branch(doc) -> str | None:
	"""Branch from the POS profile, the warehouse, or the session user."""
	if doc.get("pos_profile"):
		branch = frappe.db.get_value("POS Profile", doc.pos_profile, "custom_branch")
		if branch:
			return branch

	for fieldname in ("set_warehouse", "from_warehouse", "to_warehouse"):
		warehouse = doc.get(fieldname)
		if warehouse:
			branch = frappe.db.get_value("Warehouse", warehouse, "custom_branch")
			if branch:
				return branch

	for row in doc.get("items", []) or []:
		warehouse = row.get("warehouse") or row.get("s_warehouse") or row.get("t_warehouse")
		if warehouse:
			branch = frappe.db.get_value("Warehouse", warehouse, "custom_branch")
			if branch:
				return branch

	return get_user_branch()


def _pick_cost_center(doc, profile) -> str | None:
	"""Service documents post to the branch's Service cost center."""
	if doc.doctype in ("Sales Invoice", "POS Invoice", "Sales Order"):
		if doc.get("order_type") == "Maintenance" or doc.get("a3_service_job_card"):
			return profile.service_cost_center or profile.cost_center
		return profile.sales_cost_center or profile.cost_center
	return profile.cost_center


# ---------------------------------------------------------------------------
# Margin scheme — Rule 32(5)
# ---------------------------------------------------------------------------
def apply_margin_scheme(doc, method=None):
	"""Tax margin-scheme lines on (sale - purchase) instead of the full rate.

	ERPNext computes tax from `net_amount`, so for these lines we set the taxable
	base to the margin while leaving `rate`/`amount` (what the customer actually
	pays) untouched. A non-positive margin attracts no GST and cannot be set off
	against another sale.
	"""
	if doc.doctype not in ("Sales Invoice", "POS Invoice"):
		return

	touched = False
	for row in doc.get("items", []) or []:
		if not row.meta.has_field("a3_is_margin_scheme"):
			continue

		if not row.get("a3_is_margin_scheme"):
			row.a3_is_margin_scheme = frappe.get_cached_value("Item", row.item_code, "a3_is_margin_scheme") or 0

		if not row.a3_is_margin_scheme:
			continue

		purchase_cost = flt(row.get("a3_purchase_cost")) or _serial_purchase_cost(row)
		row.a3_purchase_cost = purchase_cost

		margin = flt(row.amount) - flt(purchase_cost) * flt(row.qty or 1)
		row.a3_margin_value = max(margin, 0)

		# Taxable value is the margin (never negative).
		row.net_amount = row.a3_margin_value
		row.net_rate = flt(row.a3_margin_value) / flt(row.qty or 1)
		touched = True

	if touched:
		# Recompute the tax block against the adjusted net amounts.
		doc.calculate_taxes_and_totals()


def _serial_purchase_cost(row) -> float:
	"""Purchase cost of the specific device being resold."""
	serials = (row.get("serial_no") or "").split("\n")
	serials = [s.strip() for s in serials if s.strip()]
	if not serials:
		return 0.0

	cost = frappe.db.get_value("Serial No", serials[0], "a3_purchase_cost")
	return flt(cost)


def validate_margin_scheme_lines(doc, method=None):
	"""A margin-scheme line without a purchase cost would be taxed on the full value."""
	for row in doc.get("items", []) or []:
		if row.get("a3_is_margin_scheme") and not flt(row.get("a3_purchase_cost")):
			frappe.throw(
				_(
					"Row {0}: {1} is under the margin scheme but has no purchase cost, "
					"so GST cannot be computed on the margin."
				).format(row.idx, row.item_code)
			)
