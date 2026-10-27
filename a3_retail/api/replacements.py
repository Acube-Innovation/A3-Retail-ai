# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Swapping a faulty handset for a good one (`Replace` on a bill).

A customer brings back a phone that has failed. The shop gives them another,
and the dead one goes back to the distributor who replaces it in turn. That is
one act at the counter and four documents in the books, and doing them by hand
across four screens is how branches end up with phones nobody can account for.

The four, in the order stock has to move:

    1. credit note   the faulty unit comes back from the customer
    2. debit note    the faulty unit goes out to the supplier
    3. purchase      the replacement comes in from the supplier
    4. sale          the replacement goes out to the customer

Each pair nets to nothing — the customer pays no more and is owed no more, and
the supplier is owed no more and owes no more — so a fifth document, a journal
against both of the customer's, knocks them off each other. Without it the
customer is left holding a credit note and an invoice for the same money, and
every statement they are sent is wrong.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from a3_retail.api import require_permission, stamp_cost_center
from a3_retail.api.pos import _profile, print_url
from a3_retail.api.staff import _me


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def options(invoice: str) -> dict:
	"""What on this bill can be swapped, and the serials to swap."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	doc = frappe.get_doc("Sales Invoice", invoice)
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))
	if doc.docstatus != 1 or doc.is_return:
		frappe.throw(_("Only a completed sale can be replaced."), title=_("Not a sale"))

	# What has already gone back on this bill, so the same handset cannot be
	# swapped twice.
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
		serials = [s for s in (row.get("serial_no") or "").split("\n") if s.strip()]
		lines.append({
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"rate": flt(row.rate),
			"can_replace": max(flt(row.qty) - already, 0),
			"serials": serials,
			"has_serial": bool(frappe.db.get_value("Item", row.item_code, "has_serial_no")),
			"supplier": _supplier_for(row.item_code, serials),
		})

	return {
		"invoice": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"posting_date": str(doc.posting_date),
		"lines": lines,
	}


def _supplier_for(item_code: str, serials: list[str]) -> str | None:
	"""Who this unit came from.

	A Serial No records the document it arrived on rather than the supplier, so
	the supplier is read off that document — which is the right one anyway: a
	handset goes back to whoever actually sent it, not to whoever the item is
	usually bought from.
	"""
	for serial in serials:
		bought_on = frappe.db.get_value("Serial No", serial, "purchase_document_no")
		if bought_on and frappe.db.exists("Purchase Invoice", bought_on):
			supplier = frappe.db.get_value("Purchase Invoice", bought_on, "supplier")
			if supplier:
				return supplier
	return frappe.db.get_value("Item Default", {"parent": item_code}, "default_supplier")


@frappe.whitelist()
def replace(payload) -> dict:
	"""Swap a faulty unit for a good one, both ways at once."""
	employee = _me()
	require_permission("Sales Invoice", "create")
	require_permission("Purchase Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	source = _checked_bill(data.get("invoice"), employee)
	line = _checked_line(source, data)
	qty = flt(data.get("qty")) or 1
	faulty = [s for s in (data.get("faulty_serials") or []) if s]
	fresh = [s for s in (data.get("new_serials") or []) if s]
	reason = (data.get("reason") or "").strip()
	if not reason:
		frappe.throw(_("Say what is wrong with it."), title=_("Reason"))

	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Name the supplier the faulty one goes back to."),
		             title=_("Supplier"))

	has_serial = bool(frappe.db.get_value("Item", line.item_code, "has_serial_no"))
	if has_serial:
		if len(faulty) != int(qty):
			frappe.throw(_("Pick which {0} is coming back.").format(line.item_name),
			             title=_("IMEI"))
		if len(fresh) != int(qty):
			frappe.throw(_("Enter the IMEI of the replacement the supplier gave."),
			             title=_("New IMEI"))
		if set(fresh) & set(faulty):
			frappe.throw(_("The replacement cannot be the handset that came back."),
			             title=_("New IMEI"))
		_serial_is_free(fresh)

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A replacement cannot be dated in the future."), title=_("Date"))
	if posting < getdate(source.posting_date):
		frappe.throw(_("The bill is dated {0}, so it cannot have been replaced on {1}.")
		             .format(frappe.utils.formatdate(source.posting_date),
		                     frappe.utils.formatdate(posting)), title=_("Date"))

	profile = _profile(employee.branch)
	cost = flt(data.get("cost_rate")) or _cost_of(line.item_code, profile.default_warehouse)

	# Order matters: stock has to be on the shelf before it can leave it.
	swap_ref = f"REPL/{source.name}"
	credit = _credit_note(source, line, qty, faulty, reason, posting, employee, profile)
	debit = _debit_note(supplier, line, qty, faulty, cost, reason, posting,
	                    employee, profile, swap_ref)
	bought = _purchase(supplier, line, qty, fresh, cost, reason, posting,
	                   employee, profile, swap_ref)
	sold = _sale(source, line, qty, fresh, reason, posting, employee, profile)
	netting = _net_off(source.customer, credit, sold, posting)
	supplier_netting = _net_supplier(supplier, debit, bought, posting)

	_leave_a_trail(source, credit, debit, bought, sold, netting, line, faulty, fresh)

	return {
		"credit_note": credit, "debit_note": debit,
		"purchase": bought, "sale": sold, "netting": netting,
		"supplier_netting": supplier_netting,
		"item": line.item_name,
		"faulty": faulty, "replacement": fresh,
		"print_url": print_url(sold),
	}


# ---------------------------------------------------------------------------
# What is allowed
# ---------------------------------------------------------------------------
def _checked_bill(invoice: str | None, employee):
	doc = frappe.get_doc("Sales Invoice", invoice) if invoice and frappe.db.exists(
		"Sales Invoice", invoice) else None
	if not doc:
		frappe.throw(_("Find the bill this is coming back on."), title=_("Which bill?"))
	if doc.branch and doc.branch != employee.branch:
		frappe.throw(_("That bill belongs to another branch."), title=_("Not this branch"))
	if doc.docstatus != 1 or doc.is_return:
		frappe.throw(_("Only a completed sale can be replaced."), title=_("Not a sale"))
	return doc


def _checked_line(source, data: dict):
	code = (data.get("item_code") or "").strip()
	for row in source.items:
		if row.item_code == code:
			return row
	frappe.throw(_("That item is not on this bill."), title=_("Not on the bill"))


def _serial_is_free(serials: list[str]) -> None:
	"""A replacement IMEI must not already be somebody else's handset."""
	for serial in serials:
		held = frappe.db.get_value("Serial No", serial,
		                           ["name", "status", "warehouse"], as_dict=True)
		if held and held.warehouse:
			frappe.throw(
				_("IMEI {0} is already in {1} — it cannot also be the one the "
				  "supplier just sent.").format(serial, held.warehouse),
				title=_("IMEI in use"))
		if held and held.status == "Delivered":
			frappe.throw(
				_("IMEI {0} has already been sold. Check the number on the box.")
				.format(serial), title=_("IMEI in use"))


def _cost_of(item_code: str, warehouse: str | None) -> float:
	"""What the unit is worth going back, so both supplier documents agree.

	The shelf's own valuation first, then what the item was last bought at: the
	debit note and the purchase that replaces it have to carry the same figure
	or the supplier's account is left with a difference nobody owes.
	"""
	held = flt(frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	if held > 0:
		return held
	return flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))


# ---------------------------------------------------------------------------
# The documents
# ---------------------------------------------------------------------------
def _trim_to_line(doc, item_code: str, qty: float, serials: list[str]) -> None:
	"""Keep one line of a copied bill, at the quantity being swapped.

	A bill's discount belongs to the whole bill, so trimming it to one line has
	to take that line's share of it with it — otherwise a 6,000 discount meant
	for five items lands entirely on the one coming back.
	"""
	whole = sum(abs(flt(row.amount)) for row in doc.items) or 1.0
	keep = [row for row in doc.items if row.item_code == item_code][:1]
	if not keep:
		frappe.throw(_("That item is not on this bill."), title=_("Not on the bill"))

	row = keep[0]
	share = abs(flt(row.amount)) / whole
	sign = -1 if flt(row.qty) < 0 else 1
	row.qty = sign * abs(flt(qty))
	# The bundle the line arrived with belongs to the bill it was copied from,
	# and ERPNext refuses to let two documents share one. The serials are given
	# by number instead, and a fresh bundle is built on submit.
	for field in ("serial_and_batch_bundle", "rejected_serial_and_batch_bundle"):
		if row.meta.has_field(field):
			row.set(field, None)
	row.serial_no = "\n".join(serials) if serials else None
	row.use_serial_batch_fields = 1 if serials else 0
	doc.set("items", [row])

	if flt(doc.discount_amount):
		doc.discount_amount = flt(flt(doc.discount_amount) * share, 2)


def _credit_note(source, line, qty, serials, reason, posting, employee, profile) -> str:
	"""Leg 1 — the faulty unit comes back from the customer.

	Built by ERPNext's own return builder rather than by hand: it carries the
	bill's rates, its discount and its tax treatment across, and this shop
	sells at tax-inclusive prices with a discount on the grand total. Hand-built
	it came out at 47,199 against a 33,999 bill.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	# `make_return_doc` maps the document through `get_mapped_doc`, which asks
	# the session user for create rights on the target in its own way. The
	# caller has already been checked for Sales Invoice create above, so the
	# mapping runs elevated — the same bargain `pos._receipt` makes.
	actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		doc = make_return_doc("Sales Invoice", source.name)
	finally:
		frappe.set_user(actor)
	_trim_to_line(doc, line.item_code, qty, serials)
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.due_date = posting
	doc.set("payment_schedule", [])
	doc.set("payments", [])
	doc.is_pos = 0
	doc.remarks = _("Replaced — {0}").format(reason)[:500]
	return _post(doc, profile)


def _sale(source, line, qty, serials, reason, posting, employee, profile) -> str:
	"""Leg 4 — the replacement goes out, on the terms the first one went out on.

	A copy of the original bill with the new handset on it: same price, same
	discount, same tax. A warranty swap is not a new sale, and the customer
	must not end up owing a rupee more or less for it.
	"""
	doc = frappe.copy_doc(source)
	doc.is_return = 0
	doc.return_against = None
	_trim_to_line(doc, line.item_code, qty, serials)
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.due_date = posting
	# The copy carries the original's payment schedule, whose due dates are the
	# original's too — and a schedule that falls before the bill it is on is
	# refused. Cleared so ERPNext builds a fresh one for today.
	doc.set("payment_schedule", [])
	doc.set("payments", [])
	doc.is_pos = 0
	doc.set("sales_team", source.get("sales_team") or [])
	doc.remarks = _("Replacement for {0} — {1}").format(source.name, reason)[:500]
	return _post(doc, profile)


def _debit_note(supplier, line, qty, serials, cost, reason, posting,
                employee, profile, data_ref=None) -> str:
	"""Leg 2 — the faulty unit goes out to the supplier."""
	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.is_return = 1
	doc.posting_date = posting
	doc.set_posting_time = 1
	# GST Settings make a bill number mandatory on every purchase document, and
	# a distributor sends no bill with a warranty swap — so the shop's own
	# reference goes on, which is what it would write on the docket anyway.
	doc.bill_no = (data_ref or doc.name or "REPL")[:140]
	doc.bill_date = posting
	doc.update_stock = 1
	doc.set_warehouse = profile.default_warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	doc.remarks = _("Faulty, returned for replacement — {0}").format(reason)[:500]

	item = doc.append("items", {
		"item_code": line.item_code, "qty": -flt(qty), "rate": flt(cost),
		"warehouse": profile.default_warehouse})
	if serials:
		item.use_serial_batch_fields = 1
		item.serial_no = "\n".join(serials)
	return _post(doc, profile)


def _purchase(supplier, line, qty, serials, cost, reason, posting,
              employee, profile, data_ref=None) -> str:
	"""Leg 3 — the replacement arrives from the supplier.

	At the same figure the faulty one went back at, so the supplier's account
	nets to nothing: nobody has bought anything, a unit has been swapped.
	"""
	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.bill_no = (data_ref or "REPL")[:140]
	doc.bill_date = posting
	doc.update_stock = 1
	doc.set_warehouse = profile.default_warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch
	doc.remarks = _("Warranty replacement — {0}").format(reason)[:500]

	item = doc.append("items", {
		"item_code": line.item_code, "qty": flt(qty), "rate": flt(cost),
		"warehouse": profile.default_warehouse})
	if serials:
		item.use_serial_batch_fields = 1
		item.serial_no = "\n".join(serials)
	return _post(doc, profile)


def _post(doc, profile) -> str:
	"""Stamp the branch's cost centre on it and put it through."""
	centre = profile.sales_cost_center or profile.cost_center
	if centre:
		stamp_cost_center(doc, centre)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _net_off(customer: str, credit: str, sale: str, posting) -> str:
	"""Knock the credit note off the replacement invoice, with no money moving.

	A Payment Entry will not take a zero amount, and nothing is being paid: the
	customer settled this phone once already. A journal against both is what
	ERPNext leaves for exactly this.
	"""
	company = _company()
	amount = abs(flt(frappe.db.get_value("Sales Invoice", credit, "outstanding_amount")))
	owed = flt(frappe.db.get_value("Sales Invoice", sale, "outstanding_amount"))
	amount = min(amount, owed)
	if amount <= 0.005:
		return ""

	debtors = frappe.db.get_value("Company", company, "default_receivable_account")
	doc = frappe.new_doc("Journal Entry")
	doc.voucher_type = "Credit Note"
	doc.company = company
	doc.posting_date = posting
	doc.user_remark = _("Replacement: {0} settled against {1}").format(credit, sale)
	doc.append("accounts", {
		"account": debtors, "party_type": "Customer", "party": customer,
		"debit_in_account_currency": amount,
		"reference_type": "Sales Invoice", "reference_name": credit})
	doc.append("accounts", {
		"account": debtors, "party_type": "Customer", "party": customer,
		"credit_in_account_currency": amount,
		"reference_type": "Sales Invoice", "reference_name": sale})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _net_supplier(supplier: str, debit: str, bought: str, posting) -> str:
	"""Knock the debit note off the replacement purchase, with no money moving.

	Nobody has bought anything: a dead unit went back and a live one came in at
	the same figure. Left unnetted the supplier shows as both owing and being
	owed, and the Pay screen offers to settle a bill that is already square.
	"""
	company = _company()
	owed = abs(flt(frappe.db.get_value("Purchase Invoice", bought, "outstanding_amount")))
	back = abs(flt(frappe.db.get_value("Purchase Invoice", debit, "outstanding_amount")))
	amount = min(owed, back)
	if amount <= 0.005:
		return ""

	creditors = frappe.db.get_value("Company", company, "default_payable_account")
	doc = frappe.new_doc("Journal Entry")
	doc.voucher_type = "Debit Note"
	doc.company = company
	doc.posting_date = posting
	doc.user_remark = _("Replacement: {0} settled against {1}").format(debit, bought)
	doc.append("accounts", {
		"account": creditors, "party_type": "Supplier", "party": supplier,
		"debit_in_account_currency": amount,
		"reference_type": "Purchase Invoice", "reference_name": bought})
	doc.append("accounts", {
		"account": creditors, "party_type": "Supplier", "party": supplier,
		"credit_in_account_currency": amount,
		"reference_type": "Purchase Invoice", "reference_name": debit})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _leave_a_trail(source, credit, debit, bought, sold, netting, line,
                   faulty, fresh) -> None:
	"""Write the chain onto the original bill, so it can be followed later."""
	swapped = (_("IMEI {0} replaced by {1}").format(", ".join(faulty), ", ".join(fresh))
	           if faulty and fresh else _("{0} replaced").format(line.item_name))
	frappe.get_doc("Sales Invoice", source.name).add_comment(
		"Comment",
		text=(f"{swapped}. Credit note {credit}, debit note {debit}, "
		      f"purchase {bought}, replacement bill {sold}"
		      + (f", settled by {netting}" if netting else "") + "."))
