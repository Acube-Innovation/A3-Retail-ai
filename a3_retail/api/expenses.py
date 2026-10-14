# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch petty cash (`/retail/expenses`).

The shop records around sixty of these a month — tea, water, transport, an AC
service — and until now had to ask head office to enter every one. This is the
counter's own screen for them.

A category is an expense Account under the company's indirect expenses, so the
spend lands in the P&L where the accountant expects it. The spend itself is a
Branch Expense — what was bought, how many, at what rate, who it went to and what
is still owed — and submitting one posts the Journal Entry: debit each line,
credit whatever it was paid from. Nothing here writes a ledger entry by hand.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.utils import tax
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
def bootstrap() -> dict:
	"""Everything the Create Expense page needs before the first keystroke."""
	_me()
	return {
		"categories": categories(),
		"sources": paid_from(),
		"modes": modes(),
		"can_add_category": can_add_category(),
		"series": next_number(),
	}


@frappe.whitelist()
def next_number() -> dict:
	"""The prefix and the number this expense will get.

	Shown the way the old software showed them, in two boxes. They are not typed
	into: the number has to be the next one and has to be unique, so it is read
	rather than chosen.
	"""
	employee = _me()
	from a3_retail.utils.branch import get_branch_code

	code = get_branch_code(employee.branch) or "HO"
	year = frappe.utils.nowdate()[2:4]
	prefix = f"EXP-{code}-{year}-"
	last = frappe.db.sql(
		"""select name from `tabBranch Expense`
		   where name like %(like)s order by name desc limit 1""",
		{"like": prefix + "%"})
	nxt = (int(last[0][0].rsplit("-", 1)[1]) + 1) if last else 1
	return {"prefix": prefix, "number": f"{nxt:05d}"}


@frappe.whitelist()
def can_add_category() -> bool:
	"""Whether this person may invent a category, so the screen can say so."""
	_me()
	return bool({"Branch Manager", "Service Manager", "System Manager",
	             "A3 Retail Admin"} & set(frappe.get_roles()))


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
	require_permission("Branch Expense", "read")

	rows = frappe.get_all(
		"Branch Expense",
		filters={"branch": employee.branch, "docstatus": ["<", 2]},
		fields=["name", "posting_date", "category", "grand_total as amount",
		        "paid_to", "supplier", "notes", "outstanding_amount", "docstatus"],
		order_by="posting_date desc, creation desc",
		limit=int(limit) or 40,
	)
	for r in rows:
		r["category_label"] = frappe.db.get_value("Account", r["category"], "account_name") \
			if r.get("category") else ""
		r["paid_to_label"] = r.get("paid_to") or (
			frappe.db.get_value("Supplier", r["supplier"], "supplier_name")
			if r.get("supplier") else "")
		r["amount"] = flt(r["amount"])

	month = frappe.db.sql(
		"""
		select coalesce(sum(grand_total), 0) from `tabBranch Expense`
		where docstatus = 1 and branch = %(branch)s
		  and month(posting_date) = month(curdate())
		  and year(posting_date) = year(curdate())
		""",
		{"branch": employee.branch},
	)[0][0]

	return {"branch": employee.branch, "rows": rows, "month_total": flt(month)}


@frappe.whitelist()
def create(payload) -> dict:
	"""Record a spend. The document works out the posting."""
	employee = _me()
	require_permission("Branch Expense", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})

	lines = [row for row in (data.get("items") or [])
	         if flt(row.get("rate")) or flt(row.get("qty"))]
	if not lines:
		frappe.throw(_("Add what the money went on."), title=_("Nothing to record"))

	doc = frappe.new_doc("Branch Expense")
	doc.branch = employee.branch
	doc.posting_date = getdate(data.get("date") or nowdate())
	doc.category = (data.get("category") or "").strip()
	doc.reference_no = (data.get("reference_no") or "").strip() or None
	doc.supplier = (data.get("supplier") or "").strip() or None
	doc.paid_to = (data.get("paid_to") or "").strip() or None
	doc.due_date = getdate(data["due_date"]) if data.get("due_date") else None
	doc.mode_of_payment = (data.get("mode_of_payment") or "").strip() or None
	doc.paid_from = (data.get("paid_from") or "").strip() or None
	doc.with_gst = 1 if data.get("with_gst") else 0
	doc.discount_amount = flt(data.get("discount"))
	doc.notes = (data.get("note") or "").strip() or None

	for row in lines:
		doc.append("items", {
			"item_code": (row.get("item_code") or "").strip() or None,
			"description": (row.get("description") or "").strip() or None,
			"qty": flt(row.get("qty")) or 1,
			"rate": flt(row.get("rate")),
			"gst_rate": flt(row.get("gst_rate")),
		})

	# Blank means it was all paid, which is what a shop means unless it says so.
	if data.get("paid_amount") not in (None, ""):
		doc.paid_amount = flt(data.get("paid_amount"))

	# A balance has to be owed to somebody: ERPNext keeps payables against a
	# party, and a typed name cannot hold one. Rather than refuse the entry over
	# a record the counter has no way to create, make the supplier from the name
	# they gave — which is what their old software did with a contact.
	if doc.paid_to and not doc.supplier and _owes(doc):
		doc.supplier = _supplier_named(doc.paid_to)
		doc.paid_to = None

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	return {
		"expense": doc.name,
		"amount": flt(doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		"category": frappe.db.get_value("Account", doc.category, "account_name"),
		"date": str(doc.posting_date),
	}


def _owes(doc) -> bool:
	"""Whether this expense will leave something unpaid."""
	total = sum(flt(row.get("qty") or 1) * flt(row.get("rate")) for row in doc.items)
	grand = flt(total - flt(doc.discount_amount))
	paid = grand if doc.paid_amount is None else flt(doc.paid_amount)
	return flt(grand - paid) > 0


def _supplier_named(name: str) -> str:
	"""The supplier by that name, made if this is the first time it is owed money."""
	existing = frappe.db.get_value("Supplier", {"supplier_name": name}, "name")
	if existing:
		return existing
	doc = frappe.new_doc("Supplier")
	doc.supplier_name = name
	doc.supplier_group = frappe.db.get_value(
		"Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def search_items(query: str = "", limit: int = 20) -> list[dict]:
	"""The things a shop buys that are not stock — tea, a service call, a sheet.

	Serialised handsets and accessories are bought on a purchase bill, not here,
	so this only ever offers what carries no stock.
	"""
	_me()
	like = f"%{(query or '').strip()}%"
	rows = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_stock_item": 0},
		or_filters={"item_name": ["like", like], "item_code": ["like", like]},
		fields=["name as item_code", "item_name", "item_group", "stock_uom",
		        "gst_hsn_code as hsn", "valuation_rate as rate"],
		order_by="item_name",
		limit=int(limit) or 20,
	)
	for r in rows:
		r["expense_account"] = frappe.db.get_value(
			"Item Default", {"parent": r["item_code"]}, "expense_account")
		r["gst_rate"] = tax.item_rate(r["item_code"])
	return rows


@frappe.whitelist()
def create_item(payload) -> dict:
	"""Add something the shop buys but does not stock."""
	_me()
	require_permission("Item", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	name = (data.get("item_name") or "").strip()
	if not name:
		frappe.throw(_("Give it a name."), title=_("Item name"))

	existing = frappe.db.get_value("Item", {"item_name": name, "is_stock_item": 0}, "name")
	if existing:
		return {"item_code": existing, "item_name": name, "created": False}

	doc = frappe.new_doc("Item")
	doc.item_code = name
	doc.item_name = name
	doc.item_group = _expense_item_group()
	doc.stock_uom = (data.get("uom") or "Nos").strip() or "Nos"
	doc.is_stock_item = 0
	# Bought, never sold: it has no business turning up in the till's search.
	doc.is_purchase_item = 1
	doc.is_sales_item = 0
	account = (data.get("expense_account") or "").strip()
	if account and frappe.db.exists("Account", account):
		doc.append("item_defaults", {
			"company": _company(), "expense_account": account})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return {"item_code": doc.name, "item_name": doc.item_name, "created": True}


def _expense_item_group() -> str:
	"""Where bought-not-sold things live, made once if it is not there yet."""
	name = "Expense Items"
	if frappe.db.exists("Item Group", name):
		return name
	parent = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""},
	                             "name") or "All Item Groups"
	group = frappe.new_doc("Item Group")
	group.item_group_name = name
	group.parent_item_group = parent
	group.is_group = 0
	group.flags.ignore_permissions = True
	group.insert(ignore_permissions=True)
	return group.name


@frappe.whitelist()
def modes() -> list[str]:
	"""How the money left the drawer."""
	_me()
	return frappe.get_all("Mode of Payment", filters={"enabled": 1}, pluck="name",
	                      order_by="name")


@frappe.whitelist()
def search_suppliers(query: str = "", limit: int = 10) -> list[dict]:
	"""Who it was paid to, when that is somebody already on file."""
	_me()
	like = f"%{(query or '').strip()}%"
	return frappe.get_all(
		"Supplier", filters={"disabled": 0},
		or_filters={"supplier_name": ["like", like], "name": ["like", like]},
		fields=["name", "supplier_name"], order_by="supplier_name",
		limit=int(limit) or 10)


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
