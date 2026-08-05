# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Estimate and its portal approval flow (scope 3.4).

The customer approves from a link like `/approve-estimate/<token>`. Only a hash
of the token is stored, so a database leak cannot be replayed against the portal,
and a token is single-use: once a decision is recorded the estimate leaves
`Sent` and every later attempt is refused.
"""

import hashlib
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, get_url, getdate, now_datetime, nowdate

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.utils import money
from a3_retail.utils.branch import A3BranchMixin
from a3_retail.utils.naming import set_branch_code

TOKEN_BYTES = 24
DECIDED_STATUSES = ("Approved", "Rejected", "Revision Requested", "Expired")


def hash_token(token: str) -> str:
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ServiceEstimate(A3BranchMixin, Document):
	def before_naming(self):
		# Frappe names a document before `before_validate` runs, so the branch has
		# to be resolved here or the series renders as "EST--26-0001".
		self.pull_job_card_details()
		set_branch_code(self)

	def before_validate(self):
		self.pull_job_card_details()
		self.set_branch_defaults()

	def validate(self):
		self.set_defaults()
		self.compute_totals()
		self.validate_dates()

	def before_submit(self):
		if not self.get("parts") and not self.get("labour"):
			frappe.throw(_("An estimate needs at least one part or labour line."))
		self.approval_status = "Sent"

	def on_submit(self):
		self.issue_portal_token()
		self.sync_job_card(st.ESTIMATE_SENT, "Sent")

	def on_cancel(self):
		self.approval_status = "Expired"

	# ------------------------------------------------------------------ helpers
	def pull_job_card_details(self):
		if not self.job_card:
			return

		job = frappe.db.get_value(
			"Service Job Card",
			self.job_card,
			["branch", "branch_code", "customer", "customer_mobile", "device_model", "imei_1"],
			as_dict=True,
		)
		if not job:
			return

		self.branch = self.branch or job.branch
		self.branch_code = self.branch_code or job.branch_code
		self.customer = job.customer
		self.customer_mobile = job.customer_mobile
		self.device_model = job.device_model
		self.imei_1 = job.imei_1

	def set_defaults(self):
		if not self.estimate_date:
			self.estimate_date = getdate(nowdate())
		if not self.valid_till:
			self.valid_till = add_days(self.estimate_date, 3)
		if not self.version_no:
			self.version_no = 1
		if self.terms_template and not self.terms:
			self.terms = frappe.db.get_value("Terms and Conditions", self.terms_template, "terms")

	def validate_dates(self):
		if getdate(self.valid_till) < getdate(self.estimate_date):
			frappe.throw(_("Valid Till cannot be before the estimate date."))

	def compute_totals(self):
		"""Only lines the customer approved count towards the total."""
		for row in self.get("parts") or []:
			row.qty = flt(row.qty) or 1
			row.amount = money(flt(row.rate) * flt(row.qty))
		for row in self.get("labour") or []:
			row.qty = flt(row.qty) or 1
			row.amount = money(flt(row.rate) * flt(row.qty))

		self.parts_total = money(sum(flt(r.amount) for r in self.approved_lines("parts")))
		self.labour_total = money(sum(flt(r.amount) for r in self.approved_lines("labour")))

		self.net_total = money(flt(self.parts_total) + flt(self.labour_total) - flt(self.discount))
		self.tax_amount = money(flt(self.net_total) * 0.18)
		self.grand_total = money(flt(self.net_total) + flt(self.tax_amount))

	def approved_lines(self, table: str):
		"""Mandatory lines plus the optional ones the customer ticked."""
		for row in self.get(table) or []:
			if row.is_optional and not row.is_approved:
				continue
			yield row

	def issue_portal_token(self) -> str:
		"""Generate a token, store only its hash, and build the approval URL."""
		token = secrets.token_urlsafe(TOKEN_BYTES)
		self.db_set("portal_token_hash", hash_token(token), update_modified=False)
		url = f"{get_url()}/approve-estimate/{token}"
		self.db_set("portal_url", url, update_modified=False)
		# The plaintext token exists only here, to be handed to the messaging layer.
		self.flags.portal_token = token
		return token

	def sync_job_card(self, job_status: str | None, estimate_status: str):
		"""Reflect the estimate's state on the job card.

		The target is often two hops away (Under Diagnosis -> Estimate Pending ->
		Estimate Sent), so each intermediate state is applied in turn — that keeps
		the status log a faithful record instead of skipping states.
		"""
		if not self.job_card:
			return

		job = frappe.get_doc("Service Job Card", self.job_card)
		job.service_estimate = self.name
		job.estimate_status = estimate_status
		job.flags.ignore_permissions = True

		if not job_status or job.status == job_status:
			job.save(ignore_permissions=True)
			return

		for hop in st.path_to(job.status, job_status):
			job.status = hop
			job.save(ignore_permissions=True)

	def is_expired(self) -> bool:
		return getdate(self.valid_till) < getdate(nowdate())

	def record_decision(self, decision: str, approver_name: str | None = None,
	                    remarks: str | None = None, ip_address: str | None = None,
	                    optional_items: list | None = None):
		"""Write the customer's decision. Refuses a second decision."""
		if self.approval_status in DECIDED_STATUSES:
			frappe.throw(
				_("This estimate was already {0} and cannot be changed.").format(_(self.approval_status)),
				title=_("Already Decided"),
			)

		if self.is_expired():
			self.db_set("approval_status", "Expired", update_modified=False)
			frappe.throw(_("This estimate expired on {0}.").format(self.valid_till))

		if optional_items is not None:
			self.apply_optional_selection(optional_items)

		self.approval_status = decision
		self.approved_on = now_datetime()
		self.approver_name = approver_name
		self.customer_remarks = remarks
		self.approval_ip = ip_address
		self.compute_totals()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)

		if decision == "Approved":
			self.sync_job_card(st.ESTIMATE_APPROVED, "Approved")
			self.create_sales_order()
		elif decision == "Rejected":
			self.sync_job_card(st.ESTIMATE_REJECTED, "Rejected")
		elif decision == "Revision Requested":
			self.sync_job_card(None, "Revision Requested")

		return self

	def apply_optional_selection(self, selected: list):
		"""Tick/untick optional lines from the portal checkboxes."""
		selected = {str(s) for s in (selected or [])}
		for table in ("parts", "labour"):
			for row in self.get(table) or []:
				if row.is_optional:
					row.is_approved = 1 if row.name in selected else 0

	def create_sales_order(self) -> str | None:
		"""Approved estimate becomes a Maintenance Sales Order (ADR-04)."""
		if self.sales_order:
			return self.sales_order

		lines = list(self.approved_lines("parts")) + list(self.approved_lines("labour"))
		if not lines:
			return None

		job = frappe.get_doc("Service Job Card", self.job_card)
		order = frappe.new_doc("Sales Order")
		order.customer = self.customer
		order.order_type = "Maintenance"
		order.transaction_date = getdate(nowdate())
		order.delivery_date = getdate(job.estimated_delivery_date or add_days(nowdate(), 2))
		order.company = job.company
		order.branch = job.branch
		if order.meta.has_field("a3_service_job_card"):
			order.a3_service_job_card = self.job_card

		for row in lines:
			order.append(
				"items",
				{
					"item_code": row.get("item_code") or row.get("service_item"),
					"qty": flt(row.qty),
					"rate": flt(row.rate),
					"delivery_date": order.delivery_date,
					"warehouse": job.branch and _service_warehouse(job.branch),
				},
			)

		order.flags.ignore_permissions = True
		order.insert(ignore_permissions=True)
		order.submit()

		self.db_set("sales_order", order.name, update_modified=False)
		frappe.db.set_value("Service Job Card", self.job_card, "sales_order", order.name,
		                    update_modified=False)
		return order.name

	def create_revision(self):
		"""Supersede this estimate with a new version (scope 3.4)."""
		revision = frappe.copy_doc(self)
		# copy_doc keeps the source docstatus, so an unreset copy of a submitted
		# estimate would insert as a submission and run before_submit.
		revision.docstatus = 0
		revision.revision_of = self.name
		revision.version_no = (self.version_no or 1) + 1
		revision.approval_status = "Pending"
		revision.approved_on = None
		revision.approver_name = None
		revision.portal_token_hash = None
		revision.portal_url = None
		revision.sales_order = None
		revision.flags.ignore_permissions = True
		revision.insert(ignore_permissions=True)

		self.db_set("approval_status", "Expired", update_modified=False)
		return revision


def _service_warehouse(branch: str) -> str | None:
	return frappe.db.get_value("Branch Profile", {"branch": branch}, "service_warehouse")


def resolve_token(token: str):
	"""Find the estimate a portal token belongs to, or throw."""
	if not token:
		frappe.throw(_("Invalid approval link."), frappe.PermissionError)

	name = frappe.db.get_value("Service Estimate", {"portal_token_hash": hash_token(token)}, "name")
	if not name:
		frappe.throw(_("This approval link is not valid."), frappe.PermissionError)

	return frappe.get_doc("Service Estimate", name)


def expire_stale_estimates():
	"""Daily — mark estimates past their validity as Expired."""
	names = frappe.get_all(
		"Service Estimate",
		filters={"docstatus": 1, "approval_status": ["in", ["Pending", "Sent"]],
		         "valid_till": ["<", nowdate()]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Service Estimate", name, "approval_status", "Expired", update_modified=False)

	frappe.db.commit()
	return len(names)


# ---------------------------------------------------------------------------
# Desk actions
# ---------------------------------------------------------------------------
@frappe.whitelist()
def create_from_job_card(job_card: str) -> str:
	"""Draft an estimate pre-filled from the job card's parts and labour."""
	from a3_retail.api import require_permission

	require_permission("Service Estimate", "create")
	job = frappe.get_doc("Service Job Card", job_card)

	estimate = frappe.new_doc("Service Estimate")
	estimate.job_card = job.name
	estimate.estimate_date = getdate(nowdate())
	estimate.expected_tat_hours = int(
		frappe.db.get_value("Service TAT Policy", job.tat_policy, "tat_hours") or 48
	)

	for row in job.get("parts") or []:
		estimate.append(
			"parts",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"rate": row.rate,
				"availability": "In Stock" if flt(row.available_qty) >= flt(row.qty) else "To Purchase",
			},
		)
	for row in job.get("labour") or []:
		estimate.append(
			"labour",
			{"service_item": row.service_item, "qty": row.qty, "rate": row.rate, "minutes": row.minutes},
		)

	estimate.insert()

	if st.can_transition(job.status, st.ESTIMATE_PENDING):
		job.status = st.ESTIMATE_PENDING
		job.estimate_status = "Pending"
		job.service_estimate = estimate.name
		job.save()

	return estimate.name


@frappe.whitelist()
def record_manual_decision(estimate: str, decision: str, approver_name: str | None = None,
                           remarks: str | None = None) -> dict:
	"""In-person approval captured by the Service Manager (scope 3.4)."""
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Service Estimate", estimate)
	require_permission("Service Estimate", "write", doc)

	doc.approval_channel = "In Person"
	doc.record_decision(decision, approver_name=approver_name, remarks=remarks)
	return {"estimate": doc.name, "status": doc.approval_status, "sales_order": doc.sales_order}


@frappe.whitelist()
def make_revision(estimate: str) -> str:
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Service Estimate", estimate)
	require_permission("Service Estimate", "create", doc)
	return doc.create_revision().name
