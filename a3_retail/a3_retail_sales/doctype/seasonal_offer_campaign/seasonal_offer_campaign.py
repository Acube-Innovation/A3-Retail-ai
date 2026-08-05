# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Seasonal Offer Campaign (scope 2.3, ADR-05).

The campaign is the client-facing wrapper. On submit it generates standard
ERPNext `Pricing Rule` documents, so POS, Sales Order and Sales Invoice all
apply the offer through ERPNext's own pricing engine — nothing here re-implements
discounting.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing, money

DRAFT = "Draft"
PENDING = "Pending Approval"
SCHEDULED = "Scheduled"
ACTIVE = "Active"
PAUSED = "Paused"
EXPIRED = "Expired"
CANCELLED = "Cancelled"

LIVE_STATUSES = (SCHEDULED, ACTIVE)


class SeasonalOfferCampaign(Document):
	def validate(self):
		self.validate_dates()
		self.validate_scope()
		self.validate_benefit()
		if not self.company:
			self.company = frappe.db.get_single_value("Global Defaults", "default_company")

	def before_submit(self):
		if self.requires_approval and not self.approved_by:
			self.status = PENDING
		else:
			self.status = self.status_for_dates()

	def on_submit(self):
		if self.status in LIVE_STATUSES:
			self.generate_pricing_rules()

	def on_cancel(self):
		self.remove_pricing_rules()
		self.status = CANCELLED

	# ------------------------------------------------------------------ checks
	def validate_dates(self):
		if getdate(self.valid_upto) < getdate(self.valid_from):
			frappe.throw(_("Valid Upto must be on or after Valid From."))

	def validate_scope(self):
		if self.apply_on == "Entire Catalogue":
			return
		if not self.get("items"):
			frappe.throw(_("Add at least one row under Applicable Items, or apply to the entire catalogue."))

		field = {"Item Code": "item_code", "Item Group": "item_group", "Brand": "brand"}[self.apply_on]
		for row in self.items:
			if not row.get(field):
				frappe.throw(_("Row {0}: {1} is required when applying on {2}.").format(
					row.idx, _(field.replace("_", " ").title()), _(self.apply_on)
				))

	def validate_benefit(self):
		if flt(self.discount_percentage) > 100:
			frappe.throw(_("A discount cannot exceed 100%."))
		if self.rate_or_discount == "Discount Percentage" and not flt(self.discount_percentage):
			if self.offer_type in ("Flat Percentage",):
				frappe.throw(_("Enter the discount percentage."))

	def status_for_dates(self) -> str:
		today = getdate(nowdate())
		if getdate(self.valid_from) > today:
			return SCHEDULED
		if getdate(self.valid_upto) < today:
			return EXPIRED
		return ACTIVE

	# ------------------------------------------------------- pricing rules
	def branch_warehouses(self) -> list[str]:
		"""Warehouses the offer applies to; empty means every branch."""
		branches = [row.branch for row in self.get("applicable_branches") or [] if row.is_included]
		if not branches:
			return []

		return frappe.get_all(
			"Warehouse",
			filters={"custom_branch": ["in", branches], "is_group": 0, "disabled": 0},
			pluck="name",
		)

	def generate_pricing_rules(self):
		"""One Pricing Rule per applicability row (scope 2.3)."""
		self.remove_pricing_rules()

		rows = list(self.get("items") or [])
		if self.apply_on == "Entire Catalogue":
			rows = [frappe._dict({"idx": 1})]

		warehouses = self.branch_warehouses()
		generated = []

		for index, row in enumerate(rows, start=1):
			# ERPNext's Pricing Rule is per-warehouse; a campaign covering three
			# branches therefore produces one rule per branch warehouse.
			targets = warehouses or [None]
			for warehouse in targets:
				rule = self._build_rule(row, index, warehouse)
				if rule:
					generated.append((row, rule))

		self.set("generated_rules", [])
		for row, rule in generated:
			self.append(
				"generated_rules",
				{
					"item_code": row.get("item_code"),
					"item_group": row.get("item_group"),
					"brand": row.get("brand"),
					"pricing_rule": rule,
				},
			)
			if row.get("name"):
				frappe.db.set_value("Offer Item Rule", row.name, "pricing_rule", rule,
				                    update_modified=False)

		self.db_update_child_table()
		return [rule for _row, rule in generated]

	def db_update_child_table(self):
		for row in self.get("generated_rules") or []:
			row.parent = self.name
			row.parenttype = self.doctype
			row.parentfield = "generated_rules"
			row.db_insert() if not row.get("creation") else row.db_update()

	def _build_rule(self, row, index: int, warehouse: str | None) -> str | None:
		title = f"{self.campaign_name}-{index}" + (f"-{warehouse.split(' - ')[0]}" if warehouse else "")
		title = title[:140]

		if frappe.db.exists("Pricing Rule", {"title": title}):
			return None

		rule = frappe.new_doc("Pricing Rule")
		rule.title = title
		rule.selling = 1
		rule.company = self.company
		rule.valid_from = self.valid_from
		rule.valid_upto = self.valid_upto
		rule.priority = str(self.priority or 1)
		rule.apply_multiple_pricing_rules = 1 if self.is_cumulative else 0
		rule.warehouse = warehouse
		rule.currency = frappe.get_cached_value("Company", self.company, "default_currency")

		if self.customer_group:
			rule.applicable_for = "Customer Group"
			rule.customer_group = self.customer_group

		if self.apply_on == "Entire Catalogue":
			rule.apply_rule_on_other = None
			rule.apply_on = "Item Group"
			rule.append("item_groups", {"item_group": _root_item_group()})
		elif self.apply_on == "Item Code":
			rule.apply_on = "Item Code"
			rule.append("items", {"item_code": row.item_code, "uom": row.get("uom")})
		elif self.apply_on == "Item Group":
			rule.apply_on = "Item Group"
			rule.append("item_groups", {"item_group": row.item_group})
		else:
			rule.apply_on = "Brand"
			rule.append("brands", {"brand": row.brand})

		rule.min_qty = flt(row.get("min_qty") or self.min_qty)
		rule.max_qty = flt(self.max_qty)
		rule.min_amt = flt(self.min_amount)
		rule.max_amt = flt(self.max_amount)

		self._apply_benefit(rule, row)

		rule.flags.ignore_permissions = True
		try:
			rule.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: pricing rule for {self.name}")
			return None
		return rule.name

	def _apply_benefit(self, rule, row):
		if self.offer_type == "Buy X Get Y" and self.free_item:
			rule.price_or_product_discount = "Product"
			rule.free_item = self.free_item
			rule.free_qty = flt(self.free_qty) or 1
			return

		rule.price_or_product_discount = "Price"
		special_rate = flt(row.get("special_rate") or self.special_rate)
		discount_amount = flt(row.get("discount_amount") or self.discount_amount)
		discount_percent = flt(row.get("discount_percentage") or self.discount_percentage)

		if self.rate_or_discount == "Rate" or special_rate:
			rule.rate_or_discount = "Rate"
			rule.rate = special_rate
		elif self.rate_or_discount == "Discount Amount" or (discount_amount and not discount_percent):
			rule.rate_or_discount = "Discount Amount"
			rule.discount_amount = discount_amount
		else:
			rule.rate_or_discount = "Discount Percentage"
			rule.discount_percentage = discount_percent
			# The cap is what stops an 8% offer giving away 8% of a flagship.
			if flt(self.max_discount_amount):
				rule.has_priority = 1

	def remove_pricing_rules(self):
		for row in self.get("generated_rules") or []:
			if row.pricing_rule and frappe.db.exists("Pricing Rule", row.pricing_rule):
				frappe.delete_doc("Pricing Rule", row.pricing_rule, force=1, ignore_permissions=True)
		self.set("generated_rules", [])
		frappe.db.delete("Offer Item Rule", {"parent": self.name, "parentfield": "generated_rules"})

	def disable_pricing_rules(self, disabled: bool = True):
		for row in self.get("generated_rules") or []:
			if row.pricing_rule and frappe.db.exists("Pricing Rule", row.pricing_rule):
				frappe.db.set_value("Pricing Rule", row.pricing_rule, "disable", 1 if disabled else 0,
				                    update_modified=False)

	# ------------------------------------------------------------------ budget
	def consume(self, amount: float):
		"""Book discount given away; pause the campaign once the cap is hit."""
		consumed = money(flt(self.consumed_amount) + flt(amount))
		self.db_set("consumed_amount", consumed, update_modified=False)

		if flt(self.budget_cap) and consumed >= flt(self.budget_cap) and self.status == ACTIVE:
			self.db_set("status", PAUSED, update_modified=False)
			self.disable_pricing_rules(True)
			frappe.msgprint(
				_("Campaign {0} has used its budget and was paused.").format(self.name), alert=True
			)


def _root_item_group() -> str:
	return frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name") or "All Item Groups"


# ---------------------------------------------------------------------------
# Hooks and scheduler
# ---------------------------------------------------------------------------
def track_offer_consumption(doc, method=None):
	"""Sales Invoice on_submit — add the discount given to each campaign's budget."""
	if doc.get("is_return"):
		return

	per_rule: dict[str, float] = {}
	for row in doc.get("items") or []:
		rules = row.get("pricing_rules")
		if not rules:
			continue
		try:
			names = frappe.parse_json(rules)
		except Exception:
			names = [rules]

		saved = (flt(row.price_list_rate) - flt(row.rate)) * flt(row.qty)
		if saved <= 0:
			continue
		for name in names or []:
			per_rule[name] = per_rule.get(name, 0) + saved

	for rule_name, amount in per_rule.items():
		campaign = frappe.db.get_value(
			"Offer Item Rule", {"pricing_rule": rule_name, "parentfield": "generated_rules"}, "parent"
		)
		if not campaign:
			continue
		frappe.get_doc("Seasonal Offer Campaign", campaign).consume(amount)


def refresh_campaign_statuses():
	"""Daily — activate scheduled campaigns and expire finished ones (scope 2.3)."""
	today = getdate(nowdate())
	activated = expired = 0

	for name in frappe.get_all(
		"Seasonal Offer Campaign",
		filters={"docstatus": 1, "status": SCHEDULED, "valid_from": ["<=", today]},
		pluck="name",
	):
		doc = frappe.get_doc("Seasonal Offer Campaign", name)
		doc.db_set("status", ACTIVE, update_modified=False)
		doc.disable_pricing_rules(False)
		activated += 1

	for name in frappe.get_all(
		"Seasonal Offer Campaign",
		filters={"docstatus": 1, "status": ["in", [ACTIVE, PAUSED]], "valid_upto": ["<", today]},
		pluck="name",
	):
		doc = frappe.get_doc("Seasonal Offer Campaign", name)
		doc.db_set("status", EXPIRED, update_modified=False)
		doc.disable_pricing_rules(True)
		expired += 1

	commit_if_not_testing()
	return {"activated": activated, "expired": expired}


@frappe.whitelist()
def approve(campaign: str) -> dict:
	"""Head-office approval moves a campaign from Pending to Scheduled/Active."""
	from a3_retail.api import require_role

	require_role("A3 Retail Admin")

	doc = frappe.get_doc("Seasonal Offer Campaign", campaign)
	if doc.status != PENDING:
		frappe.throw(_("Only a campaign pending approval can be approved."))

	doc.db_set("approved_by", frappe.session.user, update_modified=False)
	doc.db_set("status", doc.status_for_dates(), update_modified=False)
	doc.reload()
	doc.generate_pricing_rules()

	return {"campaign": doc.name, "status": doc.status}


@frappe.whitelist()
def pause(campaign: str) -> dict:
	from a3_retail.api import require_role

	require_role("A3 Retail Admin", "Branch Manager")

	doc = frappe.get_doc("Seasonal Offer Campaign", campaign)
	doc.db_set("status", PAUSED, update_modified=False)
	doc.disable_pricing_rules(True)
	return {"campaign": doc.name, "status": PAUSED}


@frappe.whitelist()
def active_exchange_bonus(branch: str | None = None) -> float:
	"""Exchange bonus offered by any live campaign — used by Device Exchange."""
	today = getdate(nowdate())
	rows = frappe.get_all(
		"Seasonal Offer Campaign",
		filters={
			"docstatus": 1,
			"status": ACTIVE,
			"offer_type": "Exchange Bonus",
			"valid_from": ["<=", today],
			"valid_upto": [">=", today],
		},
		fields=["name", "exchange_bonus"],
	)
	return max([flt(r.exchange_bonus) for r in rows], default=0.0)
