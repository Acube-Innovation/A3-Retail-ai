# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Cash and bank for one branch (`/retail/cashbank`).

What is in the drawer, what is in each bank account, and every rupee that moved
either way — the question a shop asks at closing time.

Everything here is narrowed to the branch's own cost centres. The company's bank
balance is a head-office number; a counter that could see it would be reading
six other shops' takings, and would have no way to tell which part was its own.
Cash and bank GL entries carry the branch cost centre because the counter's
invoices and expenses set it, so the narrowing is exact rather than a guess.

Nothing here writes a ledger entry by hand: a deposit is a Journal Entry, the
same document an accountant would raise.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _branch_cost_centres(branch: str) -> list[str]:
	"""Every cost centre this branch books to."""
	profile = frappe.db.get_value(
		"Branch Profile", {"branch": branch},
		["cost_center", "sales_cost_center", "service_cost_center"], as_dict=True
	) or frappe._dict()
	centres = {profile.cost_center, profile.sales_cost_center, profile.service_cost_center}
	centres.discard(None)
	return list(centres)


def _accounts(company: str) -> list[dict]:
	return frappe.db.sql(
		"""
		select name, account_name, account_type
		from `tabAccount`
		where company = %(company)s and is_group = 0 and disabled = 0
		  and account_type in ('Cash', 'Bank')
		order by account_type desc, account_name
		""",
		{"company": company}, as_dict=True,
	)


@frappe.whitelist()
def summary() -> dict:
	"""What this branch holds, in the drawer and at the bank."""
	employee = _me()
	centres = _branch_cost_centres(employee.branch)
	accounts = _accounts(_company())
	if not centres or not accounts:
		return {"branch": employee.branch, "cash": [], "banks": [],
		        "cash_total": 0.0, "bank_total": 0.0, "total": 0.0}

	balances = {
		row.account: flt(row.balance)
		for row in frappe.db.sql(
			"""
			select account, sum(debit) - sum(credit) as balance
			from `tabGL Entry`
			where is_cancelled = 0 and cost_center in %(centres)s
			group by account
			""",
			{"centres": centres}, as_dict=True,
		)
	}

	cash, banks = [], []
	for row in accounts:
		entry = {"account": row.name, "label": row.account_name,
		         "balance": flt(balances.get(row.name, 0.0))}
		(cash if row.account_type == "Cash" else banks).append(entry)

	cash_total = sum(row["balance"] for row in cash)
	bank_total = sum(row["balance"] for row in banks)
	return {
		"branch": employee.branch,
		"cash": cash,
		"banks": banks,
		"cash_total": cash_total,
		"bank_total": bank_total,
		"total": cash_total + bank_total,
		"as_of": nowdate(),
	}


@frappe.whitelist()
def transactions(limit: int = 40, account: str | None = None) -> dict:
	"""Money in and money out, newest first."""
	employee = _me()
	centres = _branch_cost_centres(employee.branch)
	if not centres:
		return {"branch": employee.branch, "rows": []}

	conditions = ["gle.is_cancelled = 0", "gle.cost_center in %(centres)s",
	              "acc.account_type in ('Cash', 'Bank')"]
	values = {"centres": centres, "limit": min(cint(limit) or 40, 200)}
	if account:
		conditions.append("gle.account = %(account)s")
		values["account"] = account

	rows = frappe.db.sql(
		f"""
		select gle.posting_date, gle.account, acc.account_name, acc.account_type,
		       gle.debit, gle.credit, gle.voucher_type, gle.voucher_no,
		       gle.against, gle.remarks
		from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		where {" and ".join(conditions)}
		order by gle.posting_date desc, gle.creation desc
		limit %(limit)s
		""",
		values, as_dict=True,
	)

	for row in rows:
		row["debit"] = flt(row["debit"])
		row["credit"] = flt(row["credit"])
		row["direction"] = "in" if row["debit"] > 0 else "out"
		row["amount"] = row["debit"] or row["credit"]
	return {"branch": employee.branch, "rows": rows}


@frappe.whitelist()
def deposit(payload) -> dict:
	"""Take the day's cash to the bank.

	Both sides carry the branch cost centre so the drawer and the account stay
	answerable to the shop that banked the money.
	"""
	employee = _me()
	require_permission("Journal Entry", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	amount = flt(data.get("amount"))
	if amount <= 0:
		frappe.throw(_("Enter how much was banked."), title=_("Amount"))

	company = _company()
	source = (data.get("from_account") or "").strip()
	target = (data.get("to_account") or "").strip()
	for account in (source, target):
		if not account or not frappe.db.exists("Account", account):
			frappe.throw(_("Choose the drawer it came from and the account it went into."),
			             title=_("Accounts"))
		if frappe.db.get_value("Account", account, "company") != company:
			frappe.throw(_("{0} does not belong to this company.").format(account))
	if source == target:
		frappe.throw(_("Money cannot move to the place it came from."), title=_("Accounts"))

	centres = _branch_cost_centres(employee.branch)
	available = _available(source, centres)
	if amount > available + 0.005:
		frappe.throw(
			_("This branch only has {0} in {1}.").format(
				frappe.format_value(available, {"fieldtype": "Currency"}),
				frappe.db.get_value("Account", source, "account_name")),
			title=_("Not that much"),
		)

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A deposit cannot be dated in the future."), title=_("Date"))

	profile = frappe.db.get_value(
		"Branch Profile", {"branch": employee.branch},
		["cost_center", "sales_cost_center"], as_dict=True) or frappe._dict()
	cost_center = profile.sales_cost_center or profile.cost_center

	doc = frappe.new_doc("Journal Entry")
	doc.voucher_type = "Bank Entry"
	doc.company = company
	doc.posting_date = posting
	doc.user_remark = (data.get("note") or _("Cash banked")) + \
		f" — {employee.employee_name}, {employee.branch}"
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch

	doc.append("accounts", {"account": target, "debit_in_account_currency": amount,
	                        "cost_center": cost_center})
	doc.append("accounts", {"account": source, "credit_in_account_currency": amount,
	                        "cost_center": cost_center})

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	return {
		"entry": doc.name,
		"amount": amount,
		"from": frappe.db.get_value("Account", source, "account_name"),
		"to": frappe.db.get_value("Account", target, "account_name"),
		"date": str(posting),
	}


def _available(account: str, centres: list[str]) -> float:
	if not centres:
		return 0.0
	balance = frappe.db.sql(
		"""
		select sum(debit) - sum(credit) from `tabGL Entry`
		where is_cancelled = 0 and account = %(account)s and cost_center in %(centres)s
		""",
		{"account": account, "centres": centres},
	)[0][0]
	return flt(balance)
