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
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import date_window, require_permission
from a3_retail.utils import tax
from a3_retail.api.staff import _me

EXPENSE_PARENT_HINTS = ("Indirect Expenses", "Expenses")

# Accounts that are expenses to an accountant but not a spend to a shopkeeper:
# what the goods sold cost, a stock write-down, the rounding on an invoice.
# Counted in, every sale of the day would turn up on the expense list.
NOT_A_SPEND = ("Cost of Goods Sold", "Stock Adjustment",
               "Stock Received But Not Billed", "Expenses Included In Valuation",
               "Round Off")

# A branch spends three ways and all three end up in the same ledger: a journal
# straight to the books (which is what this screen writes), an employee paying
# out of their own pocket, or a supplier's bill settled later. The list names
# which route a row came in by, so it reads as one spend book rather than three.
SPEND_KIND = {
	"Journal Entry": "Journal",
	"Expense Claim": "Employee",
	"Purchase Invoice": "Supplier bill",
}

# The rates GST actually comes in, so the form offers a list rather than a box.
GST_RATES = [0, 0.25, 3, 5, 12, 18, 28]

# Whether the input credit on this spend can be claimed. The wording is the
# department's; the reasons matter at return time.
ITC_OPTIONS = [
	{"value": "eligible", "label": "Eligible"},
	{"value": "ineligible_17_5", "label": "Ineligible — Section 17(5)"},
	{"value": "ineligible_other", "label": "Ineligible — other"},
]


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
		"can_create_item": bool(frappe.has_permission("Item", "create")),
		"series": next_number(),
		"uoms": frappe.get_all("UOM", filters={"enabled": 1}, pluck="name",
		                       order_by="name", limit_page_length=0),
		"gst_rates": GST_RATES,
		"itc_options": ITC_OPTIONS,
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
	"""Whether this person may invent a category, so the screen can say so.

	Anyone who records a spend here may add one. It was managers only, on the
	reasoning that a counter inventing a category a week leaves the accountant
	with forty ways to say tea — but the shop asked for it, and a spend filed
	under the wrong heading because the right one could not be made is worse
	than a long list.
	"""
	_me()
	return bool(frappe.has_permission("Branch Expense", "create"))


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


def _responsible_branch(cost_center: str | None) -> str:
	"""The branch whose P&L actually carries this spend.

	Read off the cost centre, not the `branch` stamp on the ledger line: that
	stamp follows whoever happened to be signed in when the entry posted, and on
	this site two entries already disagree with the books because of it. The
	cost centre is what the P&L is cut by, so the cost centre is what is true.
	"""
	if not cost_center:
		return ""
	return frappe.get_cached_value("Cost Center", cost_center, "custom_branch") or ""


def _things(labels: list[str], shown: int = 3) -> str:
	"""The first few things bought, then a count of the rest.

	A bill can run to thirty lines and the column is one line tall, so the
	point is to say enough for the entry to be recognised, not to list it.
	"""
	labels = [str(label).strip() for label in labels if label and str(label).strip()]
	if not labels:
		return ""
	rest = len(labels) - shown
	return ", ".join(labels[:shown]) + (f" +{rest} more" if rest > 0 else "")


def _line_label(row) -> str:
	"""One bought thing, with its count when more than one was bought."""
	# `item_name` first: a Purchase Invoice line carries the catalogue
	# description, which runs to several lines and would swamp the column. A
	# Branch Expense line has no item name, so it falls through to what the
	# counter typed.
	name = row.get("item_name") or row.get("description") or row.get("item_code") or ""
	qty = flt(row.get("qty"))
	return f"{name} x{qty:g}" if qty > 1 else name


def _account_label(account: str | None) -> str:
	return frappe.get_cached_value("Account", account, "account_name") if account else ""


def _journal_spend(voucher_no: str) -> dict:
	"""A journal: either one of this screen's own, or one posted in the office."""
	ours = frappe.db.get_value(
		"Branch Expense", {"journal_entry": voucher_no, "docstatus": 1},
		["name", "category", "supplier", "paid_to", "notes", "outstanding_amount"],
		as_dict=True)
	if not ours:
		# Somebody booked this straight into the books. A journal has no item
		# lines, so the accounts it debited are the best description there is.
		entry = frappe.db.get_value(
			"Journal Entry", voucher_no, ["user_remark", "title"], as_dict=True
		) or frappe._dict()
		accounts = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": voucher_no, "debit_in_account_currency": (">", 0)},
			pluck="account")
		return {"ref": voucher_no,
		        "category_label": _account_label(accounts[0] if accounts else None),
		        "items": _things([_account_label(a) for a in accounts]),
		        "paid_to_label": "",
		        "notes": entry.user_remark or entry.title or "",
		        "outstanding_amount": 0.0}

	lines = frappe.get_all("Branch Expense Item", filters={"parent": ours.name},
	                       fields=["item_code", "description", "qty"], order_by="idx")
	return {"ref": ours.name,
	        "category_label": _account_label(ours.category),
	        "items": _things([_line_label(r) for r in lines]),
	        "paid_to_label": ours.paid_to or (
	            frappe.get_cached_value("Supplier", ours.supplier, "supplier_name")
	            if ours.supplier else ""),
	        "notes": ours.notes or "",
	        "outstanding_amount": flt(ours.outstanding_amount)}


def _claim_spend(voucher_no: str) -> dict:
	"""An employee paid out of their own pocket and is owed it back."""
	claim = frappe.db.get_value(
		"Expense Claim", voucher_no,
		["employee_name", "remark", "grand_total", "total_amount_reimbursed"],
		as_dict=True) or frappe._dict()
	lines = frappe.get_all("Expense Claim Detail", filters={"parent": voucher_no},
	                       fields=["expense_type", "description"], order_by="idx")
	return {"ref": voucher_no,
	        "category_label": lines[0].expense_type if lines else "",
	        "items": _things([r.description or r.expense_type for r in lines]),
	        "paid_to_label": claim.employee_name or "",
	        "notes": claim.remark or "",
	        "outstanding_amount": flt(claim.grand_total) - flt(claim.total_amount_reimbursed)}


def _bill_spend(voucher_no: str) -> dict:
	"""A supplier's bill, whatever has since been paid against it."""
	bill = frappe.db.get_value(
		"Purchase Invoice", voucher_no,
		["supplier_name", "remarks", "outstanding_amount", "bill_no"],
		as_dict=True) or frappe._dict()
	lines = frappe.get_all(
		"Purchase Invoice Item", filters={"parent": voucher_no},
		fields=["item_name", "description", "qty", "expense_account"], order_by="idx")
	return {"ref": voucher_no,
	        "category_label": _account_label(lines[0].expense_account) if lines else "",
	        "items": _things([_line_label(r) for r in lines]),
	        "paid_to_label": bill.supplier_name or "",
	        "notes": bill.bill_no or bill.remarks or "",
	        "outstanding_amount": flt(bill.outstanding_amount)}


SPEND_DETAIL = {
	"Journal Entry": _journal_spend,
	"Expense Claim": _claim_spend,
	"Purchase Invoice": _bill_spend,
}


@frappe.whitelist()
def recent(limit: int = 40, filters=None) -> dict:
	"""This branch's spend, newest first, by whichever route it was recorded.

	A spend reaches the books three ways — a journal, an employee's claim, a
	supplier's bill — and a shopkeeper asking what the branch spent last week
	means all three. So the list is read off the ledger rather than off this
	screen's own documents: anything that debited an expense account against one
	of the branch's cost centres belongs here, whoever entered it and wherever.
	"""
	employee = _me()
	require_permission("Branch Expense", "read")

	centres = _branch_cost_centres(employee.branch)
	if not centres:
		return {"branch": employee.branch, "rows": [], "month_total": 0.0}

	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	window = date_window(data, "gl.posting_date", {})
	narrowed = {}
	for key in ("from_date", "to_date"):
		if data.get(key):
			narrowed[key] = getdate(data[key])

	# Grouped by voucher: one bill is one line here however many accounts it
	# touched, and the cost centre comes along to name who carries it.
	spend = frappe.db.sql(
		"""
		select gl.voucher_type, gl.voucher_no, gl.posting_date,
		       max(gl.cost_center) as cost_center,
		       sum(gl.debit - gl.credit) as amount
		from `tabGL Entry` gl
		join `tabAccount` a on a.name = gl.account
		where gl.is_cancelled = 0
		  and gl.cost_center in %(centres)s
		  and a.root_type = 'Expense'
		  and ifnull(a.account_type, '') not in %(skip)s
		  {window}
		group by gl.voucher_type, gl.voucher_no, gl.posting_date
		having sum(gl.debit - gl.credit) > 0.005
		order by gl.posting_date desc, gl.voucher_no desc
		limit %(limit)s
		""".format(window=("and " + " and ".join(window)) if window else ""),
		dict({"centres": centres, "skip": NOT_A_SPEND,
		      "limit": min(cint(limit) or 40, 200)}, **narrowed),
		as_dict=True)

	rows = []
	for row in spend:
		detail = SPEND_DETAIL.get(row.voucher_type, lambda _: {})(row.voucher_no)
		rows.append({
			"name": detail.get("ref") or row.voucher_no,
			"voucher_type": row.voucher_type,
			"voucher_no": row.voucher_no,
			"kind": SPEND_KIND.get(row.voucher_type, row.voucher_type),
			"posting_date": str(row.posting_date),
			"amount": flt(row.amount),
			"branch_label": _responsible_branch(row.cost_center),
			"cost_center": row.cost_center,
			"category_label": detail.get("category_label") or "",
			"items": detail.get("items") or "",
			"paid_to_label": detail.get("paid_to_label") or "",
			"notes": detail.get("notes") or "",
			"outstanding_amount": flt(detail.get("outstanding_amount")),
			"docstatus": 1,
		})

	rows.extend(_unposted(employee.branch, narrowed))
	rows.sort(key=lambda r: (r["posting_date"], r["name"]), reverse=True)

	# Searched here rather than in SQL: what a spend was for lives in a journal,
	# a claim or a bill, and the row above has already been to all three.
	query = (data.get("query") or "").strip().lower()
	if query:
		rows = [r for r in rows if query in " ".join(str(r.get(key) or "") for key in
			("name", "voucher_no", "category_label", "items", "paid_to_label",
			 "notes", "kind")).lower()]

	month = frappe.db.sql(
		"""
		select coalesce(sum(gl.debit - gl.credit), 0)
		from `tabGL Entry` gl
		join `tabAccount` a on a.name = gl.account
		where gl.is_cancelled = 0
		  and gl.cost_center in %(centres)s
		  and a.root_type = 'Expense'
		  and ifnull(a.account_type, '') not in %(skip)s
		  and month(gl.posting_date) = month(curdate())
		  and year(gl.posting_date) = year(curdate())
		""",
		{"centres": centres, "skip": NOT_A_SPEND})[0][0]

	# What the rows on screen come to, which is not the month's total once a
	# window has been asked for — the tiles have to say which they are showing.
	shown = sum(flt(r["amount"]) for r in rows)
	return {"branch": employee.branch, "rows": rows, "month_total": flt(month),
	        "shown_total": shown, "filtered": bool(query or narrowed)}


def _unposted(branch: str, window: dict | None = None) -> list[dict]:
	"""Expenses started here and not yet submitted, which have no ledger line."""
	picked = {"branch": branch, "docstatus": 0}
	if (window or {}).get("from_date"):
		picked["posting_date"] = (">=", window["from_date"])
	if (window or {}).get("to_date"):
		picked["posting_date"] = (("between", [window.get("from_date"), window["to_date"]])
		                          if window.get("from_date") else ("<=", window["to_date"]))
	drafts = frappe.get_all(
		"Branch Expense", filters=picked,
		fields=["name", "posting_date", "category", "grand_total", "paid_to",
		        "supplier", "notes", "outstanding_amount", "cost_center"],
		order_by="posting_date desc, creation desc")
	out = []
	for d in drafts:
		lines = frappe.get_all("Branch Expense Item", filters={"parent": d.name},
		                       fields=["item_code", "description", "qty"], order_by="idx")
		out.append({
			"name": d.name, "voucher_type": "Branch Expense", "voucher_no": d.name,
			"kind": SPEND_KIND["Journal Entry"],
			"posting_date": str(d.posting_date), "amount": flt(d.grand_total),
			"branch_label": _responsible_branch(d.cost_center) or branch,
			"cost_center": d.cost_center,
			"category_label": _account_label(d.category),
			"items": _things([_line_label(r) for r in lines]),
			"paid_to_label": d.paid_to or (
				frappe.get_cached_value("Supplier", d.supplier, "supplier_name")
				if d.supplier else ""),
			"notes": d.notes or "", "outstanding_amount": flt(d.outstanding_amount),
			"docstatus": 0,
		})
	return out


@frappe.whitelist()
def create(payload) -> dict:
	"""Record a spend. The document works out which of the three it becomes.

	A GST bill posts as the supplier's own Purchase Invoice, a spend an employee
	paid out of pocket as an Expense Claim, and everything else as the Journal
	Entry petty cash has always been. See `Branch Expense.route`.
	"""
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
	# Not `doc.employee = ...`: `Document.insert` re-applies field defaults over
	# every blank field, and a Link to Employee is filled from the counter's own
	# User Permission — so "nobody paid this out of pocket" would come back as
	# "the person at the till did", and every petty-cash slip would post as
	# their expense claim. The flag survives that; the field does not.
	doc.flags.paid_by_employee = (data.get("employee") or "").strip() or None
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
	# A typed nought is not blank, so the flag tells the document the difference.
	if data.get("paid_amount") not in (None, ""):
		doc.paid_amount = flt(data.get("paid_amount"))
		doc.flags.paid_amount_given = True

	# A balance has to be owed to somebody: ERPNext keeps payables against a
	# party, and a typed name cannot hold one. Rather than refuse the entry over
	# a record the counter has no way to create, make the supplier from the name
	# they gave — which is what their old software did with a contact.
	if doc.paid_to and not doc.supplier and not doc.employee and _owes(doc):
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
		"posted_as": doc.posted_as,
		"posted": doc.purchase_invoice or doc.expense_claim or doc.journal_entry,
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
	"""Add something the shop buys but does not stock.

	The same questions their old software asked, because the people filling it
	in learned the form there: a name, whether it is a thing or a job, what it
	cost last time and whether that figure had the tax in it, the unit, the HSN
	and the rate, and whether the credit can be claimed.
	"""
	_me()
	require_permission("Item", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	name = " ".join((data.get("item_name") or "").split())
	if not name:
		frappe.throw(_("Give it a name."), title=_("Item name"))

	existing = frappe.db.get_value("Item", {"item_name": name, "is_stock_item": 0}, "name")
	if existing:
		return {"item_code": existing, "item_name": name, "created": False}

	rate = flt(data.get("rate"))
	gst = flt(data.get("gst_rate"))
	# A price quoted with the tax in it is not what the expense line costs, so
	# it is taken back out before the rate is stored.
	if data.get("tax_included") and gst:
		rate = flt(rate * 100 / (100 + gst), 2)

	doc = frappe.new_doc("Item")
	doc.item_code = name
	doc.item_name = name
	doc.item_group = _expense_item_group()
	uom = (data.get("uom") or "").strip()
	doc.stock_uom = uom if uom and frappe.db.exists("UOM", uom) else "Nos"
	doc.is_stock_item = 0
	# Bought, never sold: it has no business turning up in the till's search.
	doc.is_purchase_item = 1
	doc.is_sales_item = 0
	doc.valuation_rate = rate

	hsn = (data.get("hsn") or "").strip()
	if hsn and doc.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", hsn):
		doc.gst_hsn_code = hsn
	if data.get("itc") and data["itc"] != "eligible" \
			and doc.meta.has_field("is_ineligible_for_itc"):
		doc.is_ineligible_for_itc = 1

	account = (data.get("expense_account") or "").strip()
	if account and frappe.db.exists("Account", account):
		doc.append("item_defaults", {"company": _company(), "expense_account": account})

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	if gst:
		_set_item_gst(doc.name, gst)

	return {"item_code": doc.name, "item_name": doc.item_name, "created": True,
	        "rate": rate, "gst_rate": gst}


def _set_item_gst(item_code: str, rate: float) -> None:
	"""Point the item at the tax template for its rate, when one exists."""
	template = frappe.db.get_value(
		"Item Tax Template", {"name": ("like", f"%{rate:g}%")}, "name")
	if not template:
		return
	item = frappe.get_doc("Item", item_code)
	item.append("taxes", {"item_tax_template": template})
	item.flags.ignore_permissions = True
	item.save(ignore_permissions=True)


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
def search_employees(query: str = "", limit: int = 10) -> list[dict]:
	"""Staff of this branch, for a spend one of them paid out of pocket."""
	employee = _me()
	like = f"%{(query or '').strip()}%"
	return frappe.get_all(
		"Employee",
		filters={"status": "Active", "branch": employee.branch,
		         "employee_name": ("like", like)},
		fields=["name", "employee_name", "designation"],
		order_by="employee_name",
		limit_page_length=min(cint(limit) or 10, 25))


@frappe.whitelist()
def supplier_gstin(supplier: str) -> dict:
	"""Whether this supplier can be billed with GST, for the form to say so."""
	_me()
	from a3_retail.utils import tax

	return {"supplier": supplier, "gstin": tax.supplier_gstin(supplier)}


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
	_me()
	require_permission("Branch Expense", "create")

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
