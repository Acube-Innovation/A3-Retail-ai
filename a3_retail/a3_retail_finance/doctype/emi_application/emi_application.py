# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Application (scope 4.5).

Accounting principle (scope 4.1): the customer is invoiced the **full** amount.
The loan portion is booked to a partner-wise settlement receivable — a current
asset — not to Debtors, and the Financier Settlement clears it later.

Cost fields (subvention, MDR, net realisable) sit at permlevel 1 so a branch user
can process the application without seeing what it costs the shop.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, flt, getdate, now_datetime, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

DRAFT = "Draft"
DOCS_PENDING = "Documents Pending"
READY = "Ready to Submit"
SUBMITTED = "Submitted to Financier"
UNDER_REVIEW = "Under Review"
APPROVED = "Approved"
REJECTED = "Rejected"
DISBURSED = "Disbursed"
SETTLED = "Settled"
CANCELLED = "Cancelled"

# Statuses where the loan is still an open receivable on the financier.
OPEN_RECEIVABLE = (DISBURSED,)

GST_ON_MDR = 18.0


class EMIApplication(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.application_date:
			self.application_date = getdate(nowdate())
		if not self.company:
			profile = get_branch_profile(self.branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.validate_pan()
		self.pull_scheme_terms()
		self.validate_scheme_fit()
		self.compute_loan()
		self.populate_checklist()
		self.refresh_document_state()
		self.advance_status()
		# Also gate on draft saves: a coordinator can type a status straight into
		# the field, and the requirements must hold there too.
		self.validate_status_requirements()

	def before_update_after_submit(self):
		"""Everything after submit — approval, invoicing, settlement — recomputes."""
		self.compute_loan()
		self.refresh_document_state()
		self.validate_status_requirements()

	def before_submit(self):
		self.validate_status_requirements()

	def on_cancel(self):
		self.status = CANCELLED

	# ------------------------------------------------------------------ checks
	def validate_pan(self):
		if self.pan_number:
			self.pan_number = self.pan_number.strip().upper()
			if not PAN_RE.match(self.pan_number):
				frappe.throw(_("{0} is not a valid PAN.").format(self.pan_number))

		if self.aadhaar_last4 and (len(self.aadhaar_last4) != 4 or not self.aadhaar_last4.isdigit()):
			frappe.throw(_("Record only the last four digits of the Aadhaar number."))

	def pull_scheme_terms(self):
		if not self.emi_scheme:
			return

		scheme = frappe.get_cached_doc("EMI Scheme", self.emi_scheme)
		self.tenure_months = scheme.tenure_months
		if not self.finance_partner:
			self.finance_partner = scheme.finance_partner

		if not flt(self.processing_fee):
			if scheme.processing_fee_type == "Percentage":
				self.processing_fee = money(flt(self.invoice_total) * flt(scheme.processing_fee) / 100)
			else:
				self.processing_fee = flt(scheme.processing_fee)

	def validate_scheme_fit(self):
		"""A scheme has a ticket range, a minimum down payment and brand limits."""
		if not self.emi_scheme:
			return

		scheme = frappe.get_cached_doc("EMI Scheme", self.emi_scheme)
		total = flt(self.invoice_total)

		if scheme.finance_partner != self.finance_partner:
			frappe.throw(_("Scheme {0} belongs to {1}.").format(self.emi_scheme, scheme.finance_partner))

		if flt(scheme.min_invoice_amount) and total < flt(scheme.min_invoice_amount):
			frappe.throw(
				_("{0} needs an invoice of at least {1}.").format(
					self.emi_scheme, frappe.format_value(scheme.min_invoice_amount, {"fieldtype": "Currency"})
				)
			)
		if flt(scheme.max_invoice_amount) and total > flt(scheme.max_invoice_amount):
			frappe.throw(
				_("{0} allows an invoice up to {1}.").format(
					self.emi_scheme, frappe.format_value(scheme.max_invoice_amount, {"fieldtype": "Currency"})
				)
			)

		minimum_dp = max(
			flt(scheme.min_down_payment),
			money(total * flt(scheme.down_payment_percent) / 100),
		)
		if flt(self.down_payment) < minimum_dp:
			frappe.throw(
				_("Down payment must be at least {0} for {1}.").format(
					frappe.format_value(minimum_dp, {"fieldtype": "Currency"}), self.emi_scheme
				)
			)

		self.validate_brand_applicability(scheme)

	def validate_brand_applicability(self, scheme):
		brands = {row.brand for row in scheme.get("applicable_brands") or []}
		groups = {row.item_group for row in scheme.get("applicable_item_groups") or []}
		if not brands and not groups:
			return

		for row in self.get("items") or []:
			item = frappe.get_cached_value(
				"Item", row.item_code, ["brand", "item_group"], as_dict=True
			)
			if brands and item.brand not in brands:
				frappe.throw(
					_("{0} does not cover brand {1}.").format(self.emi_scheme, item.brand or "-")
				)
			if groups and item.item_group not in groups:
				frappe.throw(
					_("{0} does not cover item group {1}.").format(self.emi_scheme, item.item_group)
				)

	# ------------------------------------------------------------------- maths
	def compute_loan(self):
		"""loan = invoice - down payment; EMI spreads it over the tenure (scope 4.3)."""
		for row in self.get("items") or []:
			row.amount = money(flt(row.rate) * (flt(row.qty) or 1))

		if not flt(self.invoice_total) and self.get("items"):
			self.invoice_total = money(sum(flt(r.amount) for r in self.items))

		self.loan_amount = money(max(flt(self.invoice_total) - flt(self.down_payment), 0))

		scheme = frappe.get_cached_doc("EMI Scheme", self.emi_scheme) if self.emi_scheme else None
		tenure = cint(self.tenure_months) or (cint(scheme.tenure_months) if scheme else 0)

		self.emi_amount = money(self.compute_emi(flt(self.loan_amount), tenure,
		                                         flt(scheme.interest_rate) if scheme else 0))

		if not self.first_emi_date and self.application_date:
			self.first_emi_date = add_months(getdate(self.application_date), 1)

		self.compute_costs(scheme)

	@staticmethod
	def compute_emi(loan_amount: float, tenure_months: int, annual_rate: float = 0) -> float:
		"""Flat instalment. A no-cost scheme is simply loan / tenure."""
		if not tenure_months or loan_amount <= 0:
			return 0.0

		if not annual_rate:
			return loan_amount / tenure_months

		# Reducing-balance EMI: P*r*(1+r)^n / ((1+r)^n - 1)
		monthly_rate = annual_rate / 12.0 / 100.0
		factor = (1 + monthly_rate) ** tenure_months
		return loan_amount * monthly_rate * factor / (factor - 1)

	def compute_costs(self, scheme):
		"""What the deal actually costs the shop (permlevel 1)."""
		partner = frappe.get_cached_doc("Finance Partner", self.finance_partner) if self.finance_partner else None

		subvention_percent = flt(scheme.subvention_percent) if scheme else 0
		self.merchant_subvention_cost = money(flt(self.loan_amount) * subvention_percent / 100)

		mdr_percent = flt(partner.mdr_percent) if partner else 0
		self.mdr_amount = money(flt(self.loan_amount) * mdr_percent / 100)

		self.net_realisable = money(
			flt(self.loan_amount) - flt(self.mdr_amount) - flt(self.merchant_subvention_cost)
		)

	# -------------------------------------------------------------- checklist
	def populate_checklist(self):
		"""Merge the partner's document list, filtered by employment type (scope 4.5)."""
		if self.get("documents") or not self.finance_partner:
			return

		partner = frappe.get_cached_doc("Finance Partner", self.finance_partner)
		wanted = [row.document_type for row in partner.get("required_documents") or []]

		if not wanted:
			wanted = frappe.get_all(
				"EMI Document Type",
				filters={"applies_to": ["in", ["All", self.employment_type or "All"]]},
				pluck="name",
			)

		for document in wanted:
			meta = frappe.get_cached_doc("EMI Document Type", document)
			if meta.applies_to not in ("All", self.employment_type):
				continue
			self.append(
				"documents",
				{"document_type": document, "is_mandatory": meta.is_mandatory_default},
			)

	def refresh_document_state(self):
		outstanding = [
			row for row in self.get("documents") or []
			if row.is_mandatory and (not row.is_received or not row.attachment)
		]
		self.all_documents_received = 0 if outstanding else 1

	def missing_documents(self) -> list[str]:
		return [
			row.document_type
			for row in self.get("documents") or []
			if row.is_mandatory and (not row.is_received or not row.attachment)
		]

	# ---------------------------------------------------------------- status
	def advance_status(self):
		"""Draft moves itself to Documents Pending / Ready to Submit."""
		if self.status in (DRAFT, DOCS_PENDING, READY):
			self.status = READY if self.all_documents_received else DOCS_PENDING

	def validate_status_requirements(self):
		"""Gate the statuses that carry real consequences (scope 4.5)."""
		if self.status in (READY, SUBMITTED) and not self.all_documents_received:
			frappe.throw(
				_("These mandatory documents are still missing: {0}").format(
					", ".join(self.missing_documents())
				),
				title=_("Documents Incomplete"),
			)

		if self.status == APPROVED:
			for field in ("partner_application_no", "approved_loan_amount", "loan_account_number"):
				if not self.get(field):
					frappe.throw(
						_("{0} is required before marking the application Approved.").format(
							_(self.meta.get_label(field))
						)
					)

		if self.status == REJECTED and not self.rejection_reason:
			frappe.throw(_("Record why the financier rejected the application."))


# ---------------------------------------------------------------------------
# Sales Invoice integration (scope 4.5)
# ---------------------------------------------------------------------------
def validate_emi_payment(doc, method=None):
	"""An EMI payment line needs a matching approved application."""
	if doc.get("is_return"):
		return

	emi_modes = [
		row.mode_of_payment
		for row in doc.get("payments") or []
		if (row.mode_of_payment or "").upper().startswith("EMI")
	]
	if not emi_modes:
		return

	if doc.get("a3_emi_application"):
		_assert_application_usable(doc.a3_emi_application, doc)
		return

	application = _find_application(doc, emi_modes)
	if not application:
		frappe.throw(
			_("This invoice is paid by {0} but has no approved EMI Application.").format(
				", ".join(emi_modes)
			),
			title=_("EMI Application Required"),
		)

	doc.a3_emi_application = application


def _find_application(doc, emi_modes) -> str | None:
	partners = frappe.get_all(
		"Finance Partner", filters={"mode_of_payment": ["in", emi_modes]}, pluck="name"
	)
	if not partners:
		return None

	return frappe.db.get_value(
		"EMI Application",
		{
			"customer": doc.customer,
			"finance_partner": ["in", partners],
			"status": APPROVED,
			"docstatus": 1,
			"sales_invoice": ["in", ["", None]],
		},
		"name",
		order_by="application_date desc",
	)


def _assert_application_usable(application: str, doc):
	status = frappe.db.get_value("EMI Application", application, "status")
	if status not in (APPROVED, DISBURSED):
		frappe.throw(
			_("EMI Application {0} is {1}; only an approved application can be invoiced.").format(
				application, status
			)
		)


def stamp_invoice_on_application(doc, method=None):
	"""On submit, tie the invoice back and move the application to Disbursed."""
	application = doc.get("a3_emi_application")
	if not application or doc.get("is_return"):
		return

	imeis = []
	for row in doc.get("items") or []:
		if row.get("serial_no"):
			imeis.extend(s.strip() for s in str(row.serial_no).split("\n") if s.strip())

	emi = frappe.get_doc("EMI Application", application)
	emi.sales_invoice = doc.name
	emi.disbursement_date = getdate(doc.posting_date)
	emi.status = DISBURSED

	# Copy the IMEIs actually sold onto the application (scope 4.5).
	for index, row in enumerate(emi.get("items") or []):
		if index < len(imeis):
			row.serial_no = imeis[index]

	emi.flags.ignore_permissions = True
	emi.save(ignore_permissions=True)


def unstamp_invoice_on_application(doc, method=None):
	application = doc.get("a3_emi_application")
	if not application:
		return
	if frappe.db.get_value("EMI Application", application, "sales_invoice") != doc.name:
		return

	emi = frappe.get_doc("EMI Application", application)
	emi.sales_invoice = None
	emi.disbursement_date = None
	emi.status = APPROVED
	emi.flags.ignore_permissions = True
	emi.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Scheduler (scope 4.5)
# ---------------------------------------------------------------------------
def nudge_stale_applications():
	"""Daily — chase submissions sitting with the financier, cancel stale approvals."""
	nudge_after = cint(frappe.db.get_single_value("A3 Retail Settings", "emi_followup_after_days")) or 3
	cancel_after = cint(
		frappe.db.get_single_value("A3 Retail Settings", "auto_cancel_approved_after_days")
	) or 7

	pending = frappe.get_all(
		"EMI Application",
		filters={"docstatus": 1, "status": SUBMITTED,
		         "submitted_on": ["<", add_days(nowdate(), -nudge_after)]},
		fields=["name", "coordinator", "customer_name"],
	)
	for row in pending:
		_notify_coordinator(row)

	stale = frappe.get_all(
		"EMI Application",
		filters={"docstatus": 1, "status": APPROVED, "sales_invoice": ["in", ["", None]],
		         "approval_date": ["<", add_days(nowdate(), -cancel_after)]},
		pluck="name",
	)
	for name in stale:
		doc = frappe.get_doc("EMI Application", name)
		doc.status = CANCELLED
		doc.rejection_remarks = _("Auto-cancelled: approved but never invoiced.")
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

	commit_if_not_testing()
	return {"nudged": len(pending), "cancelled": len(stale)}


def _notify_coordinator(row):
	if not row.coordinator:
		return
	user = frappe.db.get_value("Employee", row.coordinator, "user_id")
	if not user:
		return

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"reference_type": "EMI Application",
			"reference_name": row.name,
			"description": _("EMI application {0} for {1} is still with the financier.").format(
				row.name, row.customer_name
			),
		}
	).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Whitelisted helpers
# ---------------------------------------------------------------------------
@frappe.whitelist()
def eligible_schemes(finance_partner: str | None = None, invoice_total: float = 0,
                     brand: str | None = None) -> list[dict]:
	"""Schemes that fit this cart — powers the POS EMI dialog (P6)."""
	from a3_retail.api import require_permission

	require_permission("EMI Scheme", "read")

	filters = {"is_active": 1}
	if finance_partner:
		filters["finance_partner"] = finance_partner

	schemes = frappe.get_all(
		"EMI Scheme",
		filters=filters,
		fields=["name", "scheme_name", "finance_partner", "tenure_months", "is_no_cost_emi",
		        "interest_rate", "processing_fee", "down_payment_percent", "min_down_payment",
		        "min_invoice_amount", "max_invoice_amount"],
	)

	total = flt(invoice_total)
	result = []
	for scheme in schemes:
		if total:
			if flt(scheme.min_invoice_amount) and total < flt(scheme.min_invoice_amount):
				continue
			if flt(scheme.max_invoice_amount) and total > flt(scheme.max_invoice_amount):
				continue

		if brand:
			brands = frappe.get_all("EMI Scheme Brand", filters={"parent": scheme.name}, pluck="brand")
			if brands and brand not in brands:
				continue

		down_payment = max(
			flt(scheme.min_down_payment), money(total * flt(scheme.down_payment_percent) / 100)
		)
		loan = max(total - down_payment, 0)
		scheme["suggested_down_payment"] = down_payment
		scheme["loan_amount"] = money(loan)
		scheme["emi_amount"] = money(
			EMIApplication.compute_emi(loan, cint(scheme.tenure_months), flt(scheme.interest_rate))
		)
		result.append(scheme)

	return result


@frappe.whitelist()
def record_decision(application: str, decision: str, partner_application_no: str | None = None,
                    approved_loan_amount: float | None = None, loan_account_number: str | None = None,
                    rejection_reason: str | None = None, remarks: str | None = None) -> dict:
	"""Record the financier's answer (scope 4.5 workflow)."""
	from a3_retail.api import require_role

	require_role("EMI Coordinator", "Branch Manager", "Accounts Manager")

	doc = frappe.get_doc("EMI Application", application)
	if decision not in (APPROVED, REJECTED):
		frappe.throw(_("Decision must be Approved or Rejected."))

	doc.status = decision
	if decision == APPROVED:
		doc.partner_application_no = partner_application_no or doc.partner_application_no
		doc.approved_loan_amount = flt(approved_loan_amount) or flt(doc.loan_amount)
		doc.loan_account_number = loan_account_number or doc.loan_account_number
		doc.approval_date = getdate(nowdate())
	else:
		doc.rejection_reason = rejection_reason
		doc.rejection_remarks = remarks

	doc.save()
	return {"application": doc.name, "status": doc.status}


@frappe.whitelist()
def submit_to_financier(application: str, partner_application_no: str | None = None) -> dict:
	from a3_retail.api import require_role

	require_role("EMI Coordinator", "Branch Manager")

	doc = frappe.get_doc("EMI Application", application)
	doc.status = SUBMITTED
	doc.submitted_on = now_datetime()
	if partner_application_no:
		doc.partner_application_no = partner_application_no
	doc.save()

	return {"application": doc.name, "status": doc.status}
