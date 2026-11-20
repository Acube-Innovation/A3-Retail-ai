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
# The line that carries the taxable part of a used-device sale.
MARGIN_ITEM = "USED-DEVICE-MARGIN"


def apply_margin_scheme(doc, method=None):
	"""Tax a used device on its margin, not on what the customer pays.

	Rule 32(5): the value of supply is selling price less purchase price, and a
	negative margin is ignored. A phone bought at 20,000 and sold at 25,000 is
	taxed on 5,000.

	**Why the bill carries two lines for one phone.** ERPNext's arithmetic is
	total = taxable + tax, and the margin scheme breaks it: the customer pays
	25,000 while the value of supply is 5,000. Two earlier shapes were tried
	and neither survives. Setting the line's taxable value to the margin is
	undone by ERPNext's own recalculation a moment later. Charging the margin's
	GST as a fixed `Actual` amount is refused outright by india_compliance —
	*"Charge Type is set to Actual. However, this would not compute item taxes,
	and your further reporting will be affected"* — and it is right to refuse,
	because the GST return is built from item-wise tax and an Actual row has
	none.

	What is both legal and reportable is to say plainly what the sale is made
	of: the part that is not taxed, and the part that is.

	    Used iPhone 13          20,000   nil rated   (what we paid)
	    Margin on used device    5,000   18%         (the value of supply)
	                            ------
	                            25,000               what the customer pays

	GSTR-1 then shows a taxable value of 4,237.29 at 18% — the margin, exactly
	as the rule asks — rather than 25,000 at 18% or a made-up effective rate on
	the whole price. The customer's copy shows one line and no tax at all,
	which is the other half of why the shop asked for this.

	A used device may not share a bill with new stock: the split only makes
	sense when every line on the bill is a used device.
	"""
	if doc.doctype not in ("Sales Invoice", "POS Invoice"):
		return

	margin_rows = []
	for row in doc.get("items") or []:
		if not row.meta.has_field("a3_is_margin_scheme"):
			return
		if row.item_code == MARGIN_ITEM:
			continue
		if not row.get("a3_is_margin_scheme"):
			row.a3_is_margin_scheme = frappe.get_cached_value(
				"Item", row.item_code, "a3_is_margin_scheme") or 0
		if row.a3_is_margin_scheme:
			margin_rows.append(row)

	# Nothing second-hand on this bill, so nothing here applies — and in
	# particular the margin line is left alone. Stripping it unconditionally
	# emptied any bill that carried only it.
	if not margin_rows:
		return

	# What this put on the bill last time is rebuilt from scratch, so a second
	# save measures the margin from the price and not from its own answer.
	doc.set("items", [row for row in (doc.get("items") or [])
	                  if row.item_code != MARGIN_ITEM])

	if len(margin_rows) != len(doc.get("items")):
		frappe.throw(
			_("A used device has to be billed on its own. Its GST is charged on "
			  "the margin, and that cannot be worked out on the same bill as "
			  "new stock."),
			title=_("Bill the used device separately"))

	nil = _nil_rated_template(doc.company)
	total_margin = 0.0

	for row in margin_rows:
		qty = flt(row.qty) or 1
		# What the customer pays. Held on the row, because the row's own rate
		# becomes the untaxed part and a re-save must not measure from that.
		gross = flt(row.get("a3_gross_rate")) or flt(row.rate) * qty
		row.a3_gross_rate = gross

		purchase = flt(row.get("a3_purchase_cost")) or _serial_purchase_cost(row)
		row.a3_purchase_cost = purchase

		margin = max(gross - purchase * qty, 0.0)
		row.a3_margin_value = margin
		total_margin += margin

		# The device itself is the part that is not taxed.
		row.rate = (gross - margin) / qty
		row.price_list_rate = gross / qty
		if nil:
			row.item_tax_template = nil
		row.item_tax_rate = "{}"

	if total_margin > 0:
		_append_margin_line(doc, total_margin)

	doc.calculate_taxes_and_totals()


def _nil_rated_template(company: str) -> str | None:
	"""The template that charges nothing, for the part of the price that is
	only what the shop paid for the handset."""
	for title in ("Nil-Rated", "Exempted", "Non-GST"):
		name = frappe.db.get_value("Item Tax Template",
		                           {"company": company, "name": ["like", f"{title}%"]},
		                           "name")
		if name:
			return name
	return None


def _margin_income_account(company: str) -> str | None:
	"""Where the margin is earned. Its own account, because used trading is
	its own trade and the shop wants to read it on its own."""
	return (frappe.db.get_value("Account",
	                            {"company": company,
	                             "account_name": ["like", "%Used Devices%"]}, "name")
	        or frappe.db.get_value("Company", company, "default_income_account"))


def _append_margin_line(doc, margin: float) -> None:
	"""The taxable half of the sale, as its own line."""
	if not frappe.db.exists("Item", MARGIN_ITEM):
		frappe.throw(
			_("The margin line item {0} is missing, so GST on a used device "
			  "cannot be charged. Ask head office to run the setup.")
			.format(MARGIN_ITEM), title=_("Not set up"))

	first = (doc.get("items") or [None])[0]
	line = doc.append("items", {
		"item_code": MARGIN_ITEM,
		"item_name": _("Margin on used device"),
		"description": _("Value of supply under Rule 32(5) — "
		                 "selling price less purchase price"),
		"qty": 1,
		"rate": flt(margin),
		"uom": frappe.db.get_value("Item", MARGIN_ITEM, "stock_uom") or "Nos",
		"conversion_factor": 1,
		# Used trading has an income account of its own, so the margin can be
		# read apart from ordinary sales. The cost centre follows the handset's
		# line, which the branch stamp has already set.
		"income_account": _margin_income_account(doc.company),
		"cost_center": (first.get("cost_center") if first else None)
		               or doc.get("cost_center"),
		# Appended by hand, so nothing fetches this for us — and india_compliance
		# refuses to submit a line without it. The margin is taxed at the rate
		# of the thing it was made on, so it carries the handset's own code.
		"gst_hsn_code": (first.get("gst_hsn_code") if first else None)
		                or frappe.db.get_value("Item", MARGIN_ITEM, "gst_hsn_code"),
	})
	# Not itself a used device: it is the bit that bears the tax.
	if line.meta.has_field("a3_is_margin_scheme"):
		line.a3_is_margin_scheme = 0
	if doc.get("set_warehouse") and line.meta.has_field("warehouse"):
		line.warehouse = None


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
