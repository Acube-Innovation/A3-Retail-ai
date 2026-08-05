# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Stock Damage Report (scope 6.3).

Approving a report moves the goods into the branch's Damaged warehouse; the
disposition then decides where they go from there:

| Disposition        | Document created                                  |
|--------------------|---------------------------------------------------|
| Scrap              | Material Issue to Stock Damage Written Off        |
| Return to Supplier | Purchase Return (handled outside this document)   |
| Sell as Refurbished| Transfer to Used Devices                          |

Recovery from an employee raises an Additional Salary deduction, so the money
comes back through payroll rather than an untracked adjustment.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code

DRAFT = "Draft"
PENDING = "Pending Approval"
APPROVED = "Approved"
MOVED = "Moved to Damaged"
DISPOSED = "Disposed"
RECOVERED = "Recovered"
REJECTED = "Rejected"

# Scope 6.3 approval matrix.
BRANCH_MANAGER_LIMIT = 2000.0
HEAD_OFFICE_LIMIT = 25000.0


class StockDamageReport(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.report_date:
			self.report_date = getdate(nowdate())
		if not self.company:
			profile = get_branch_profile(self.branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.set_source_warehouse()
		self.compute_totals()
		self.validate_recovery()
		self.set_approval_requirement()

	def before_update_after_submit(self):
		self.compute_totals()
		self.validate_recovery()

	def before_submit(self):
		if not self.get("items"):
			frappe.throw(_("Add at least one damaged item."))
		if self.status == DRAFT:
			self.status = PENDING

	def on_cancel(self):
		self.status = REJECTED

	# ------------------------------------------------------------------ checks
	def set_source_warehouse(self):
		if self.source_warehouse:
			return
		profile = get_branch_profile(self.branch)
		if profile:
			self.source_warehouse = profile.default_warehouse

	def compute_totals(self):
		total_qty = total_value = 0.0
		for row in self.get("items") or []:
			if not row.warehouse:
				row.warehouse = self.source_warehouse
			if not flt(row.valuation_rate):
				row.valuation_rate = _valuation(row.item_code, row.warehouse)
			row.amount = money(flt(row.valuation_rate) * flt(row.qty))
			total_qty += flt(row.qty)
			total_value += flt(row.amount)

		self.total_qty = total_qty
		self.total_value = money(total_value)

	def validate_recovery(self):
		if not self.is_recoverable:
			return

		if flt(self.recovery_amount) > flt(self.total_value) + 0.01:
			frappe.throw(
				_("Recovery of {0} exceeds the damaged value of {1}.").format(
					frappe.format_value(self.recovery_amount, {"fieldtype": "Currency"}),
					frappe.format_value(self.total_value, {"fieldtype": "Currency"}),
				)
			)

		if self.responsibility == "Employee" and not self.responsible_employee:
			frappe.throw(_("Name the employee the loss is recovered from."))
		if self.responsibility in ("Supplier", "Customer") and not self.responsible_party:
			frappe.throw(_("Name the party the loss is recovered from."))

	def set_approval_requirement(self):
		"""Value decides who has to sign (scope 6.3)."""
		self.needs_ho_approval = 1 if flt(self.total_value) > BRANCH_MANAGER_LIMIT else 0

	def required_approver(self) -> str:
		value = flt(self.total_value)
		if value <= BRANCH_MANAGER_LIMIT:
			return "Branch Manager"
		if value <= HEAD_OFFICE_LIMIT:
			return "A3 Retail Admin"
		return "Accounts Manager"

	# -------------------------------------------------------------- processing
	def approve(self, user: str | None = None):
		"""Approve and move the goods into the Damaged warehouse."""
		if self.status not in (PENDING, DRAFT):
			frappe.throw(_("Only a pending report can be approved."))

		self.db_set("approved_by", user or frappe.session.user, update_modified=False)
		self.db_set("status", APPROVED, update_modified=False)
		self.move_to_damaged()
		self.raise_recovery()
		return self

	def move_to_damaged(self) -> str | None:
		if self.stock_entry_transfer:
			return self.stock_entry_transfer

		profile = get_branch_profile(self.branch)
		damaged = profile.damaged_warehouse if profile else None
		if not damaged:
			frappe.throw(_("Branch {0} has no Damaged Goods warehouse.").format(self.branch))

		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Transfer"
		entry.purpose = "Material Transfer"
		entry.company = self.company
		entry.posting_date = getdate(nowdate())
		if entry.meta.has_field("branch"):
			entry.branch = self.branch

		for row in self.get("items") or []:
			rate = flt(row.valuation_rate) or _valuation(row.item_code, row.warehouse)
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty),
					"s_warehouse": row.warehouse or self.source_warehouse,
					"t_warehouse": damaged,
					"serial_no": row.serial_no,
					"basic_rate": rate,
					"allow_zero_valuation_rate": 0 if rate else 1,
				},
			)

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()

		self.db_set("stock_entry_transfer", entry.name, update_modified=False)
		self.db_set("status", MOVED, update_modified=False)
		return entry.name

	def scrap(self) -> str | None:
		"""Write the goods off out of the Damaged warehouse."""
		if self.stock_entry_writeoff:
			return self.stock_entry_writeoff
		if not self.stock_entry_transfer:
			frappe.throw(_("Move the goods to the Damaged warehouse first."))

		profile = get_branch_profile(self.branch)
		damaged = profile.damaged_warehouse if profile else None
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		expense = f"Stock Damage Written Off - {abbr}"

		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Issue"
		entry.purpose = "Material Issue"
		entry.company = self.company
		entry.posting_date = getdate(nowdate())
		if frappe.db.exists("Account", expense):
			entry.expense_account = expense
		if entry.meta.has_field("branch"):
			entry.branch = self.branch

		for row in self.get("items") or []:
			rate = flt(row.valuation_rate) or _valuation(row.item_code, damaged)
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty),
					"s_warehouse": damaged,
					"serial_no": row.serial_no,
					"basic_rate": rate,
					"allow_zero_valuation_rate": 0 if rate else 1,
					"expense_account": expense if frappe.db.exists("Account", expense) else None,
				},
			)

		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()

		self.db_set("stock_entry_writeoff", entry.name, update_modified=False)
		self.db_set("status", DISPOSED, update_modified=False)
		self.db_set("disposal_date", getdate(nowdate()), update_modified=False)
		return entry.name

	def raise_recovery(self) -> str | None:
		"""Recover from an employee through payroll (scope 6.3)."""
		if not self.is_recoverable or not flt(self.recovery_amount):
			return None
		if self.recovery_mode != "Salary Deduction" or not self.responsible_employee:
			return None
		if self.additional_salary:
			return self.additional_salary

		component = _deduction_component(self.company)
		if not component:
			return None

		deduction = frappe.new_doc("Additional Salary")
		deduction.employee = self.responsible_employee
		deduction.company = self.company
		deduction.salary_component = component
		deduction.amount = flt(self.recovery_amount)
		deduction.payroll_date = add_days(nowdate(), 1)
		deduction.overwrite_salary_structure_amount = 0
		deduction.ref_doctype = self.doctype
		deduction.ref_docname = self.name
		deduction.flags.ignore_permissions = True
		try:
			deduction.insert(ignore_permissions=True)
			deduction.submit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: salary deduction for {self.name}")
			return None

		self.db_set("additional_salary", deduction.name, update_modified=False)
		self.db_set("status", RECOVERED, update_modified=False)
		return deduction.name


def _valuation(item_code: str, warehouse: str | None) -> float:
	if not warehouse:
		return 0.0
	return flt(
		frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
	)


def _deduction_component(company: str) -> str | None:
	"""The salary component damage recoveries are booked against."""
	name = "Damage / Loss Recovery"
	if frappe.db.exists("Salary Component", name):
		return name

	abbr = frappe.get_cached_value("Company", company, "abbr")
	account = f"Damage Recovery - {abbr}"

	component = frappe.new_doc("Salary Component")
	component.salary_component = name
	component.type = "Deduction"
	component.salary_component_abbr = "DLR"
	if frappe.db.exists("Account", account):
		component.append("accounts", {"company": company, "account": account})
	component.flags.ignore_permissions = True
	try:
		component.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: damage recovery salary component")
		return None
	return name


# ---------------------------------------------------------------------------
# Whitelisted actions
# ---------------------------------------------------------------------------
@frappe.whitelist()
def approve(damage_report: str) -> dict:
	from a3_retail.api import require_role

	doc = frappe.get_doc("Stock Damage Report", damage_report)
	require_role(doc.required_approver())
	doc.approve()
	return {"damage_report": doc.name, "status": doc.status,
	        "stock_entry": doc.stock_entry_transfer}


@frappe.whitelist()
def scrap(damage_report: str) -> dict:
	from a3_retail.api import require_role

	doc = frappe.get_doc("Stock Damage Report", damage_report)
	require_role(doc.required_approver())
	entry = doc.scrap()
	return {"damage_report": doc.name, "status": doc.status, "stock_entry": entry}


@frappe.whitelist()
def create_from_transfer_discrepancy(stock_request: str, item_code: str, qty: float,
                                     description: str) -> str:
	"""A short or damaged receipt on a transfer raises a damage report (scope 6.2)."""
	from a3_retail.api import require_permission

	require_permission("Stock Damage Report", "create")

	request = frappe.get_doc("Stock Request", stock_request)
	doc = frappe.new_doc("Stock Damage Report")
	doc.branch = request.requesting_branch
	doc.damage_type = "Transit Damage"
	doc.discovered_during = "Inter-branch Transfer Receipt"
	doc.source_warehouse = request.requesting_warehouse
	doc.reference_type = "Stock Request"
	doc.reference_name = stock_request
	doc.responsibility = "Courier / Transporter"
	doc.append(
		"items",
		{"item_code": item_code, "qty": flt(qty), "warehouse": request.requesting_warehouse,
		 "damage_description": description},
	)
	doc.insert()
	return doc.name
