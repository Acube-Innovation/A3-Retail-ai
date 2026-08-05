# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stock Request — branch-to-branch transfer (scope 6.2).

ERPNext's Material Request could do this, but the shop needs a lightweight
approval object that the Stock Explorer, POS and a job card can raise in one
click. This document orchestrates; the actual movement is two standard Stock
Entries using ERPNext's in-transit pattern:

    Source Store -> Goods In Transit   (Add to Transit)
    Goods In Transit -> Target Store   (End Transit)

Serial numbers ride through both entries, so a device's IMEI history stays
intact across the transfer.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate, now_datetime, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code

DRAFT = "Draft"
PENDING = "Pending Approval"
APPROVED = "Approved"
REJECTED = "Rejected"
PARTIAL = "Partially Dispatched"
IN_TRANSIT = "In Transit"
RECEIVED = "Received"
CANCELLED = "Cancelled"

MANAGER_ROLES = ("Branch Manager", "Store Keeper", "A3 Retail Admin", "System Manager")


class StockRequest(A3BranchMixin, Document):
	def before_naming(self):
		self.branch = self.requesting_branch
		set_branch_code(self)

	def before_validate(self):
		if not self.request_date:
			self.request_date = now_datetime()
		if not self.company:
			profile = get_branch_profile(self.requesting_branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.validate_branches()
		self.set_warehouses()
		self.compute_items()
		self.set_approval_requirement()

	def before_update_after_submit(self):
		self.compute_items()

	def before_submit(self):
		if not self.get("items"):
			frappe.throw(_("Add at least one item to transfer."))
		if self.status == DRAFT:
			self.status = APPROVED if self.auto_approves() else PENDING

	def on_cancel(self):
		self.status = CANCELLED

	# ------------------------------------------------------------------ checks
	def validate_branches(self):
		if self.requesting_branch == self.source_branch:
			frappe.throw(_("A branch cannot request stock from itself."))

	def set_warehouses(self):
		requesting = get_branch_profile(self.requesting_branch)
		source = get_branch_profile(self.source_branch)

		if not self.requesting_warehouse and requesting:
			# A job card's parts land in the Service Bay, everything else in the store.
			self.requesting_warehouse = (
				requesting.service_warehouse
				if self.purpose == "Service Job Card" and requesting.service_warehouse
				else requesting.default_warehouse
			)
		if not self.source_warehouse and source:
			# Spare parts sit in the Service Bay, devices in the store — so pick
			# the source branch's warehouse that actually holds the goods rather
			# than always defaulting to the store.
			self.source_warehouse = self._best_source_warehouse(source)

		if not self.transit_warehouse:
			self.transit_warehouse = (
				(requesting.transit_warehouse if requesting else None)
				or frappe.db.get_single_value("A3 Retail Settings", "transit_warehouse")
				or frappe.db.get_value(
					"Warehouse", {"company": self.company, "warehouse_type": "Transit"}, "name"
				)
			)

	def _best_source_warehouse(self, profile) -> str | None:
		candidates = [
			profile.default_warehouse,
			profile.service_warehouse,
			profile.used_device_warehouse,
		]
		candidates = [w for w in candidates if w]
		if not candidates or not self.get("items"):
			return candidates[0] if candidates else None

		item_codes = [row.item_code for row in self.items if row.item_code]
		best, best_qty = candidates[0], -1.0
		for warehouse in candidates:
			qty = sum(_bin_qty(code, warehouse) for code in item_codes)
			if qty > best_qty:
				best, best_qty = warehouse, qty

		return best

	def compute_items(self):
		total = 0.0
		for row in self.get("items") or []:
			row.available_at_source = _bin_qty(row.item_code, self.source_warehouse)
			if not flt(row.rate):
				row.rate = _valuation(row.item_code, self.source_warehouse)
			total += flt(row.rate) * flt(row.qty)

		self.total_value = money(total)

	def set_approval_requirement(self):
		"""Scope 6.2 approval matrix, driven by value and purpose."""
		auto_limit = flt(
			frappe.db.get_single_value("A3 Retail Settings", "stock_request_auto_approve_limit")
		) or 10000
		ho_limit = flt(
			frappe.db.get_single_value("A3 Retail Settings", "stock_request_ho_approval_limit")
		) or 25000

		self.needs_ho_approval = 1 if flt(self.total_value) > ho_limit else 0
		self._auto_limit = auto_limit

	def auto_approves(self) -> bool:
		"""A small service-parts request does not need a manager to sign off."""
		limit = getattr(self, "_auto_limit", 10000)
		return self.purpose == "Service Job Card" and flt(self.total_value) <= flt(limit)

	# --------------------------------------------------------------- movement
	def approve(self, user: str | None = None):
		if self.status not in (PENDING, DRAFT):
			frappe.throw(_("Only a pending request can be approved."))

		self.db_set("status", APPROVED, update_modified=False)
		self.db_set("approved_by", user or frappe.session.user, update_modified=False)
		self.db_set("approved_on", now_datetime(), update_modified=False)
		return self

	def reject(self, reason: str):
		if self.status not in (PENDING, DRAFT):
			frappe.throw(_("Only a pending request can be rejected."))
		self.db_set("status", REJECTED, update_modified=False)
		self.db_set("rejection_reason", reason, update_modified=False)
		return self

	def dispatch(self) -> str:
		"""Source Store -> Goods In Transit (ERPNext 'Add to Transit')."""
		if self.status != APPROVED:
			frappe.throw(_("Approve the request before dispatching."))
		if self.outward_stock_entry:
			return self.outward_stock_entry

		if not self.transit_warehouse:
			frappe.throw(_("No Goods In Transit warehouse is configured."))

		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Transfer"
		entry.purpose = "Material Transfer"
		entry.company = self.company
		entry.posting_date = getdate(nowdate())
		entry.from_warehouse = self.source_warehouse
		entry.to_warehouse = self.transit_warehouse
		if entry.meta.has_field("add_to_transit"):
			entry.add_to_transit = 1
		if entry.meta.has_field("branch"):
			entry.branch = self.source_branch

		for row in self.get("items") or []:
			# State the valuation explicitly on both legs: a transfer must not
			# depend on ERPNext resolving a rate for the transit warehouse.
			rate = flt(row.rate) or _valuation(row.item_code, self.source_warehouse)
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty),
					"s_warehouse": self.source_warehouse,
					"t_warehouse": self.transit_warehouse,
					"serial_no": row.serial_no,
					"basic_rate": rate,
					"allow_zero_valuation_rate": 0 if rate else 1,
				},
			)

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()

		self.db_set("outward_stock_entry", entry.name, update_modified=False)
		self.db_set("dispatched_on", now_datetime(), update_modified=False)
		self.db_set("status", IN_TRANSIT, update_modified=False)

		for row in self.get("items") or []:
			row.db_set("dispatched_qty", flt(row.qty), update_modified=False)

		self._sync_job_card_parts("Awaiting Transfer")
		return entry.name

	def receive(self) -> str:
		"""Goods In Transit -> requesting warehouse (ERPNext 'End Transit')."""
		if self.inward_stock_entry:
			return self.inward_stock_entry
		if self.status != IN_TRANSIT:
			frappe.throw(_("Only a request in transit can be received."))

		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Transfer"
		entry.purpose = "Material Transfer"
		entry.company = self.company
		entry.posting_date = getdate(nowdate())
		entry.from_warehouse = self.transit_warehouse
		entry.to_warehouse = self.requesting_warehouse
		if entry.meta.has_field("outgoing_stock_entry"):
			entry.outgoing_stock_entry = self.outward_stock_entry
		if entry.meta.has_field("branch"):
			entry.branch = self.requesting_branch

		for row in self.get("items") or []:
			# The transit warehouse's own valuation is not always resolvable on
			# the inward leg, so carry the outward rate across explicitly.
			rate = flt(row.rate) or _valuation(row.item_code, self.transit_warehouse)
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty),
					"s_warehouse": self.transit_warehouse,
					"t_warehouse": self.requesting_warehouse,
					"serial_no": row.serial_no,
					"basic_rate": rate,
					"allow_zero_valuation_rate": 0 if rate else 1,
				},
			)

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()

		self.db_set("inward_stock_entry", entry.name, update_modified=False)
		self.db_set("received_on", now_datetime(), update_modified=False)
		self.db_set("status", RECEIVED, update_modified=False)
		self.db_set(
			"transit_days",
			date_diff(nowdate(), getdate(self.dispatched_on)) if self.dispatched_on else 0,
			update_modified=False,
		)

		for row in self.get("items") or []:
			row.db_set("received_qty", flt(row.qty), update_modified=False)

		self._sync_job_card_parts("Received")
		return entry.name

	def _sync_job_card_parts(self, part_status: str):
		"""Keep the job card's part rows in step with the transfer."""
		if not self.reference_job_card:
			return

		items = {row.item_code for row in self.get("items") or []}
		job = frappe.get_doc("Service Job Card", self.reference_job_card)
		for row in job.get("parts") or []:
			if row.item_code in items and row.stock_request == self.name:
				row.db_set("part_status", part_status, update_modified=False)

		if part_status == "Received":
			from a3_retail.a3_retail_service.parts import resume_if_parts_ready

			resume_if_parts_ready(self.reference_job_card)


def _bin_qty(item_code: str, warehouse: str | None) -> float:
	if not warehouse:
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


def _valuation(item_code: str, warehouse: str | None) -> float:
	if not warehouse:
		return 0.0
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
	)


# ---------------------------------------------------------------------------
# Whitelisted actions
# ---------------------------------------------------------------------------
@frappe.whitelist()
def approve(stock_request: str) -> dict:
	from a3_retail.api import require_role

	require_role(*MANAGER_ROLES)
	doc = frappe.get_doc("Stock Request", stock_request)
	doc.approve()
	return {"stock_request": doc.name, "status": doc.status}


@frappe.whitelist()
def reject(stock_request: str, reason: str) -> dict:
	from a3_retail.api import require_role

	require_role(*MANAGER_ROLES)
	doc = frappe.get_doc("Stock Request", stock_request)
	doc.reject(reason)
	return {"stock_request": doc.name, "status": doc.status}


@frappe.whitelist()
def dispatch(stock_request: str) -> dict:
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Stock Request", stock_request)
	require_permission("Stock Request", "write", doc)
	require_permission("Stock Entry", "create")
	entry = doc.dispatch()
	return {"stock_request": doc.name, "status": doc.status, "stock_entry": entry}


@frappe.whitelist()
def receive(stock_request: str) -> dict:
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Stock Request", stock_request)
	require_permission("Stock Request", "write", doc)
	require_permission("Stock Entry", "create")
	entry = doc.receive()
	return {"stock_request": doc.name, "status": doc.status, "stock_entry": entry}


@frappe.whitelist()
def create_from_explorer(item_code: str, qty: float, source_branch: str,
                         to_branch: str | None = None, purpose: str = "Stock Balancing",
                         job_card: str | None = None) -> str:
	"""One-click transfer request from the Stock Explorer (scope 6.1)."""
	from a3_retail.api import require_permission
	from a3_retail.utils.branch import get_user_branch

	require_permission("Stock Request", "create")

	doc = frappe.new_doc("Stock Request")
	doc.requesting_branch = to_branch or get_user_branch()
	doc.source_branch = source_branch
	doc.purpose = purpose
	doc.reference_job_card = job_card
	doc.append("items", {"item_code": item_code, "qty": flt(qty)})
	doc.insert()
	doc.submit()

	return doc.name


def flag_stuck_transfers():
	"""Weekly — surface transfers that have been in transit too long."""
	rows = frappe.get_all(
		"Stock Request",
		filters={"docstatus": 1, "status": IN_TRANSIT, "dispatched_on": ["is", "set"]},
		fields=["name", "dispatched_on", "requesting_branch"],
	)
	stuck = []
	for row in rows:
		days = date_diff(nowdate(), getdate(row.dispatched_on))
		frappe.db.set_value("Stock Request", row.name, "transit_days", days, update_modified=False)
		if days > 5:
			stuck.append(row.name)

	commit_if_not_testing()
	return stuck
