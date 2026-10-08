# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Supplier management for the branch app (`/retail/suppliers`).

One distributor, everything about them: what the shop bought, what it has paid,
what it sent back, and what is still owed. The counterpart to `/retail/customers`
and deliberately the same shape, because the person using it is the same person.

Unlike the customer desk this one does take money out: a shop settles its
distributors from the branch, and making them walk to the desk UI for it is how
payments end up unrecorded. A payment is a Payment Entry against the supplier,
with the bills it settles allocated against it, so the ledger shows which
invoice each rupee closed rather than a loose credit on the account.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.staff import _me

PAGE_SIZE = 8


def _company() -> str:
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _initials(name: str) -> str:
	parts = [p for p in str(name or "").split() if p]
	return ("".join(p[0] for p in parts[:2]) or "?").upper()


def _outstanding(supplier: str) -> float:
	"""What the shop still owes, across every submitted bill."""
	return flt(frappe.db.sql(
		"""select sum(outstanding_amount) from `tabPurchase Invoice`
		   where supplier = %s and docstatus = 1""", supplier)[0][0])


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------
@frappe.whitelist()
def list_suppliers(query: str = "", page: int = 1, page_size: int = PAGE_SIZE,
                   only_owing: int = 0) -> dict:
	"""The left-hand list. Suppliers are chain-wide: a distributor serves every
	branch, so unlike customers there is nothing branch-local to scope to."""
	_me()
	require_permission("Supplier", "read")

	page = max(cint(page), 1)
	size = min(max(cint(page_size) or PAGE_SIZE, 1), 50)
	conditions = ["s.disabled in (0, 1)"]
	values = {"start": (page - 1) * size, "size": size}

	if query:
		conditions.append(
			"(s.supplier_name like %(like)s or s.name like %(like)s"
			" or s.gstin like %(like)s or s.mobile_no like %(like)s)")
		values["like"] = f"%{query}%"
	where = " and ".join(conditions)

	total = frappe.db.sql(f"select count(*) from `tabSupplier` s where {where}", values)[0][0]
	rows = frappe.db.sql(
		f"""
		select s.name, s.supplier_name, s.disabled, s.supplier_group,
		       s.mobile_no, s.gstin, s.gst_category
		from `tabSupplier` s
		where {where}
		order by s.modified desc
		limit %(start)s, %(size)s
		""", values, as_dict=True)

	for row in rows:
		row["initials"] = _initials(row["supplier_name"])
		row["active"] = not cint(row["disabled"])
		row["outstanding"] = _outstanding(row["name"])

	if cint(only_owing):
		rows = [r for r in rows if flt(r["outstanding"]) > 0]

	return {
		"rows": rows, "total": total, "page": page, "page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


@frappe.whitelist()
def profile(supplier: str) -> dict:
	"""Everything the panel shows about one distributor."""
	_me()
	require_permission("Supplier", "read")

	doc = frappe.get_doc("Supplier", supplier)
	address = frappe.db.sql(
		"""select a.name, a.address_line1, a.city, a.state, a.pincode, a.gstin
		   from `tabAddress` a
		   join `tabDynamic Link` l on l.parent = a.name
		   where l.link_doctype = 'Supplier' and l.link_name = %s
		   order by a.is_primary_address desc, a.modified desc limit 1""",
		supplier, as_dict=True)

	bills = frappe.db.sql(
		"""select count(*) n, ifnull(sum(grand_total), 0) spend,
		          max(posting_date) last_seen
		   from `tabPurchase Invoice` where supplier = %s and docstatus = 1""",
		supplier, as_dict=True)[0]

	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_group": doc.supplier_group,
		"mobile_no": doc.get("mobile_no"),
		"email_id": doc.get("email_id"),
		"gstin": doc.get("gstin"),
		"gst_category": doc.get("gst_category"),
		"disabled": cint(doc.disabled),
		"initials": _initials(doc.supplier_name),
		"address": address[0] if address else {},
		"bills": cint(bills.n),
		"spend": flt(bills.spend),
		"last_seen": bills.last_seen,
		"outstanding": _outstanding(supplier),
	}


@frappe.whitelist()
def tab(supplier: str, name: str = "purchases", limit: int = 40) -> list[dict]:
	"""One of the panel's tabs: what was bought, paid, or sent back."""
	_me()
	require_permission("Supplier", "read")
	limit = min(max(cint(limit) or 40, 1), 200)

	if name == "payments":
		require_permission("Payment Entry", "read")
		return frappe.db.sql(
			"""select pe.name, pe.posting_date, pe.paid_amount, pe.mode_of_payment,
			          pe.paid_from, pe.reference_no, pe.docstatus
			   from `tabPayment Entry` pe
			   where pe.party_type = 'Supplier' and pe.party = %s and pe.docstatus < 2
			   order by pe.posting_date desc, pe.creation desc limit %s""",
			(supplier, limit), as_dict=True)

	is_return = 1 if name == "returns" else 0
	return frappe.db.sql(
		"""select pi.name, pi.posting_date, pi.bill_no, pi.grand_total,
		          pi.outstanding_amount, pi.status, pi.docstatus
		   from `tabPurchase Invoice` pi
		   where pi.supplier = %s and pi.docstatus < 2 and ifnull(pi.is_return, 0) = %s
		   order by pi.posting_date desc, pi.creation desc limit %s""",
		(supplier, is_return, limit), as_dict=True)


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
@frappe.whitelist()
def save_supplier(supplier: str | None = None, supplier_name: str = "",
                  mobile_no: str | None = None, email_id: str | None = None,
                  gstin: str | None = None, address_line1: str | None = None,
                  city: str | None = None, state: str | None = None,
                  pincode: str | None = None) -> dict:
	"""Create a distributor, or correct one already on file.

	A GSTIN is checked before it is stored and the state is taken from it, the
	same as for a customer — a purchase filed under a wrong number is as much
	trouble as a sale.
	"""
	_me()
	from a3_retail.api.customer import gstin_state, validate_gstin

	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw(_("Give the supplier a name."), title=_("Supplier"))
	gstin = validate_gstin(gstin)

	if supplier:
		require_permission("Supplier", "write")
		doc = frappe.get_doc("Supplier", supplier)
	else:
		require_permission("Supplier", "create")
		doc = frappe.new_doc("Supplier")
		doc.supplier_group = frappe.db.get_value(
			"Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"

	doc.supplier_name = supplier_name
	if mobile_no is not None and doc.meta.has_field("mobile_no"):
		doc.mobile_no = mobile_no.strip() or None
	if email_id is not None and doc.meta.has_field("email_id"):
		doc.email_id = email_id.strip() or None
	if gstin:
		doc.gstin = gstin
		from a3_retail.api.customer import _gst_category

		doc.gst_category = _gst_category(gstin)
	doc.flags.ignore_mandatory = True
	doc.save()

	home = gstin_state(gstin) or (state or "").strip() or None
	if address_line1 or gstin:
		_save_address(doc.name, supplier_name, address_line1 or "-", city, pincode,
		              home, gstin)
	return profile(doc.name)


def _save_address(supplier, title, line1, city, pincode, state, gstin):
	existing = frappe.db.sql(
		"""select a.name from `tabAddress` a
		   join `tabDynamic Link` l on l.parent = a.name
		   where l.link_doctype = 'Supplier' and l.link_name = %s
		   order by a.is_primary_address desc, a.modified desc limit 1""", supplier)
	doc = frappe.get_doc("Address", existing[0][0]) if existing else frappe.new_doc("Address")
	if not existing:
		doc.address_title = title[:100]
		doc.address_type = "Billing"
		doc.is_primary_address = 1
		doc.append("links", {"link_doctype": "Supplier", "link_name": supplier})
	doc.address_line1 = line1
	doc.city = city or doc.city or "-"
	doc.state = state or doc.state
	doc.pincode = pincode
	doc.country = doc.country or "India"
	if gstin and doc.meta.has_field("gstin"):
		doc.gstin = gstin
	doc.flags.ignore_mandatory = True
	doc.save()


@frappe.whitelist()
def set_disabled(supplier: str, disabled: int = 1) -> dict:
	"""Stop buying from a distributor without losing what was bought before."""
	_me()
	require_permission("Supplier", "write")
	frappe.db.set_value("Supplier", supplier, "disabled", 1 if cint(disabled) else 0)
	return profile(supplier)


# ---------------------------------------------------------------------------
# Paying
# ---------------------------------------------------------------------------
@frappe.whitelist()
def open_invoices(supplier: str) -> list[dict]:
	"""Bills with something still owing on them, oldest first.

	Oldest first because that is the order a shop settles in, and the screen
	allocates down the list.
	"""
	_me()
	require_permission("Purchase Invoice", "read")
	return frappe.db.sql(
		"""select pi.name, pi.posting_date, pi.bill_no, pi.bill_date,
		          pi.grand_total, pi.outstanding_amount
		   from `tabPurchase Invoice` pi
		   where pi.supplier = %s and pi.docstatus = 1
		     and ifnull(pi.is_return, 0) = 0 and pi.outstanding_amount > 0.005
		   order by pi.posting_date, pi.creation""", supplier, as_dict=True)


@frappe.whitelist()
def pay(supplier: str, amount: float, mode_of_payment: str = "Cash",
        account: str | None = None, allocations=None,
        reference_no: str | None = None, posting_date: str | None = None) -> dict:
	"""Pay a distributor, settling the bills the counter picked.

	`allocations` is what the screen decided — `[{"invoice": name, "amount": x}]`.
	Without any, the payment sits on the supplier's account as a credit, which is
	a real thing a shop does (an advance), so it is allowed rather than refused.

	The money leaves a real account, so the mode's own account is used unless the
	counter named which one it came out of.
	"""
	employee = _me()
	require_permission("Payment Entry", "create")

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter how much is being paid."), title=_("Payment"))
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("That supplier is not on file."), title=_("Payment"))

	if isinstance(allocations, str):
		allocations = frappe.parse_json(allocations)
	allocations = allocations or []

	company = _company()
	paid_from = account or frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company},
		"default_account")
	if not paid_from:
		frappe.throw(
			_("{0} has no account set for this company — head office has to add it once.")
			.format(mode_of_payment), title=_("Payment"))

	rows = []
	total_allocated = 0.0
	for line in allocations:
		invoice = (line or {}).get("invoice")
		share = flt((line or {}).get("amount"))
		if not invoice or share <= 0:
			continue
		owed = flt(frappe.db.get_value("Purchase Invoice", invoice, "outstanding_amount"))
		if frappe.db.get_value("Purchase Invoice", invoice, "supplier") != supplier:
			frappe.throw(_("{0} is not a bill from this supplier.").format(invoice),
			             title=_("Payment"))
		if share > owed + 0.005:
			frappe.throw(
				_("{0} only has {1} left on it.").format(invoice, frappe.format_value(
					owed, {"fieldtype": "Currency"})), title=_("Payment"))
		rows.append({"reference_doctype": "Purchase Invoice", "reference_name": invoice,
		             "allocated_amount": share})
		total_allocated += share

	if total_allocated > amount + 0.005:
		frappe.throw(_("The bills picked come to more than the amount being paid."),
		             title=_("Payment"))

	from erpnext.accounts.party import get_party_account

	# Posting as the signed-in user keeps the branch's own guards in play; the
	# mechanical bits that read the chart of accounts run elevated, exactly as a
	# counter receipt does.
	actor = frappe.session.user
	frappe.set_user("Administrator")
	try:
		entry = frappe.new_doc("Payment Entry")
		entry.payment_type = "Pay"
		entry.company = company
		entry.posting_date = getdate(posting_date) if posting_date else nowdate()
		entry.mode_of_payment = mode_of_payment
		entry.party_type = "Supplier"
		entry.party = supplier
		entry.paid_from = paid_from
		entry.paid_to = get_party_account("Supplier", supplier, company)
		entry.paid_amount = amount
		entry.received_amount = amount
		entry.source_exchange_rate = 1
		entry.target_exchange_rate = 1
		if reference_no:
			entry.reference_no = reference_no
			entry.reference_date = entry.posting_date
		cost_center = frappe.db.get_value(
			"Branch Profile", {"branch": employee.branch}, "sales_cost_center")
		if cost_center and entry.meta.has_field("cost_center"):
			entry.cost_center = cost_center
		for row in rows:
			entry.append("references", row)
		entry.setup_party_account_field()
		entry.set_missing_values()
		for row in entry.get("deductions") or []:
			row.cost_center = cost_center or row.cost_center
		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
	finally:
		frappe.set_user(actor)

	return {
		"payment": entry.name,
		"paid": flt(entry.paid_amount),
		"allocated": total_allocated,
		"unallocated": flt(entry.unallocated_amount),
		"outstanding": _outstanding(supplier),
	}
