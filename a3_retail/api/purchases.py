# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch purchase entry (`/retail/purchases`).

The shop buys from distributors at the counter — a rep walks in with stock and a
bill. Until now that had to go to head office, which is why five weeks of stock
arrived in the old system with no inward document at all and the books could only
be corrected by counting.

One document does the job: a Purchase Invoice with `update_stock = 1`. It records
what the supplier is owed and brings the goods into the branch warehouse at the
price actually paid, so valuation follows real cost instead of a guess. A
Purchase Order is not required — the goods are already here.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.api.pos import _profile
from a3_retail.api.staff import _me

LINE_LIMIT = 100


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist()
def bootstrap() -> dict:
	"""What the screen needs before the first keystroke."""
	employee = _me()
	profile = _profile(employee.branch)
	return {
		"branch": employee.branch,
		"warehouse": profile.default_warehouse,
		"can_create": bool(frappe.has_permission("Purchase Invoice", "create")),
		"modes": frappe.get_all(
			"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name"
		),
	}


@frappe.whitelist()
def search_suppliers(query: str = "", limit: int = 10) -> list[dict]:
	"""Find the distributor by name or phone."""
	_me()
	require_permission("Supplier", "read")

	like = f"%{(query or '').strip()}%"
	rows = frappe.db.sql(
		"""
		select name, supplier_name, mobile_no
		from `tabSupplier`
		where disabled = 0 and (supplier_name like %(q)s or name like %(q)s
		      or ifnull(mobile_no,'') like %(q)s)
		order by supplier_name limit %(limit)s
		""",
		{"q": like, "limit": min(cint(limit) or 10, 50)},
		as_dict=True,
	)
	return [{"name": r.name, "supplier_name": r.supplier_name, "mobile_no": r.mobile_no}
	        for r in rows]


@frappe.whitelist()
def gstin_info(gstin: str) -> dict:
	"""Look up a GSTIN so the counter does not retype the distributor's details.

	india_compliance's own endpoint refuses anyone without desk access, and branch
	staff are Website Users by design — so this guards the caller itself and then
	uses the internal helper.

	The live lookup needs an India Compliance API subscription. Without one, the
	number is still checked and the state read out of it, because the first two
	digits *are* the state code. Say which of the two happened rather than
	returning a half-filled form with no explanation.
	"""
	_me()
	require_permission("Supplier", "create")

	gstin = (gstin or "").strip().upper()
	if not gstin:
		frappe.throw(_("Enter the GST number first."), title=_("GSTIN"))

	from india_compliance.gst_india.constants import STATE_NUMBERS
	from india_compliance.gst_india.utils import validate_gstin

	# Raises with a plain message if the number or its check digit is wrong.
	validate_gstin(gstin)

	state = {number: name for name, number in STATE_NUMBERS.items()}.get(gstin[:2])
	offline = {"gstin": gstin, "state": state, "source": "number"}

	if not frappe.db.get_single_value("GST Settings", "api_secret"):
		offline["note"] = _("Checked the number. Full details need the GST API, "
		                    "which head office has not switched on yet.")
		return offline

	try:
		from india_compliance.gst_india.utils.gstin_info import _get_gstin_info

		info = _get_gstin_info(gstin, throw_error=False) or {}
	except Exception:
		frappe.clear_last_message()
		info = {}

	if not info.get("business_name"):
		offline["note"] = _("Checked the number, but the GST portal did not answer. "
		                    "Fill the rest in by hand.")
		return offline

	address = info.get("permanent_address") or {}
	return {
		"gstin": gstin,
		"supplier_name": info.get("business_name"),
		"gst_category": info.get("gst_category"),
		"state": address.get("state") or state,
		"address_line1": address.get("address_line1"),
		"address_line2": address.get("address_line2"),
		"city": address.get("city"),
		"pincode": address.get("pincode"),
		"source": "portal",
	}


@frappe.whitelist()
def create_supplier(supplier_name: str, mobile_no: str | None = None,
                    gstin: str | None = None, address_line1: str | None = None,
                    city: str | None = None, state: str | None = None,
                    pincode: str | None = None) -> dict:
	"""A rep the shop has not bought from before."""
	_me()
	require_permission("Supplier", "create")

	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw(_("Give the supplier a name."), title=_("Supplier"))

	gstin = (gstin or "").strip().upper() or None
	if gstin:
		from india_compliance.gst_india.utils import validate_gstin

		validate_gstin(gstin)
		held = frappe.db.get_value("Supplier", {"gstin": gstin},
		                           ["name", "supplier_name"], as_dict=True) \
			if frappe.db.has_column("Supplier", "gstin") else None
		if held:
			return {"name": held.name, "supplier_name": held.supplier_name, "created": False}

	existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
	if existing:
		return {"name": existing, "supplier_name": supplier_name, "created": False}

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = supplier_name
	if mobile_no and doc.meta.has_field("mobile_no"):
		doc.mobile_no = str(mobile_no).strip()
	if gstin and doc.meta.has_field("gstin"):
		doc.gstin = gstin
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)

	if address_line1 or city or pincode:
		_supplier_address(doc.name, supplier_name, gstin, address_line1, city, state, pincode)

	return {"name": doc.name, "supplier_name": supplier_name, "created": True}


def _supplier_address(supplier, title, gstin, line1, city, state, pincode) -> None:
	"""Where the distributor bills from — needed for the GST place of supply."""
	addr = frappe.new_doc("Address")
	addr.address_title = title[:100]
	addr.address_type = "Billing"
	addr.address_line1 = (line1 or "-")[:240]
	addr.city = (city or "-")[:100]
	if state:
		addr.state = state
	if pincode:
		addr.pincode = str(pincode)[:10]
	addr.country = "India"
	if gstin and addr.meta.has_field("gstin"):
		addr.gstin = gstin
	addr.append("links", {"link_doctype": "Supplier", "link_name": supplier})
	addr.flags.ignore_permissions = True
	addr.flags.ignore_mandatory = True
	try:
		addr.insert(ignore_permissions=True)
	except Exception:
		# An address that will not save must not lose the supplier with it.
		frappe.clear_last_message()
		frappe.log_error(frappe.get_traceback(), "A3 Retail: supplier address")


@frappe.whitelist()
def recent(limit: int = 30) -> dict:
	"""What this branch has bought, newest first."""
	employee = _me()
	require_permission("Purchase Invoice", "read")

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		return {"branch": employee.branch, "rows": []}

	rows = frappe.db.sql(
		"""
		select pi.name, pi.posting_date, pi.supplier, pi.bill_no, pi.grand_total,
		       pi.outstanding_amount, pi.status, pi.docstatus,
		       (select count(*) from `tabPurchase Invoice Item` it
		         where it.parent = pi.name) as line_count
		from `tabPurchase Invoice` pi
		where pi.docstatus < 2 and exists (
		      select 1 from `tabPurchase Invoice Item` it
		       where it.parent = pi.name and it.warehouse = %(warehouse)s)
		order by pi.posting_date desc, pi.creation desc
		limit %(limit)s
		""",
		{"warehouse": warehouse, "limit": min(cint(limit) or 30, 100)},
		as_dict=True,
	)
	for r in rows:
		r["supplier_name"] = frappe.db.get_value("Supplier", r["supplier"], "supplier_name")
		r["grand_total"] = flt(r["grand_total"])
		r["outstanding_amount"] = flt(r["outstanding_amount"])
	return {"branch": employee.branch, "rows": rows}


@frappe.whitelist()
def create(payload) -> dict:
	"""Record a supplier bill and take the goods into stock."""
	employee = _me()
	require_permission("Purchase Invoice", "create")

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})

	supplier = (data.get("supplier") or "").strip()
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Choose who the stock was bought from."), title=_("Supplier"))

	items = [row for row in (data.get("items") or [])
	         if row.get("item_code") and flt(row.get("qty")) > 0]
	if not items:
		frappe.throw(_("Add at least one item, with how many came in."), title=_("Items"))
	if len(items) > LINE_LIMIT:
		frappe.throw(_("That is more lines than one bill should carry."), title=_("Items"))

	posting = getdate(data.get("date") or nowdate())
	if posting > getdate(nowdate()):
		frappe.throw(_("A purchase cannot be dated in the future."), title=_("Date"))

	profile = _profile(employee.branch)
	warehouse = profile.default_warehouse
	if not warehouse:
		frappe.throw(_("This branch has no store to receive stock into."), title=_("Warehouse"))
	cost_center = profile.sales_cost_center or profile.cost_center

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.posting_date = posting
	doc.set_posting_time = 1
	doc.bill_no = (data.get("bill_no") or "").strip() or None
	doc.bill_date = posting
	# One document, not three: the goods are standing in the shop, so the bill
	# brings them into stock as it is entered.
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	if doc.meta.has_field("branch"):
		doc.branch = employee.branch

	for row in items:
		code = row["item_code"]
		if not frappe.db.exists("Item", code):
			frappe.throw(_("{0} is not an item we stock.").format(code), title=_("Items"))
		line = doc.append("items", {
			"item_code": code,
			"qty": flt(row["qty"]),
			"rate": flt(row.get("rate")),
			"warehouse": warehouse,
		})
		if cost_center:
			line.cost_center = cost_center
		serials = [s for s in (row.get("serials") or []) if s]
		if serials:
			line.use_serial_batch_fields = 1
			line.serial_no = "\n".join(serials)

	if cost_center and doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center
	if data.get("notes"):
		doc.remarks = str(data["notes"])[:500]

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()

	# Paid on the spot, or left on the supplier's account to settle later.
	paid = flt(data.get("paid_amount"))
	if paid > 0:
		_settle(doc, paid, data.get("mode_of_payment") or "Cash", employee)

	doc.reload()
	return {
		"purchase": doc.name,
		"supplier": frappe.db.get_value("Supplier", supplier, "supplier_name"),
		"grand_total": flt(doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		"print_url": f"/printview?doctype=Purchase%20Invoice&name={doc.name}",
	}


def _settle(invoice, paid: float, mode: str, employee) -> None:
	"""Pay the rep now — a Payment Entry against the bill just recorded."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	payable = flt(invoice.rounded_total) or flt(invoice.grand_total)
	if paid > payable + 0.5:
		frappe.throw(
			_("Paid amount is more than the bill of {0}.").format(frappe.format_value(
				payable, {"fieldtype": "Currency"})),
			title=_("Paid"),
		)

	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode, "company": invoice.company},
		"default_account",
	)
	if not account:
		frappe.throw(
			_("{0} has no account set for this company — head office has to add it once.").format(mode),
			title=_("Payment"),
		)

	entry = get_payment_entry("Purchase Invoice", invoice.name, party_amount=paid)
	entry.reference_no = invoice.bill_no or invoice.name
	entry.reference_date = invoice.posting_date
	entry.mode_of_payment = mode
	entry.paid_from = account
	entry.paid_amount = paid
	entry.base_paid_amount = paid
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
