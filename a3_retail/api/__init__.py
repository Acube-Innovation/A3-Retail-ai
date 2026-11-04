"""Whitelisted API surface for A3 Retail.

Every endpoint in this package must perform an explicit permission check —
`frappe.whitelist()` alone only proves the caller is logged in. Use the
`require_permission` / `require_role` helpers below rather than hand-rolling
checks so the security audit in step 26 has one place to look.
"""

import frappe
from frappe import _


def require_permission(doctype: str, ptype: str = "read", doc=None):
	"""Throw PermissionError unless the session user has `ptype` on `doctype`."""
	if not frappe.has_permission(doctype, ptype=ptype, doc=doc):
		frappe.throw(
			_("Not permitted to {0} {1}").format(ptype, _(doctype)),
			frappe.PermissionError,
		)


def require_role(*roles: str):
	"""Throw PermissionError unless the user holds at least one of `roles`."""
	allowed = set(roles) | {"System Manager", "A3 Retail Admin"}
	if not (allowed & set(frappe.get_roles())):
		frappe.throw(
			_("This action requires one of these roles: {0}").format(", ".join(roles)),
			frappe.PermissionError,
		)


def require_branch_access(branch: str | None):
	"""Throw unless the user is allowed to act on `branch`."""
	from a3_retail.utils.permissions import get_permitted_branches

	if not branch:
		return
	permitted = get_permitted_branches()
	if permitted and branch not in permitted:
		frappe.throw(_("You do not have access to branch {0}").format(branch), frappe.PermissionError)


def parse_payload(payload) -> dict:
	"""Accept a dict or a JSON string from the client and return a dict."""
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid payload"))
	return payload


def stamp_cost_center(doc, cost_center: str | None):
	"""Put the branch's cost center on every cost-center field of a document.

	Two reasons, and they point the same way. A branch's postings belong to that
	branch's cost center, not to whatever default ERPNext reaches for while it is
	pricing the document. And `apply_strict_user_permissions` treats a *blank*
	link, or one outside the user's allowed set, as a violation — so an invoice
	that keeps "Main" on its tax rows becomes unreadable to the very counter that
	raised it, which breaks reading it back, allocating an advance against it and
	printing it.

	Every Cost Center link on the parent and on every child row, overwritten.
	"""
	if not cost_center:
		return

	def stamp(row):
		for field in row.meta.get_link_fields():
			if field.options == "Cost Center":
				row.set(field.fieldname, cost_center)

	stamp(doc)
	for table in doc.meta.get_table_fields():
		for row in doc.get(table.fieldname) or []:
			stamp(row)



def date_window(data: dict, column: str, values: dict) -> list[str]:
	"""SQL for the from/to dates a list's filter sheet sends.

	Shared because five lists ask the same question of five different date
	columns, and a window that is half-applied on one of them is the kind of
	wrong nobody notices until a month's figures do not add up.
	"""
	from frappe.utils import getdate

	where = []
	if data.get("from_date"):
		where.append(f"{column} >= %(from_date)s")
		values["from_date"] = getdate(data["from_date"])
	if data.get("to_date"):
		where.append(f"{column} <= %(to_date)s")
		values["to_date"] = getdate(data["to_date"])
	return where


def stamp_posting(doc, posting_date, after=None, step: int = 0):
	"""Date a document, and give it a time of day that makes sense.

	`set_posting_time = 1` tells ERPNext to keep the date we chose — and it
	keeps the *time* we chose too, which on a new document is midnight. A
	credit note dated the same day as the sale therefore posted at 00:00:00,
	hours before the sale it reverses, and the stock ledger refused it:

	    Posting timestamp must be after 29-10-2026 21:17:28

	So: a document dated today posts now. One dated the same day as the thing
	it answers posts a second after it. Anything older posts at the end of its
	day, which is after everything that happened on it.

	`after` is the document being reversed or followed — a Sales Invoice, a
	Purchase Invoice, anything with a posting date and time.

	`step` pushes the time on by that many seconds, which is how a run of
	documents that must happen in a given order gets stamped in that order. A
	replacement raises four: the unit has to be bought back from the supplier
	before it can be sold on to the customer, and left to the wall clock —
	or worse, to a time copied off the original bill — the sale was landing
	before the purchase and the serial-number ledger refused the pair.
	"""
	from frappe.utils import get_datetime, getdate, nowdate, nowtime

	posting = getdate(posting_date)
	doc.posting_date = posting
	doc.set_posting_time = 1

	if posting == getdate(nowdate()):
		doc.posting_time = nowtime()
	else:
		# Late in the day, so a back-dated document sits after everything that
		# really happened on it. Room is left for `step` to climb.
		doc.posting_time = "23:50:00"

	if after is not None:
		_not_before(doc, posting, after)
	if step:
		_shift(doc, posting, step)


def _not_before(doc, posting, after):
	from frappe.utils import get_datetime, getdate

	source_date = getdate(after.get("posting_date"))
	if source_date != posting:
		return

	# Same day as the document it follows: a second later, so the ledger reads
	# them in the order they happened rather than refusing the pair.
	stamp = get_datetime(f"{source_date} {after.get('posting_time') or '00:00:00'}")
	ours = get_datetime(f"{posting} {doc.posting_time}")
	if ours <= stamp:
		from datetime import timedelta

		doc.posting_time = (stamp + timedelta(seconds=1)).strftime("%H:%M:%S")


def _shift(doc, posting, seconds: int):
	from datetime import timedelta

	from frappe.utils import get_datetime

	moved = get_datetime(f"{posting} {doc.posting_time}") + timedelta(seconds=seconds)
	doc.posting_time = moved.strftime("%H:%M:%S")


def stock_expense_account(doc):
	"""Name the inventory account on a purchase document that moves stock.

	With `update_stock`, ERPNext insists each line's expense head is the
	*warehouse's* account. Left to the company default it finds
	`Stock Received But Not Billed`, rewrites it to the warehouse's account
	anyway, and narrates the correction into whatever dialog the counter is in:

	    Row 1: Expense Head changed to Stock In Hand - PT because account Stock
	    Received But Not Billed - PT is not linked to warehouse …

	Saying it up front changes no posting — it is the same account ERPNext was
	going to use — and stops it being said.
	"""
	import frappe

	for row in doc.get("items") or []:
		warehouse = row.get("warehouse") or doc.get("set_warehouse")
		if not warehouse:
			continue
		account = frappe.db.get_value("Warehouse", warehouse, "account")
		if account:
			row.expense_account = account
