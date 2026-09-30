# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Sales returns and credit notes (`/retail/returns`).

A customer brings a phone back. The counter finds the bill it went out on, says
what is coming back and how much of it, and the shop either hands the money over
or leaves it on the customer's account.

A return is a Sales Invoice with `is_return = 1` pointing at the original — the
document ERPNext already understands — so the stock comes back on the same
ledger it left, the tax reverses on the same HSN, and the customer's balance
moves by itself. Nothing here writes a second returns system.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.pos import _profile, _sales_person, _sold_by, print_url, resolve_mode
from a3_retail.api.staff import _me

WINDOW_DAYS = 400


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the screen needs before the counter types anything."""
	employee = _me()
	return {
		"branch": employee.branch,
		"can_create": bool(frappe.has_permission("Sales Invoice", "create")),
		"modes": frappe.get_all(
			"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name"),
	}


@frappe.whitelist()
def find_bills(query: str = "", limit: int = 10) -> list[dict]:
	"""The bills a returning customer might be holding.

	Searched by bill number, customer name or phone — whichever the customer can
	produce. Only this branch's own sales, and only ones that are not themselves
	returns.
	"""
	employee = _me()
	require_permission("Sales Invoice", "read")

	like = f"%{(query or '').strip()}%"
	rows = frappe.db.sql(
		"""
		select si.name, si.customer, si.customer_name, si.posting_date,
		       si.grand_total, si.rounded_total
		from `tabSales Invoice` si
		left join `tabCustomer` c on c.name = si.customer
		where si.docstatus = 1 and si.is_return = 0 and si.branch = %(branch)s
		  and si.posting_date >= date_sub(curdate(), interval %(days)s day)
		  and (si.name like %(q)s or si.customer_name like %(q)s
		       or ifnull(c.a3_mobile_no, '') like %(q)s)
		order by si.posting_date desc, si.creation desc
		limit %(limit)s
		""",
		{"branch": employee.branch, "q": like, "days": WINDOW_DAYS,
		 "limit": min(cint(limit) or 10, 50)},
		as_dict=True,
	)
	for row in rows:
		row["payable"] = flt(row.rounded_total) or flt(row.grand_total)
	return rows


@frappe.whitelist()
def bill_lines(invoice: str) -> dict:
	"""What is on that bill, and how much of it has already come back."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	doc = frappe.get_doc("Sales Invoice", invoice)
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))
	if doc.docstatus != 1 or doc.is_return:
		frappe.throw(_("Only a completed sale can be returned."), title=_("Not a sale"))

	# Whatever has already been sent back on earlier credit notes, so the same
	# phone cannot be returned twice.
	returned = {}
	for row in frappe.db.sql(
		"""
		select it.item_code, sum(abs(it.qty)) as qty
		from `tabSales Invoice Item` it
		join `tabSales Invoice` si on si.name = it.parent
		where si.docstatus = 1 and si.is_return = 1 and si.return_against = %s
		group by it.item_code
		""", invoice, as_dict=True):
		returned[row.item_code] = flt(row.qty)

	lines = []
	for row in doc.items:
		already = flt(returned.get(row.item_code, 0))
		lines.append({
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"returned": already,
			"can_return": max(flt(row.qty) - already, 0),
			"rate": flt(row.rate),
			"serials": [s for s in (row.get("serial_no") or "").split("\n") if s.strip()],
		})

	return {
		"invoice": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"posting_date": str(doc.posting_date),
		"payable": flt(doc.rounded_total) or flt(doc.grand_total),
		"paid": (flt(doc.rounded_total) or flt(doc.grand_total)) - flt(doc.outstanding_amount),
		"lines": lines,
	}


@frappe.whitelist()
def recent(limit: int = 30) -> dict:
	"""Credit notes this branch has raised, newest first."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	rows = frappe.db.sql(
		"""
		select name, customer_name, posting_date, return_against, grand_total,
		       outstanding_amount, docstatus
		from `tabSales Invoice`
		where is_return = 1 and docstatus < 2 and branch = %(branch)s
		order by posting_date desc, creation desc
		limit %(limit)s
		""",
		{"branch": employee.branch, "limit": min(cint(limit) or 30, 100)},
		as_dict=True,
	)
	for row in rows:
		row["amount"] = abs(flt(row.grand_total))
	return {"branch": employee.branch, "rows": rows}


@frappe.whitelist()
def create(payload) -> dict:
	"""Take the goods back and raise the credit note."""
	employee = _me()
	require_permission("Sales Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	against = (data.get("invoice") or "").strip()
	if not against or not frappe.db.exists("Sales Invoice", against):
		frappe.throw(_("Find the bill this is coming back on."), title=_("Which bill?"))

	source = frappe.get_doc("Sales Invoice", against)
	if source.branch and source.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))
	if source.docstatus != 1 or source.is_return:
		frappe.throw(_("Only a completed sale can be returned."), title=_("Not a sale"))

	allowed = {row["item_code"]: row for row in bill_lines(against)["lines"]}
	wanted = [row for row in (data.get("items") or []) if flt(row.get("qty")) > 0]
	if not wanted:
		frappe.throw(_("Say what is coming back."), title=_("Nothing to return"))

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A return cannot be dated in the future."), title=_("Date"))
	if posting < getdate(source.posting_date):
		frappe.throw(_("A return cannot be dated before the sale it came from."),
		             title=_("Date"))

	profile = _profile(employee.branch)
	doc = frappe.new_doc("Sales Invoice")
	doc.company = _company()
	doc.customer = source.customer
	doc.is_return = 1
	doc.return_against = against
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.due_date = posting
	doc.branch = employee.branch
	doc.update_stock = 1
	doc.set_warehouse = profile.default_warehouse
	doc.selling_price_list = source.selling_price_list
	doc.taxes_and_charges = source.taxes_and_charges
	doc.set("taxes", [])
	for tax in source.taxes:
		doc.append("taxes", {
			"charge_type": tax.charge_type, "account_head": tax.account_head,
			"description": tax.description, "rate": tax.rate,
			"included_in_print_rate": tax.included_in_print_rate,
			"cost_center": tax.cost_center,
		})

	cost_center = profile.sales_cost_center or profile.cost_center
	for row in wanted:
		code = row.get("item_code")
		line = allowed.get(code)
		if not line:
			frappe.throw(_("{0} was not on that bill.").format(code), title=_("Not on the bill"))
		qty = flt(row["qty"])
		if qty > line["can_return"] + 0.0001:
			frappe.throw(
				_("Only {0} of {1} can still come back — the rest already has.")
				.format(line["can_return"], line["item_name"]),
				title=_("Already returned"),
			)

		# A return carries negative quantities; that is what sends the stock back.
		added = doc.append("items", {
			"item_code": code,
			"qty": -qty,
			"rate": flt(row.get("rate") or line["rate"]),
			"warehouse": profile.default_warehouse,
		})
		if cost_center:
			added.cost_center = cost_center
		serials = [s for s in (row.get("serials") or []) if s]
		if serials:
			added.use_serial_batch_fields = 1
			added.serial_no = "\n".join(serials)

	person = _sales_person(_sold_by(data, employee))
	if person:
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})
	if cost_center and doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center
	if data.get("reason"):
		doc.remarks = str(data["reason"])[:500]

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	# Money handed back over the counter, or left on the customer's account.
	refund = flt(data.get("refund_amount"))
	payable = abs(flt(doc.rounded_total) or flt(doc.grand_total))
	if refund > payable + 0.5:
		frappe.throw(
			_("The refund is more than the goods coming back, which come to {0}.").format(
				frappe.format_value(payable, {"fieldtype": "Currency"})),
			title=_("Refund"),
		)
	if refund > 0:
		mode = resolve_mode(data.get("mode_of_payment") or "Cash")
		doc.is_pos = 1
		doc.set("payments", [{"mode_of_payment": mode, "amount": -refund}])
		doc.save(ignore_permissions=True)

	doc.submit()

	return {
		"credit_note": doc.name,
		"against": against,
		"customer_name": doc.customer_name,
		"amount": payable,
		"refunded": refund,
		"credit_left": payable - refund,
		"print_url": print_url(doc.name),
	}
