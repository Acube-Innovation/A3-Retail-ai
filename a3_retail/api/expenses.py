# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch petty cash (`/retail/expenses`).

The shop records around sixty of these a month — tea, water, transport, an AC
service — and until now had to ask head office to enter every one. This is the
counter's own screen for them.

A category is an expense Account under the company's indirect expenses, so the
spend lands in the P&L where the accountant expects it. The posting itself is a
Journal Entry: debit the category, credit whatever it was paid from. Nothing here
writes a ledger entry by hand.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

EXPENSE_PARENT_HINTS = ("Indirect Expenses", "Expenses")


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _abbr(company):
	return frappe.get_cached_value("Company", company, "abbr")


def _expense_parent(company):
	"""The group account new categories are filed under."""
	abbr = _abbr(company)
	for hint in EXPENSE_PARENT_HINTS:
		name = f"{hint} - {abbr}"
		if frappe.db.exists("Account", name):
			return name
	return frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "root_type": "Expense"}, "name"
	)


@frappe.whitelist()
def categories() -> list[dict]:
	"""What the spend can be filed under."""
	employee = _me()
	company = _company()
	parent = _expense_parent(company)
	if not parent:
		return []

	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "root_type": "Expense",
		         "disabled": 0, "lft": [">", frappe.db.get_value("Account", parent, "lft")],
		         "rgt": ["<", frappe.db.get_value("Account", parent, "rgt")]},
		fields=["name", "account_name"],
		order_by="account_name",
	)
	return [{"account": r.name, "label": r.account_name} for r in rows]


@frappe.whitelist()
def paid_from() -> list[dict]:
	"""The drawer, or a bank account the branch actually pays from."""
	_me()
	company = _company()
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0,
		         "account_type": ["in", ["Cash", "Bank"]]},
		fields=["name", "account_name", "account_type"],
		order_by="account_type desc, account_name",
	)
	return [{"account": r.name, "label": r.account_name, "kind": r.account_type} for r in rows]


def _branch_cost_centres(branch: str) -> list[str]:
	"""Every cost centre this branch books to, including its group."""
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": branch},
		["cost_center", "sales_cost_center", "service_cost_center"], as_dict=True
	) or frappe._dict()
	centres = {profile.cost_center, profile.sales_cost_center, profile.service_cost_center}
	centres.discard(None)
	return list(centres)


@frappe.whitelist()
def recent(limit: int = 40) -> dict:
	"""This branch's spend, newest first, with what it adds up to this month."""
	employee = _me()
	require_permission("Journal Entry", "read")

	# Journal Entry carries no branch field — the Branch dimension does not reach
	# it — so the branch is read from the cost centre the spend was booked to.
	centres = _branch_cost_centres(employee.branch)
	if not centres:
		return {"branch": employee.branch, "rows": [], "month_total": 0.0}

	rows = frappe.db.sql(
		"""
		select je.name, je.posting_date, je.total_debit as amount, je.user_remark,
		       je.docstatus,
		       (select gle.account from `tabJournal Entry Account` gle
		         where gle.parent = je.name and gle.debit_in_account_currency > 0
		         limit 1) as category
		from `tabJournal Entry` je
		where je.docstatus < 2 and ifnull(je.a3_is_branch_expense, 0) = 1
		  and exists (select 1 from `tabJournal Entry Account` c
		              where c.parent = je.name and c.cost_center in %(centres)s)
		order by je.posting_date desc, je.creation desc
		limit %(limit)s
		""",
		{"centres": centres, "limit": int(limit) or 40},
		as_dict=True,
	)
	for r in rows:
		r["category_label"] = frappe.db.get_value("Account", r["category"], "account_name") \
			if r.get("category") else ""
		r["amount"] = flt(r["amount"])

	month = frappe.db.sql(
		"""
		select coalesce(sum(je.total_debit), 0) from `tabJournal Entry` je
		where je.docstatus = 1 and ifnull(je.a3_is_branch_expense, 0) = 1
		  and month(je.posting_date) = month(curdate())
		  and year(je.posting_date) = year(curdate())
		  and exists (select 1 from `tabJournal Entry Account` c
		              where c.parent = je.name and c.cost_center in %(centres)s)
		""",
		{"centres": centres},
	)[0][0]

	return {"branch": employee.branch, "rows": rows, "month_total": flt(month)}


@frappe.whitelist()
def create(payload) -> dict:
	"""Record a spend. Debit the category, credit what it was paid from."""
	employee = _me()
	require_permission("Journal Entry", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	amount = flt(data.get("amount"))
	if amount <= 0:
		frappe.throw(_("Enter how much was spent."), title=_("Amount"))

	category = (data.get("category") or "").strip()
	if not category or not frappe.db.exists("Account", category):
		frappe.throw(_("Choose what this was spent on."), title=_("Category"))

	source = (data.get("paid_from") or "").strip()
	if not source or not frappe.db.exists("Account", source):
		frappe.throw(_("Choose where the money came from."), title=_("Paid from"))

	company = _company()
	for account in (category, source):
		if frappe.db.get_value("Account", account, "company") != company:
			frappe.throw(_("{0} does not belong to this company.").format(account))

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("An expense cannot be dated in the future."), title=_("Date"))

	profile = frappe.db.get_value(
		"Branch Profile", {"branch": employee.branch},
		["cost_center", "sales_cost_center"], as_dict=True
	) or frappe._dict()
	cost_center = profile.sales_cost_center or profile.cost_center

	note = (data.get("note") or "").strip()
	remark = note or frappe.db.get_value("Account", category, "account_name")

	doc = frappe.new_doc("Journal Entry")
	doc.voucher_type = "Journal Entry"
	doc.company = company
	doc.posting_date = posting
	doc.user_remark = f"{remark} — {employee.employee_name}, {employee.branch}"
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	if doc.meta.has_field("a3_is_branch_expense"):
		doc.a3_is_branch_expense = 1

	doc.append("accounts", {"account": category, "debit_in_account_currency": amount,
	                        "cost_center": cost_center})
	doc.append("accounts", {"account": source, "credit_in_account_currency": amount,
	                        "cost_center": cost_center})

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	return {
		"expense": doc.name,
		"amount": amount,
		"category": frappe.db.get_value("Account", category, "account_name"),
		"paid_from": frappe.db.get_value("Account", source, "account_name"),
		"date": str(posting),
	}


@frappe.whitelist()
def add_category(label: str) -> dict:
	"""A shop has its own words for what it spends on — let it add one.

	Restricted to managers: an account is chart-of-accounts furniture, and a
	counter inventing one per week leaves the accountant with forty ways to say
	tea.
	"""
	from a3_retail.api import require_role

	_me()
	require_role("Branch Manager", "Service Manager")

	label = (label or "").strip()
	if not label:
		frappe.throw(_("Give the category a name."))

	company = _company()
	abbr = _abbr(company)
	full = f"{label} - {abbr}"
	if frappe.db.exists("Account", full):
		return {"account": full, "label": label, "created": False}

	parent = _expense_parent(company)
	if not parent:
		frappe.throw(_("This company has no expenses group to file it under."))

	acc = frappe.new_doc("Account")
	acc.account_name = label
	acc.parent_account = parent
	acc.company = company
	acc.is_group = 0
	acc.root_type = "Expense"
	acc.account_type = "Expense Account"
	acc.flags.ignore_permissions = True
	acc.insert(ignore_permissions=True)
	return {"account": acc.name, "label": label, "created": True}
