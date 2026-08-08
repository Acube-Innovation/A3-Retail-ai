# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""EMI Management — the branch's financing desk (`/branch/emi`).

One workspace over machinery that already exists. The EMI Application, EMI
Scheme, Finance Partner and Financier Settlement doctypes own the rules, the
arithmetic and the accounting; this module reads them for the screen and calls
their own routines when the screen acts. It writes no ledger of its own: a
settlement posts through the Financier Settlement's Journal Entry, a sale is
still an ERPNext Sales Invoice, and the money a customer hands over at the
counter is still a Payment Entry raised by the till.

Two rules run through the whole module. Nothing about a financier is hard-coded
— partners, schemes, documents, fees and branch merchant codes are all master
data. And nothing here promises a loan: the arithmetic is the shop's own
commercial configuration, marked indicative, and the financier's answer is what
gets recorded against the application.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, nowdate

from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import (
	APPROVED,
	CANCELLED,
	DISBURSED,
	DRAFT,
	DOCS_PENDING,
	READY,
	REJECTED,
	SETTLED,
	SUBMITTED,
	UNDER_REVIEW,
	EMIApplication,
)
from a3_retail.api import parse_payload, require_permission, require_role
from a3_retail.api.staff import _me
from a3_retail.utils import money

PAGE_SIZES = (20, 50, 100)

# Where an application stands, in the colours the rest of the app uses.
TONES = {
	DRAFT: "pill-sky",
	DOCS_PENDING: "pill-warn",
	READY: "pill-sky",
	SUBMITTED: "pill-purple",
	UNDER_REVIEW: "pill-warn",
	APPROVED: "pill-good",
	REJECTED: "pill-bad",
	DISBURSED: "pill-good",
	SETTLED: "pill-good",
	CANCELLED: "pill-bad",
}

# The states that mean "still with the financier, nobody has answered yet".
PENDING_STATUSES = (SUBMITTED, UNDER_REVIEW)
# The states that mean "the shop is owed money by a financier".
OWED_STATUSES = (DISBURSED,)

SETTLEMENT_TONES = {
	"Draft": "pill-warn",
	"Reconciled": "pill-good",
	"Variance - Under Query": "pill-bad",
	"Closed": "pill-sky",
}


def _branch() -> str:
	return _me().branch


def _may_see_every_branch() -> bool:
	return bool({"A3 Retail Admin", "Accounts Manager", "System Manager"} & set(frappe.get_roles()))


def _sees_cost() -> bool:
	"""Whether this person may see what the deal costs the shop.

	MDR, subvention and net realisable sit at permlevel 1 on the application so a
	counter can process financing without seeing the margin. The screen asks the
	doctype's own permission rows rather than keeping a second list of roles.
	"""
	roles = set(frappe.get_roles())
	return any(
		row.permlevel == 1 and row.read and row.role in roles
		for row in frappe.get_meta("EMI Application").permissions
	)


def tone_of(status: str) -> str:
	return TONES.get(status, "pill-sky")


# ---------------------------------------------------------------------------
# Filters — one where-clause the whole page shares
# ---------------------------------------------------------------------------
def _filters(data: dict, alias: str = "e") -> tuple[str, dict]:
	employee = _me()
	conditions = [f"{alias}.docstatus < 2"]
	values = {"branch": employee.branch}

	wants_all = (data.get("branch") or "current") == "all"
	if not wants_all or not _may_see_every_branch():
		conditions.append(f"{alias}.branch = %(branch)s")
	elif data.get("branch") not in (None, "", "all", "current"):
		conditions.append(f"{alias}.branch = %(named_branch)s")
		values["named_branch"] = data["branch"]

	if data.get("query"):
		conditions.append(
			f"({alias}.name like %(like)s or {alias}.customer_name like %(like)s "
			f"or {alias}.customer_mobile like %(like)s or {alias}.sales_invoice like %(like)s "
			f"or {alias}.finance_partner like %(like)s or {alias}.partner_application_no like %(like)s "
			f"or {alias}.loan_account_number like %(like)s)"
		)
		values["like"] = f"%{data['query']}%"

	if data.get("from_date"):
		conditions.append(f"{alias}.application_date >= %(from_date)s")
		values["from_date"] = getdate(data["from_date"])
	if data.get("to_date"):
		conditions.append(f"{alias}.application_date <= %(to_date)s")
		values["to_date"] = getdate(data["to_date"])

	if data.get("partner"):
		conditions.append(f"{alias}.finance_partner = %(partner)s")
		values["partner"] = data["partner"]
	if data.get("scheme"):
		conditions.append(f"{alias}.emi_scheme = %(scheme)s")
		values["scheme"] = data["scheme"]
	if data.get("sales_person"):
		conditions.append(f"{alias}.sales_person = %(sales_person)s")
		values["sales_person"] = data["sales_person"]

	status = data.get("status") or "all"
	if status == "pending":
		values["pending"] = list(PENDING_STATUSES)
		conditions.append(f"{alias}.status in %(pending)s")
	elif status == "open":
		values["open"] = [DRAFT, DOCS_PENDING, READY, SUBMITTED, UNDER_REVIEW, APPROVED]
		conditions.append(f"{alias}.status in %(open)s")
	elif status != "all":
		conditions.append(f"{alias}.status = %(status)s")
		values["status"] = status

	if data.get("item_group"):
		conditions.append(
			f"exists (select 1 from `tabEMI Application Item` ai "
			f"join `tabItem` it on it.name = ai.item_code "
			f"where ai.parent = {alias}.name and it.item_group = %(item_group)s)"
		)
		values["item_group"] = data["item_group"]

	return " and ".join(conditions), values


# ---------------------------------------------------------------------------
# What the page needs before anybody touches anything
# ---------------------------------------------------------------------------
@frappe.whitelist()
def bootstrap() -> dict:
	employee = _me()
	require_permission("EMI Application", "read")

	partners = frappe.get_all(
		"Finance Partner",
		filters={"is_active": 1},
		fields=["name", "partner_name", "partner_type", "mode_of_payment", "settlement_tat_days"],
		order_by="partner_name",
	)
	schemes = frappe.get_all(
		"EMI Scheme",
		filters={"is_active": 1},
		fields=["name", "scheme_name", "finance_partner", "tenure_months"],
		order_by="finance_partner, tenure_months",
	)

	return {
		"branch": employee.branch,
		"employee": employee.employee_name,
		"company": frappe.db.get_single_value("Global Defaults", "default_company"),
		"partners": partners,
		"schemes": schemes,
		"statuses": [DRAFT, DOCS_PENDING, READY, SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED,
		             DISBURSED, SETTLED, CANCELLED],
		"settlement_statuses": list(SETTLEMENT_TONES),
		"document_types": frappe.get_all(
			"EMI Document Type",
			fields=["name", "document_name", "category", "applies_to", "is_mandatory_default",
			        "requires_expiry"],
			order_by="category, document_name"),
		"item_groups": frappe.get_all(
			"Item Group", filters={"is_group": 0}, pluck="name", order_by="name"),
		"brands": [brand for brand in frappe.get_all("Brand", pluck="name", order_by="name")
		           if not brand.startswith("_Test")],
		"branches": frappe.get_all("Branch", pluck="name", order_by="branch")
		if _may_see_every_branch() else [employee.branch],
		"sales_people": frappe.get_all(
			"Sales Person", filters={"enabled": 1}, pluck="name", order_by="name"),
		"accounts": _bank_accounts(),
		"partner_types": _select_options("Finance Partner", "partner_type"),
		"employment_types": _select_options("EMI Application", "employment_type"),
		"rejection_reasons": [reason for reason
		                      in _select_options("EMI Application", "rejection_reason") if reason],
		"all_branches": _may_see_every_branch(),
		"can": {
			"apply": bool(frappe.has_permission("EMI Application", "create")),
			"decide": bool({"EMI Coordinator", "Branch Manager", "Accounts Manager",
			                "A3 Retail Admin", "System Manager"} & set(frappe.get_roles())),
			"partner": bool(frappe.has_permission("Finance Partner", "write")),
			"scheme": bool(frappe.has_permission("EMI Scheme", "write")),
			"settle": bool(frappe.has_permission("Financier Settlement", "create")),
			"see_cost": _sees_cost(),
		},
	}


def _select_options(doctype: str, fieldname: str) -> list[str]:
	field = frappe.get_meta(doctype).get_field(fieldname)
	return (field.options or "").split("\n") if field else []


def _bank_accounts() -> list[str]:
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company or not frappe.has_permission("Account", "read"):
		return []
	return frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_type": ["in", ("Bank", "Cash")]},
		pluck="name", order_by="name", limit=60,
	)


# ---------------------------------------------------------------------------
# The cards over the workspace
# ---------------------------------------------------------------------------
@frappe.whitelist()
def kpis(filters=None) -> dict:
	"""Eight compact cards, each one a filter the page can jump to."""
	_me()
	require_permission("EMI Application", "read")
	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

	# The cards answer for the branch and the period, not for whatever the
	# applications table happens to be filtered by right now.
	scope = {key: data.get(key) for key in ("branch", "from_date", "to_date", "partner")}
	where, values = _filters({key: value for key, value in scope.items() if value})

	rows = frappe.db.sql(
		f"""
		select e.status, e.application_date, e.approval_date, e.loan_amount,
		       e.invoice_total, e.down_payment, e.sales_invoice, e.mdr_amount,
		       e.merchant_subvention_cost, e.disbursement_date
		from `tabEMI Application` e where {where}
		""",
		values,
		as_dict=True,
	)

	today = getdate(nowdate())
	month_start = today.replace(day=1)

	def total(subset, field="loan_amount") -> float:
		return money(sum(flt(row.get(field)) for row in subset))

	# A sale went out on finance the day the financier disbursed it — the invoice
	# is usually raised the same minute, but the disbursement is the event.
	sold = [row for row in rows if row.status in (DISBURSED, SETTLED) and row.disbursement_date]
	sold_today = [row for row in sold if getdate(row.disbursement_date) == today]
	sold_month = [row for row in sold if getdate(row.disbursement_date) >= month_start]
	owed = [row for row in rows if row.status in OWED_STATUSES]

	return {
		"sales_today": {"value": total(sold_today, "invoice_total"), "count": len(sold_today),
		                "money": True, "go": {"tab": "sales"}},
		"active": {"value": len([row for row in rows if row.status in (
			DOCS_PENDING, READY, SUBMITTED, UNDER_REVIEW, APPROVED)]),
			"go": {"tab": "applications", "status": "open"}},
		"pending": {"value": len([row for row in rows if row.status in PENDING_STATUSES]),
		            "go": {"tab": "applications", "status": "pending"}},
		"approved_today": {"value": len([row for row in rows if row.approval_date
		                                 and getdate(row.approval_date) == today]),
		                   "go": {"tab": "applications", "status": APPROVED}},
		"rejected": {"value": len([row for row in rows if row.status == REJECTED]),
		             "go": {"tab": "applications", "status": REJECTED}},
		"pending_settlement": {"value": total(owed), "count": len(owed), "money": True,
		                       "go": {"tab": "settlements"}},
		"month_sales": {"value": total(sold_month, "invoice_total"), "count": len(sold_month),
		                "money": True, "go": {"tab": "sales"}},
		"commission": {"value": money(sum(flt(row.mdr_amount) + flt(row.merchant_subvention_cost)
		                                  for row in rows)),
		               "count": len(rows), "money": True, "cost": True,
		               "go": {"tab": "reconciliation"}},
	}


@frappe.whitelist()
def financiers_summary(filters=None) -> list[dict]:
	"""What each partner is worth this period — read from the partner master."""
	_me()
	require_permission("EMI Application", "read")
	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	scope = {key: data.get(key) for key in ("branch", "from_date", "to_date") if data.get(key)}
	where, values = _filters(scope)

	rows = frappe.db.sql(
		f"""
		select e.finance_partner, fp.partner_type,
		       count(e.name) as application_count,
		       sum(e.loan_amount) as financed,
		       sum(case when e.status = %(approved)s then 1 else 0 end) as approved,
		       sum(case when e.status in %(pending)s then 1 else 0 end) as pending
		from `tabEMI Application` e
		left join `tabFinance Partner` fp on fp.name = e.finance_partner
		where {where} and e.finance_partner is not null
		group by e.finance_partner, fp.partner_type
		order by financed desc
		""",
		{**values, "approved": APPROVED, "pending": list(PENDING_STATUSES)},
		as_dict=True,
	)

	for row in rows:
		row["financed"] = money(row.financed)
		row["applications"] = cint(row.application_count)
	return rows


# ---------------------------------------------------------------------------
# The tabs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def tab(name: str, filters=None, page: int = 1, page_size: int = 20) -> dict:
	"""Whatever the open tab shows, in the shape the table renders."""
	_me()
	require_permission("EMI Application", "read")
	data = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

	handlers = {
		"overview": _overview,
		"applications": _applications,
		"schemes": _schemes,
		"financiers": _financiers,
		"sales": _sales,
		"settlements": _settlements,
		"documents": _documents,
		"reconciliation": _reconciliation,
	}
	handler = handlers.get(name)
	if not handler:
		frappe.throw(_("There is no {0} tab on this page.").format(name))

	if name in ("applications", "sales", "documents", "reconciliation"):
		return handler(data, cint(page) or 1, cint(page_size) or 20)
	return handler(data)


def _paged(total: int, page: int, size: int) -> dict:
	return {
		"total": total,
		"page": page,
		"page_size": size,
		"pages": max(1, -(-total // size)),
		"showing": [(page - 1) * size + 1 if total else 0, min(page * size, total)],
	}


# ------------------------------------------------------------------ overview
def _overview(data: dict) -> dict:
	"""Six short lists: what needs doing today, not a second dashboard."""
	where, values = _filters(data)

	def applications(extra_where: str, extra_values: dict, order: str, limit: int = 6):
		return frappe.db.sql(
			f"""
			select e.name, e.application_date, e.customer_name, e.customer_mobile,
			       e.finance_partner, e.emi_scheme, e.loan_amount, e.emi_amount,
			       e.tenure_months, e.status, e.branch, e.sales_invoice, e.approval_date,
			       e.rejection_reason, e.submitted_on
			from `tabEMI Application` e
			where {where} and {extra_where}
			order by {order} limit {cint(limit)}
			""",
			{**values, **extra_values},
			as_dict=True,
		)

	pending = applications("e.status in %(pending)s", {"pending": list(PENDING_STATUSES)},
	                       "e.submitted_on asc")
	approvals = applications("e.status = %(approved)s", {"approved": APPROVED},
	                         "e.approval_date desc")
	sales = applications("e.status in %(sold)s", {"sold": [DISBURSED, SETTLED]},
	                     "e.disbursement_date desc")
	rejected = applications("e.status = %(rejected)s", {"rejected": REJECTED},
	                        "e.modified desc")

	for row in pending + approvals + sales + rejected:
		row["tone"] = tone_of(row.status)
		row["waiting_days"] = (
			(getdate(nowdate()) - getdate(row.submitted_on)).days if row.submitted_on else 0
		)

	settlements = frappe.get_all(
		"Financier Settlement",
		filters={"docstatus": 0},
		fields=["name", "finance_partner", "from_date", "to_date", "net_expected",
		        "net_received", "variance", "status"],
		order_by="modified desc", limit=6,
	)
	for row in settlements:
		row["tone"] = SETTLEMENT_TONES.get(row.status, "pill-sky")

	expiring = frappe.db.sql(
		"""
		select name, scheme_name, finance_partner, tenure_months, valid_upto
		from `tabEMI Scheme`
		where is_active = 1 and valid_upto is not null and valid_upto <= %(soon)s
		order by valid_upto limit 6
		""",
		{"soon": add_months(getdate(nowdate()), 1)},
		as_dict=True,
	)

	owed = frappe.db.sql(
		f"""
		select e.finance_partner, count(e.name) as applications, sum(e.loan_amount) as amount,
		       min(e.disbursement_date) as oldest
		from `tabEMI Application` e
		where {where} and e.status in %(owed)s
		group by e.finance_partner order by amount desc limit 6
		""",
		{**values, "owed": list(OWED_STATUSES)},
		as_dict=True,
	)

	return {
		"pending": pending,
		"approvals": approvals,
		"sales": sales,
		"rejected": rejected,
		"settlements": settlements,
		"expiring": expiring,
		"owed": owed,
	}


# -------------------------------------------------------------- applications
def _applications(data: dict, page: int, size: int) -> dict:
	where, values = _filters(data)
	size = size if size in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	total = frappe.db.sql(
		f"select count(*) from `tabEMI Application` e where {where}", values)[0][0]

	rows = frappe.db.sql(
		f"""
		select e.name, e.application_date, e.customer, e.customer_name, e.customer_mobile,
		       e.sales_invoice, e.sales_order, e.finance_partner, e.emi_scheme,
		       e.invoice_total, e.loan_amount, e.down_payment, e.emi_amount, e.tenure_months,
		       e.processing_fee, e.status, e.branch, e.sales_person, e.docstatus,
		       e.partner_application_no, e.loan_account_number, e.approval_date,
		       e.rejection_reason, e.submitted_on, e.all_documents_received,
		       (select group_concat(ai.item_name separator ', ')
		          from `tabEMI Application Item` ai where ai.parent = e.name) as products
		from `tabEMI Application` e
		where {where}
		order by e.application_date desc, e.creation desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		row["tone"] = tone_of(row.status)
		row["editable"] = cint(row.docstatus) == 0
		row["documents_ok"] = bool(cint(row.all_documents_received))

	return {"rows": rows, **_paged(total, page, size)}


# -------------------------------------------------------------------- schemes
def _schemes(data: dict) -> dict:
	"""Every scheme the shop has configured, with what it costs and covers."""
	filters = {}
	if data.get("partner"):
		filters["finance_partner"] = data["partner"]
	if data.get("scheme_status") == "active":
		filters["is_active"] = 1
	elif data.get("scheme_status") == "inactive":
		filters["is_active"] = 0

	rows = frappe.get_all(
		"EMI Scheme",
		filters=filters,
		fields=["name", "scheme_name", "scheme_code", "finance_partner", "tenure_months",
		        "is_no_cost_emi", "interest_rate", "interest_type", "processing_fee",
		        "processing_fee_type", "documentation_fee", "down_payment_percent",
		        "min_down_payment", "max_down_payment", "subvention_percent",
		        "customer_subvention_percent", "cashback_amount", "min_invoice_amount",
		        "max_invoice_amount", "valid_from", "valid_upto", "is_active", "description"],
		order_by="finance_partner, tenure_months",
	)

	today = getdate(nowdate())
	for row in rows:
		row["brands"] = frappe.get_all(
			"EMI Scheme Brand", filters={"parent": row.name}, pluck="brand")
		row["item_groups"] = frappe.get_all(
			"EMI Scheme Item Group", filters={"parent": row.name}, pluck="item_group")
		row["branches"] = frappe.get_all(
			"Offer Branch", filters={"parent": row.name, "parenttype": "EMI Scheme"},
			pluck="branch")
		row["documents"] = frappe.get_all(
			"EMI Document Checklist",
			filters={"parent": row.name, "parenttype": "EMI Scheme"},
			fields=["document_type", "is_mandatory"])
		row["applications"] = frappe.db.count("EMI Application",
		                                      {"emi_scheme": row.name, "docstatus": ["<", 2]})
		expired = row.valid_upto and getdate(row.valid_upto) < today
		row["state"] = ("Expired" if expired else "Active") if row.is_active else "Inactive"
		row["tone"] = {"Active": "pill-good", "Expired": "pill-warn",
		               "Inactive": "pill-sky"}[row["state"]]

	return {"rows": rows}


# ----------------------------------------------------------------- financiers
def _financiers(data: dict) -> dict:
	"""The partner master, with what each one is carrying right now."""
	rows = frappe.get_all(
		"Finance Partner",
		fields=["name", "partner_name", "partner_type", "legal_name", "merchant_id",
		        "is_active", "settlement_tat_days", "mode_of_payment", "support_contact",
		        "support_email", "api_integration_enabled", "api_base_url", "min_ticket_size",
		        "max_ticket_size", "subvention_borne_by", "tds_applicable"],
		order_by="partner_name",
	)

	seen_cost = _sees_cost()
	for row in rows:
		row["branch_codes"] = frappe.get_all(
			"Partner Branch Code", filters={"parent": row.name},
			fields=["branch", "merchant_id", "terminal_id", "dealer_code", "settlement_account",
			        "is_active"])
		row["schemes"] = frappe.db.count("EMI Scheme",
		                                 {"finance_partner": row.name, "is_active": 1})
		row["applications"] = frappe.db.count("EMI Application",
		                                      {"finance_partner": row.name, "docstatus": ["<", 2]})
		row["approved"] = frappe.db.count(
			"EMI Application",
			{"finance_partner": row.name, "status": ["in", (APPROVED, DISBURSED, SETTLED)]})
		owed = frappe.db.sql(
			"""select sum(loan_amount) from `tabEMI Application`
			   where finance_partner = %s and docstatus = 1 and status in %s""",
			(row.name, list(OWED_STATUSES)))[0][0]
		row["pending_settlement"] = money(owed or 0)
		row["documents"] = frappe.get_all(
			"EMI Document Checklist",
			filters={"parent": row.name, "parenttype": "Finance Partner"},
			fields=["document_type", "is_mandatory"])
		row["mdr_percent"] = flt(frappe.db.get_value("Finance Partner", row.name, "mdr_percent")) \
			if seen_cost else None
		row["tone"] = "pill-good" if row.is_active else "pill-sky"
		row["integration"] = "REST API" if row.api_integration_enabled else "Manual"

	return {"rows": rows}


# ------------------------------------------------------------------ EMI sales
def _sales(data: dict, page: int, size: int) -> dict:
	"""Sales that actually went out on finance, and what each is owed."""
	where, values = _filters(data)
	size = size if size in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	# A sale on finance is one the financier has disbursed. Most carry the
	# invoice they were raised against; the ones seeded or keyed in before the
	# invoice exists still belong on this list, with the invoice column empty.
	clause = (f"{where} and (e.status in %(sold)s "
	          f"or (e.sales_invoice is not null and e.sales_invoice != ''))")
	values["sold"] = [DISBURSED, SETTLED]
	total = frappe.db.sql(
		f"select count(*) from `tabEMI Application` e where {clause}", values)[0][0]

	rows = frappe.db.sql(
		f"""
		select e.name, e.sales_invoice, e.disbursement_date, e.customer, e.customer_name,
		       e.finance_partner, e.emi_scheme, e.invoice_total, e.down_payment,
		       e.loan_amount, e.amount_received, e.status, e.settlement, e.branch,
		       si.grand_total, si.posting_date, si.docstatus as invoice_docstatus,
		       (select group_concat(ai.item_name separator ', ')
		          from `tabEMI Application Item` ai where ai.parent = e.name) as products,
		       (select group_concat(ai.serial_no separator ', ')
		          from `tabEMI Application Item` ai
		         where ai.parent = e.name and ai.serial_no != '') as imei
		from `tabEMI Application` e
		left join `tabSales Invoice` si on si.name = e.sales_invoice
		where {clause}
		order by e.disbursement_date desc, e.creation desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		row["expected"] = money(flt(row.loan_amount))
		row["received"] = money(flt(row.amount_received))
		row["customer_paid"] = money(flt(row.invoice_total) - flt(row.loan_amount))
		row["settlement_state"] = _settlement_state(row)
		row["tone"] = {"Settled": "pill-good", "Pending Settlement": "pill-warn",
		               "Partially Settled": "pill-warn", "Cancelled": "pill-bad"}.get(
			row["settlement_state"], "pill-sky")

	return {"rows": rows, **_paged(total, page, size)}


def _settlement_state(row) -> str:
	if row.status == CANCELLED:
		return "Cancelled"
	if row.status == SETTLED:
		return "Settled"
	if flt(row.amount_received) and flt(row.amount_received) < flt(row.loan_amount):
		return "Partially Settled"
	if row.status in OWED_STATUSES:
		return "Pending Settlement"
	return row.status


# --------------------------------------------------------------- settlements
def _settlements(data: dict) -> dict:
	"""What each financier owes, what arrived, and what is still short."""
	require_permission("Financier Settlement", "read")

	filters = {"docstatus": ["<", 2]}
	if data.get("partner"):
		filters["finance_partner"] = data["partner"]
	if data.get("settlement_status") and data["settlement_status"] != "all":
		filters["status"] = data["settlement_status"]

	rows = frappe.get_all(
		"Financier Settlement",
		filters=filters,
		fields=["name", "finance_partner", "from_date", "to_date", "company", "status",
		        "utr_reference", "bank_account", "gross_amount", "mdr_amount",
		        "subvention_amount", "gst_on_mdr", "tds_amount", "other_deductions",
		        "net_expected", "net_received", "variance", "docstatus", "journal_entry"],
		order_by="modified desc", limit=100,
	)
	for row in rows:
		row["tone"] = SETTLEMENT_TONES.get(row.status, "pill-sky")
		row["applications"] = frappe.db.count("Financier Settlement Item", {"parent": row.name})
		row["editable"] = cint(row.docstatus) == 0

	scope_where, scope_values = _filters(
		{key: data.get(key) for key in ("branch", "partner") if data.get(key)})
	expected = frappe.db.sql(
		f"""select sum(e.loan_amount) from `tabEMI Application` e
		    where {scope_where} and e.status in %(owed)s""",
		{**scope_values, "owed": list(OWED_STATUSES)},
	)[0][0]

	received = sum(flt(row.net_received) for row in rows if cint(row.docstatus) == 1)
	disputed = sum(flt(row.variance) for row in rows
	               if row.status == "Variance - Under Query")

	return {
		"rows": rows,
		"cards": {
			"expected": money(expected or 0),
			"received": money(received),
			"pending": money((expected or 0)),
			"disputed": money(abs(disputed)),
		},
	}


# ---------------------------------------------------------------- documents
def _documents(data: dict, page: int, size: int) -> dict:
	"""Every document on every application — what is in, and what is verified."""
	where, values = _filters(data)
	size = size if size in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	extra = ""
	state = data.get("document_status") or "all"
	if state == "missing":
		extra = " and d.is_mandatory = 1 and (d.is_received = 0 or ifnull(d.attachment, '') = '')"
	elif state == "uploaded":
		extra = " and d.is_received = 1 and d.verified = 0"
	elif state == "verified":
		extra = " and d.verified = 1"

	if data.get("document_type"):
		extra += " and d.document_type = %(document_type)s"
		values["document_type"] = data["document_type"]

	total = frappe.db.sql(
		f"""select count(*) from `tabEMI Document Checklist` d
		    join `tabEMI Application` e on e.name = d.parent
		    where d.parenttype = 'EMI Application' and {where}{extra}""",
		values,
	)[0][0]

	rows = frappe.db.sql(
		f"""
		select d.name as row_name, d.parent as application, d.document_type, d.is_mandatory,
		       d.is_received, d.verified, d.verified_by, d.expiry_date, d.document_number,
		       d.attachment, d.remarks, e.customer_name, e.finance_partner, e.status,
		       e.branch, e.application_date, dt.category
		from `tabEMI Document Checklist` d
		join `tabEMI Application` e on e.name = d.parent
		left join `tabEMI Document Type` dt on dt.name = d.document_type
		where d.parenttype = 'EMI Application' and {where}{extra}
		order by e.application_date desc, d.idx
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		row["state"] = _document_state(row)
		row["tone"] = {"Verified": "pill-good", "Uploaded": "pill-warn",
		               "Required": "pill-bad", "Optional": "pill-sky"}[row["state"]]
		# The file itself is reached through Frappe's own file route, which
		# applies the document's permissions; the table only says it is there.
		row["has_file"] = bool(row.attachment)
		row.pop("attachment", None)
		row["document_number"] = _mask(row.document_number)

	return {"rows": rows, **_paged(total, page, size)}


def _document_state(row) -> str:
	if cint(row.verified):
		return "Verified"
	if cint(row.is_received):
		return "Uploaded"
	return "Required" if cint(row.is_mandatory) else "Optional"


def _mask(value: str | None) -> str | None:
	"""A document number is shown by its tail — enough to match, not to copy."""
	if not value:
		return value
	text = str(value).strip()
	if len(text) <= 4:
		return text
	return "•" * (len(text) - 4) + text[-4:]


# ------------------------------------------------------------ reconciliation
def _reconciliation(data: dict, page: int, size: int) -> dict:
	"""The sale, the application and the settlement, side by side."""
	where, values = _filters(data)
	size = size if size in PAGE_SIZES else 20
	values.update({"start": (page - 1) * size, "size": size})

	clause = f"{where} and e.docstatus = 1 and e.status in %(live)s"
	values["live"] = [DISBURSED, SETTLED]

	total = frappe.db.sql(
		f"select count(*) from `tabEMI Application` e where {clause}", values)[0][0]

	rows = frappe.db.sql(
		f"""
		select e.name, e.sales_invoice, e.customer_name, e.finance_partner, e.emi_scheme,
		       e.loan_amount, e.amount_received, e.settlement, e.status, e.branch,
		       e.disbursement_date, e.mdr_amount, e.merchant_subvention_cost,
		       si.grand_total, si.outstanding_amount
		from `tabEMI Application` e
		left join `tabSales Invoice` si on si.name = e.sales_invoice
		where {clause}
		order by e.disbursement_date desc
		limit %(start)s, %(size)s
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		expected = money(flt(row.loan_amount) - flt(row.mdr_amount)
		                 - flt(row.merchant_subvention_cost))
		actual = money(flt(row.amount_received))
		row["expected"] = expected
		row["actual"] = actual
		# Until the financier has paid there is nothing to compare — an unsettled
		# sale is not a shortfall, and colouring it red says the wrong thing.
		row["difference"] = money(actual - expected) if row.settlement else None
		row["state"] = _match_state(row, expected, actual)
		row["tone"] = {"Matched": "pill-good", "Short settled": "pill-bad",
		               "Over settled": "pill-warn", "Awaiting settlement": "pill-sky"}[row["state"]]

	return {"rows": rows, **_paged(total, page, size)}


def _match_state(row, expected: float, actual: float) -> str:
	if not row.settlement:
		return "Awaiting settlement"
	if abs(actual - expected) <= 1:
		return "Matched"
	return "Short settled" if actual < expected else "Over settled"


# ---------------------------------------------------------------------------
# One application
# ---------------------------------------------------------------------------
def _open_application(name: str):
	"""The application, once this branch is allowed to see it."""
	employee = _me()
	require_permission("EMI Application", "read")

	if not frappe.db.exists("EMI Application", name):
		frappe.throw(_("There is no application numbered {0}.").format(name),
		             title=_("Application not found"))

	doc = frappe.get_doc("EMI Application", name)
	if doc.branch and doc.branch != employee.branch and not _may_see_every_branch():
		frappe.throw(_("That application belongs to another branch."), title=_("Not this branch"))
	return doc


@frappe.whitelist()
def application(name: str) -> dict:
	"""Everything the application view shows, read from the application itself."""
	doc = _open_application(name)
	scheme = frappe.get_cached_doc("EMI Scheme", doc.emi_scheme) if doc.emi_scheme else None
	partner = frappe.get_cached_doc("Finance Partner", doc.finance_partner) \
		if doc.finance_partner else None
	see_cost = _sees_cost()

	return {
		"name": doc.name,
		"status": doc.status,
		"tone": tone_of(doc.status),
		"docstatus": cint(doc.docstatus),
		"editable": cint(doc.docstatus) == 0 and doc.status not in (APPROVED, DISBURSED, SETTLED),
		"branch": doc.branch,
		"company": doc.company,
		"application_date": str(doc.application_date or ""),
		"customer": {
			"name": doc.customer,
			"customer_name": doc.customer_name,
			"mobile_no": doc.customer_mobile,
			"email": doc.customer_email,
			"date_of_birth": str(doc.date_of_birth or ""),
			"employment_type": doc.employment_type,
			"monthly_income": flt(doc.monthly_income),
			# Never the whole number on a screen anybody can walk past.
			"pan": _mask(doc.pan_number),
			"aadhaar": f"XXXX XXXX {doc.aadhaar_last4}" if doc.aadhaar_last4 else None,
			"existing_customer": bool(cint(doc.existing_customer_of_partner)),
			"existing_loan_account": doc.existing_loan_account,
		},
		"items": [
			{"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty),
			 "rate": flt(row.rate), "amount": flt(row.amount), "serial_no": row.serial_no,
			 "item_group": frappe.db.get_value("Item", row.item_code, "item_group"),
			 "brand": frappe.db.get_value("Item", row.item_code, "brand")}
			for row in doc.get("items") or []
		],
		"purchase": {
			"invoice": doc.sales_invoice,
			"sales_order": doc.sales_order,
			"invoice_total": flt(doc.invoice_total),
			"grand_total": flt(frappe.db.get_value("Sales Invoice", doc.sales_invoice,
			                                       "grand_total")) if doc.sales_invoice else None,
			"posting_date": str(frappe.db.get_value("Sales Invoice", doc.sales_invoice,
			                                        "posting_date") or "")
			if doc.sales_invoice else "",
		},
		"finance": {
			"partner": doc.finance_partner,
			"partner_type": partner.partner_type if partner else None,
			"scheme": doc.emi_scheme,
			"scheme_name": scheme.scheme_name if scheme else None,
			"no_cost": bool(cint(scheme.is_no_cost_emi)) if scheme else False,
			"interest_rate": flt(scheme.interest_rate) if scheme else 0,
			"interest_type": (scheme.get("interest_type") if scheme else None) or "Flat",
			"partner_application_no": doc.partner_application_no,
			"loan_account_number": doc.loan_account_number,
			"merchant_id": _merchant_id(doc),
			"submission_mode": "REST API" if partner and partner.api_integration_enabled
			else "Manual",
		},
		"loan": {
			"invoice_total": flt(doc.invoice_total),
			"down_payment": flt(doc.down_payment),
			"loan_amount": flt(doc.loan_amount),
			"approved_loan_amount": flt(doc.approved_loan_amount),
			"processing_fee": flt(doc.processing_fee),
			"documentation_fee": flt(doc.documentation_fee),
			"other_charges": flt(doc.other_charges),
			"customer_payable_today": flt(doc.customer_payable_today),
			"emi_amount": flt(doc.emi_amount),
			"tenure_months": cint(doc.tenure_months),
			"first_emi_date": str(doc.first_emi_date or ""),
			"last_emi_date": str(doc.last_emi_date or ""),
			"total_repayment": money(flt(doc.emi_amount) * cint(doc.tenure_months)),
		},
		# What the deal costs the shop is permlevel 1 on the doctype; the screen
		# keeps the same line.
		"cost": {
			"mdr": flt(doc.mdr_amount),
			"merchant_subvention": flt(doc.merchant_subvention_cost),
			"net_realisable": flt(doc.net_realisable),
			"amount_received": flt(doc.amount_received),
		} if see_cost else None,
		"progress": {
			"kyc": "Complete" if cint(doc.all_documents_received) else "Pending",
			"approval": doc.status if doc.status in (APPROVED, REJECTED, UNDER_REVIEW, SUBMITTED)
			else ("Not sent" if doc.status in (DRAFT, DOCS_PENDING, READY) else doc.status),
			"approval_date": str(doc.approval_date or ""),
			"disbursement": str(doc.disbursement_date or ""),
			"settlement": doc.settlement,
			"rejection_reason": doc.rejection_reason,
			"rejection_remarks": doc.rejection_remarks,
			"cibil": cint(doc.cibil_score) or None,
		},
		"documents": _application_documents(doc),
		"timeline": timeline(doc.name),
		"sales_person": doc.sales_person,
		"coordinator": frappe.db.get_value("Employee", doc.coordinator, "employee_name")
		if doc.coordinator else None,
		"notes": doc.get("notes"),
		"can": _can(doc),
		"print_url": print_url(doc.name),
		"checklist_url": print_url(doc.name, "EMI Document Checklist"),
		"invoice_url": f"/branch/invoice?name={frappe.utils.quoted(doc.sales_invoice)}"
		if doc.sales_invoice else None,
	}


def _merchant_id(doc) -> str | None:
	"""This branch's own merchant code with the partner, if it has one."""
	if not doc.finance_partner:
		return None
	row = frappe.db.get_value(
		"Partner Branch Code",
		{"parent": doc.finance_partner, "branch": doc.branch},
		["merchant_id", "terminal_id", "dealer_code"], as_dict=True,
	)
	if row:
		return " · ".join([value for value in
		                   (row.merchant_id, row.terminal_id, row.dealer_code) if value])
	return frappe.db.get_value("Finance Partner", doc.finance_partner, "merchant_id")


def _application_documents(doc) -> list[dict]:
	rows = []
	for row in doc.get("documents") or []:
		meta = frappe.db.get_value(
			"EMI Document Type", row.document_type, ["category", "requires_expiry", "instructions"],
			as_dict=True) or frappe._dict()
		rows.append({
			"row": row.name,
			"document_type": row.document_type,
			"category": meta.get("category"),
			"instructions": meta.get("instructions"),
			"requires_expiry": bool(cint(meta.get("requires_expiry"))),
			"is_mandatory": bool(cint(row.is_mandatory)),
			"is_received": bool(cint(row.is_received)),
			"verified": bool(cint(row.verified)),
			"verified_by": row.verified_by,
			"document_number": _mask(row.document_number),
			"expiry_date": str(row.expiry_date or ""),
			"remarks": row.remarks,
			"has_file": bool(row.attachment),
			"file_url": row.attachment,
			"state": _document_state(row),
		})
	return rows


def _can(doc) -> dict:
	roles = set(frappe.get_roles())
	decider = bool({"EMI Coordinator", "Branch Manager", "Accounts Manager", "A3 Retail Admin",
	                "System Manager"} & roles)
	return {
		"edit": cint(doc.docstatus) == 0
		and bool(frappe.has_permission("EMI Application", "write", doc)),
		"submit_to_financier": doc.status in (READY, DOCS_PENDING) and decider,
		"decide": doc.status in (SUBMITTED, UNDER_REVIEW) and decider,
		"cancel": doc.status not in (SETTLED, CANCELLED)
		and bool(frappe.has_permission("EMI Application", "write", doc)),
		"upload": bool(frappe.has_permission("EMI Application", "write", doc)),
		"verify": decider,
	}


@frappe.whitelist()
def timeline(name: str) -> list[dict]:
	"""What has happened to this application, in the order it happened."""
	doc = _open_application(name)
	# The business date, not the row's creation stamp: a card keyed in later still
	# belongs on the day the customer applied.
	events = [{"kind": "created", "label": _("Application created"),
	           "at": str(doc.application_date or doc.creation), "by": _owner_name(doc.owner),
	           "note": _("{0} · {1}").format(doc.finance_partner or "", doc.emi_scheme or "")}]

	if cint(doc.all_documents_received):
		events.append({"kind": "kyc", "label": _("Documents complete"),
		               "at": str(doc.modified), "by": _employee_name(doc.documents_verified_by),
		               "note": _("{0} documents on file").format(len(doc.get("documents") or []))})

	if doc.submitted_on:
		events.append({"kind": "submitted",
		               "label": _("Submitted to {0}").format(doc.finance_partner),
		               "at": str(doc.submitted_on), "by": "",
		               "note": doc.partner_application_no})

	if doc.approval_date:
		events.append({"kind": "approved", "label": _("Approved"), "at": str(doc.approval_date),
		               "by": "", "note": _("Loan account {0}").format(doc.loan_account_number)
		               if doc.loan_account_number else ""})

	if doc.status == REJECTED:
		events.append({"kind": "rejected", "label": _("Rejected"), "at": str(doc.modified),
		               "by": "", "note": doc.rejection_reason or doc.rejection_remarks})

	if doc.sales_invoice:
		events.append({"kind": "invoice", "label": _("Sale completed"),
		               "at": str(doc.disbursement_date or doc.modified), "by": "",
		               "note": doc.sales_invoice})

	if doc.settlement:
		settled_on = frappe.db.get_value("Financier Settlement", doc.settlement, "modified")
		events.append({"kind": "settled", "label": _("Financier settled"),
		               "at": str(settled_on or doc.modified), "by": "",
		               "note": _("{0} · {1}").format(
			               doc.settlement,
			               frappe.utils.fmt_money(flt(doc.amount_received), currency="INR"))})

	for row in frappe.get_all(
		"Comment",
		filters={"reference_doctype": "EMI Application", "reference_name": doc.name,
		         "comment_type": "Comment"},
		fields=["content", "comment_by", "comment_email", "creation"], order_by="creation",
	):
		events.append({"kind": "note", "label": _("Note"), "at": str(row.creation),
		               "by": row.comment_by or row.comment_email,
		               "note": frappe.utils.strip_html(row.content or "").strip()})

	events.sort(key=lambda event: str(event["at"] or ""))
	return events


def _owner_name(user: str | None) -> str:
	return frappe.db.get_value("User", user, "full_name") or (user or "")


def _employee_name(employee: str | None) -> str:
	return frappe.db.get_value("Employee", employee, "employee_name") if employee else ""


# ---------------------------------------------------------------------------
# Writing an application
# ---------------------------------------------------------------------------
@frappe.whitelist()
def save_application(payload) -> dict:
	"""Create or update a draft. The doctype validates; this only fills it in."""
	employee = _me()
	require_permission("EMI Application", "create")
	data = parse_payload(payload)

	if data.get("name"):
		doc = _open_application(data["name"])
		if cint(doc.docstatus) != 0:
			frappe.throw(
				_("{0} has already been submitted, so its terms cannot be edited. Record the "
				  "financier's answer instead, or cancel it.").format(doc.name),
				title=_("Already submitted"),
			)
	else:
		doc = frappe.new_doc("EMI Application")
		doc.branch = employee.branch

	customer = data.get("customer")
	if not customer:
		if not data.get("mobile_no"):
			frappe.throw(_("A financing application needs the customer's mobile number."),
			             title=_("Customer needed"))
		from a3_retail.api.customer import get_or_create

		customer = get_or_create(
			mobile_no=data.get("mobile_no"),
			customer_name=data.get("customer_name"),
			branch=employee.branch,
		)["name"]

	doc.customer = customer
	doc.customer_mobile = data.get("mobile_no") or doc.customer_mobile
	doc.customer_email = data.get("email") or doc.customer_email
	doc.date_of_birth = data.get("date_of_birth") or None
	doc.employment_type = data.get("employment_type") or doc.employment_type
	doc.monthly_income = flt(data.get("monthly_income"))
	if data.get("pan"):
		doc.pan_number = data["pan"]
	if data.get("aadhaar_last4"):
		doc.aadhaar_last4 = str(data["aadhaar_last4"])[-4:]
	doc.existing_customer_of_partner = cint(data.get("existing_customer"))
	doc.existing_loan_account = data.get("existing_loan_account")

	if data.get("sales_invoice"):
		# The invoice is the source of truth for what was sold and for how much.
		_load_invoice(doc, data["sales_invoice"])
	else:
		if data.get("items"):
			doc.set("items", [])
			for line in data["items"]:
				if not line.get("item_code"):
					continue
				doc.append("items", {
					"item_code": line["item_code"],
					"item_name": line.get("item_name"),
					"qty": flt(line.get("qty")) or 1,
					"rate": flt(line.get("rate")),
					"serial_no": line.get("serial_no"),
				})

		# A pre-approval taken before anything is picked out has a figure but no
		# lines, so the total is carried on its own.
		if flt(data.get("invoice_total")):
			doc.invoice_total = flt(data["invoice_total"])
		elif doc.get("items"):
			doc.invoice_total = money(
				sum(flt(row.rate) * (flt(row.qty) or 1) for row in doc.items))

	if not flt(doc.invoice_total):
		frappe.throw(
			_("What does the purchase come to? Load the invoice, or type the total the "
			  "customer is financing."),
			title=_("Nothing to finance"),
		)

	doc.finance_partner = data.get("partner") or doc.finance_partner
	doc.emi_scheme = data.get("scheme") or doc.emi_scheme
	doc.down_payment = flt(data.get("down_payment"))
	if data.get("processing_fee") is not None:
		doc.processing_fee = flt(data.get("processing_fee"))
	doc.documentation_fee = flt(data.get("documentation_fee"))
	doc.other_charges = flt(data.get("other_charges"))
	doc.sales_person = data.get("sales_person") or doc.sales_person
	doc.coordinator = doc.coordinator or employee.name
	doc.notes = data.get("notes") or doc.get("notes")

	if not doc.finance_partner:
		frappe.throw(_("Pick the financier this application goes to."), title=_("Financier needed"))
	if not doc.emi_scheme:
		frappe.throw(_("Pick the scheme the customer is taking."), title=_("Scheme needed"))

	_check_kyc(doc)
	doc.save()
	return {"application": doc.name, "status": doc.status,
	        "missing_documents": doc.missing_documents()}


def _check_kyc(doc):
	"""Say what a financier still needs, in one sentence, before the save fails.

	The doctype makes these mandatory for good reason — no financier takes an
	application without them — but ERPNext's own answer is "Value missing for
	EMI Application: PAN", which is not something a counter can act on.
	"""
	wanted = []
	if not doc.employment_type:
		wanted.append(_("what the customer does for a living"))
	if not doc.pan_number:
		wanted.append(_("their PAN"))
	if not doc.aadhaar_last4:
		wanted.append(_("the last four digits of their Aadhaar"))

	if wanted:
		frappe.throw(
			_("Every financier asks for {0} before it will look at an application. Go back to "
			  "the customer step and fill that in.").format(", ".join(wanted)),
			title=_("The financier needs more about the customer"),
		)


def _load_invoice(doc, invoice: str):
	"""Take the sale as it stands — this module never re-prices anything."""
	employee = _me()
	require_permission("Sales Invoice", "read")

	sales = frappe.get_doc("Sales Invoice", invoice)
	if sales.branch and sales.branch != employee.branch and not _may_see_every_branch():
		frappe.throw(_("That invoice belongs to another branch."), title=_("Not this branch"))
	if cint(sales.docstatus) == 2:
		frappe.throw(_("{0} has been cancelled.").format(invoice))

	doc.sales_invoice = invoice if cint(sales.docstatus) == 1 else None
	doc.customer = sales.customer
	doc.invoice_total = flt(sales.rounded_total) or flt(sales.grand_total)
	doc.set("items", [])
	for row in sales.get("items") or []:
		doc.append("items", {
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"rate": flt(row.rate),
			"serial_no": (row.serial_no or "").split("\n")[0] if row.get("serial_no") else None,
		})


@frappe.whitelist()
def submit_application(name: str, partner_application_no: str | None = None) -> dict:
	"""Send it to the financier — the doctype's own submission."""
	from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import (
		submit_to_financier,
	)

	doc = _open_application(name)
	if cint(doc.docstatus) == 0:
		missing = doc.missing_documents()
		if missing:
			frappe.throw(
				_("These documents are still missing: {0}. Upload them, or take them off the "
				  "checklist if this scheme does not need them.").format(", ".join(missing)),
				title=_("Documents incomplete"),
			)
		doc.submit()

	return submit_to_financier(name, partner_application_no)


@frappe.whitelist()
def decide(name: str, decision: str, partner_application_no: str | None = None,
           approved_loan_amount: float | None = None, loan_account_number: str | None = None,
           rejection_reason: str | None = None, remarks: str | None = None,
           cibil_score: int | None = None) -> dict:
	"""Record what the financier answered. The financier decides, not this page."""
	from a3_retail.a3_retail_finance.doctype.emi_application.emi_application import record_decision

	doc = _open_application(name)
	if cibil_score:
		doc.db_set("cibil_score", cint(cibil_score), update_modified=False)

	result = record_decision(
		application=doc.name, decision=decision,
		partner_application_no=partner_application_no,
		approved_loan_amount=approved_loan_amount,
		loan_account_number=loan_account_number,
		rejection_reason=rejection_reason, remarks=remarks,
	)
	return result


@frappe.whitelist()
def cancel_application(name: str, reason: str | None = None) -> dict:
	"""Cancel it, and keep the record. Nothing here deletes an application."""
	doc = _open_application(name)
	require_permission("EMI Application", "write", doc)

	if doc.status == SETTLED:
		frappe.throw(_("{0} has already been settled by the financier. Reverse the settlement "
		               "first.").format(doc.name), title=_("Already settled"))
	if doc.sales_invoice:
		frappe.throw(
			_("{0} is attached to invoice {1}. Cancel or return the invoice first — the sale "
			  "and the loan have to come apart together.").format(doc.name, doc.sales_invoice),
			title=_("The sale is still live"),
		)

	if cint(doc.docstatus) == 1:
		doc.cancel()
	else:
		doc.status = CANCELLED
		doc.rejection_remarks = reason or doc.rejection_remarks
		doc.save()

	if reason:
		doc.add_comment("Comment", _("Cancelled: {0}").format(reason))
	return {"application": doc.name, "status": CANCELLED}


@frappe.whitelist()
def add_note(name: str, text: str) -> dict:
	doc = _open_application(name)
	require_permission("EMI Application", "write", doc)

	text = (text or "").strip()
	if not text:
		frappe.throw(_("Write the note first."), title=_("Nothing to add"))
	comment = doc.add_comment("Comment", text)
	return {"comment": comment.name}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@frappe.whitelist()
def attach_document(name: str, row: str, file_url: str, document_number: str | None = None,
                    expiry_date: str | None = None) -> dict:
	"""Record a file against a checklist row.

	The file itself is uploaded through Frappe's own upload endpoint and stored
	as a File attached to this application, so its permissions, its owner and
	its audit trail are the platform's. Nothing is kept in a text field here.
	"""
	doc = _open_application(name)
	require_permission("EMI Application", "write", doc)

	target = next((line for line in doc.get("documents") or [] if line.name == row), None)
	if not target:
		frappe.throw(_("That document is not on this application's checklist."))

	target.attachment = file_url
	target.is_received = 1
	if document_number:
		target.document_number = document_number
	if expiry_date:
		target.expiry_date = getdate(expiry_date)

	doc.flags.ignore_permissions = False
	doc.save()
	return {"application": doc.name, "state": _document_state(target),
	        "all_received": bool(cint(doc.all_documents_received)),
	        "missing": doc.missing_documents()}


@frappe.whitelist()
def verify_document(name: str, row: str, verified: int = 1, remarks: str | None = None) -> dict:
	"""Somebody with authority says the paperwork is genuine."""
	require_role("EMI Coordinator", "Branch Manager", "Accounts Manager", "A3 Retail Admin")

	doc = _open_application(name)
	target = next((line for line in doc.get("documents") or [] if line.name == row), None)
	if not target:
		frappe.throw(_("That document is not on this application's checklist."))
	if not cint(target.is_received):
		frappe.throw(_("{0} has not been uploaded yet.").format(target.document_type),
		             title=_("Nothing to verify"))

	target.verified = cint(verified)
	target.verified_by = frappe.session.user if cint(verified) else None
	if remarks:
		target.remarks = remarks
	doc.documents_verified_by = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user}, "name") or doc.documents_verified_by
	doc.save()

	return {"application": doc.name, "state": _document_state(target)}


# ---------------------------------------------------------------------------
# Schemes, partners — the masters this page maintains
# ---------------------------------------------------------------------------
@frappe.whitelist()
def eligible_schemes(invoice_total: float = 0, partner: str | None = None,
                     item_code: str | None = None, brand: str | None = None,
                     item_group: str | None = None, customer: str | None = None,
                     branch: str | None = None) -> list[dict]:
	"""The schemes this cart can actually take — the service the POS consumes.

	Validity, ticket size, brand, item group and branch are all checked here so
	the counter is never offered a scheme the application would then refuse.
	The instalment on each card is the shop's own arithmetic and is marked
	indicative: the financier's portal decides the real one.
	"""
	employee = _me()
	require_permission("EMI Scheme", "read")

	branch = branch or employee.branch
	total = flt(invoice_total)
	today = getdate(nowdate())

	if item_code and not (brand and item_group):
		item = frappe.get_cached_value("Item", item_code, ["brand", "item_group"], as_dict=True)
		if item:
			brand = brand or item.brand
			item_group = item_group or item.item_group

	filters = {"is_active": 1}
	if partner:
		filters["finance_partner"] = partner

	schemes = frappe.get_all(
		"EMI Scheme", filters=filters,
		fields=["name", "scheme_name", "scheme_code", "finance_partner", "tenure_months",
		        "is_no_cost_emi", "interest_rate", "interest_type", "processing_fee",
		        "processing_fee_type", "documentation_fee", "down_payment_percent",
		        "min_down_payment", "max_down_payment", "subvention_percent",
		        "customer_subvention_percent", "cashback_amount", "min_invoice_amount",
		        "max_invoice_amount", "valid_from", "valid_upto", "description"],
		order_by="tenure_months",
	)

	active_partners = set(frappe.get_all("Finance Partner", filters={"is_active": 1}, pluck="name"))
	result = []

	for scheme in schemes:
		if scheme.finance_partner not in active_partners:
			continue
		if scheme.valid_from and getdate(scheme.valid_from) > today:
			continue
		if scheme.valid_upto and getdate(scheme.valid_upto) < today:
			continue
		if total:
			if flt(scheme.min_invoice_amount) and total < flt(scheme.min_invoice_amount):
				continue
			if flt(scheme.max_invoice_amount) and total > flt(scheme.max_invoice_amount):
				continue

		branches = frappe.get_all(
			"Offer Branch", filters={"parent": scheme.name, "parenttype": "EMI Scheme"},
			pluck="branch")
		if branches and branch not in branches:
			continue

		brands = frappe.get_all("EMI Scheme Brand", filters={"parent": scheme.name}, pluck="brand")
		if brands and brand and brand not in brands:
			continue
		groups = frappe.get_all("EMI Scheme Item Group", filters={"parent": scheme.name},
		                        pluck="item_group")
		if groups and item_group and item_group not in groups:
			continue

		result.append(_quote(scheme, total))

	# A partner the branch has no merchant code with cannot be sold here.
	codes = _branch_partners(branch)
	if codes:
		result = [row for row in result if row["finance_partner"] in codes]

	result.sort(key=lambda row: (row["finance_partner"], row["tenure_months"]))
	return result


def _branch_partners(branch: str) -> set[str]:
	"""Partners that name this branch — empty when nobody configures branches."""
	rows = frappe.get_all("Partner Branch Code", filters={"branch": branch},
	                      fields=["parent", "is_active"])
	if not rows:
		return set()
	configured = {row.parent for row in rows}
	active = {row.parent for row in rows if cint(row.is_active)}
	# Partners that use branch codes at all must have this branch switched on;
	# partners that use none are available everywhere.
	everywhere = set(frappe.get_all("Finance Partner", filters={"is_active": 1}, pluck="name")) \
		- {row.parent for row in frappe.get_all("Partner Branch Code", fields=["parent"])}
	return (active & configured) | everywhere


def _quote(scheme: dict, total: float) -> dict:
	"""The shop's own indicative arithmetic for one scheme."""
	down_payment = max(flt(scheme.get("min_down_payment")),
	                   money(total * flt(scheme.get("down_payment_percent")) / 100))
	if flt(scheme.get("max_down_payment")):
		down_payment = min(down_payment, flt(scheme["max_down_payment"]))

	loan = money(max(total - down_payment, 0))
	fee = (money(total * flt(scheme.get("processing_fee")) / 100)
	       if scheme.get("processing_fee_type") == "Percentage"
	       else flt(scheme.get("processing_fee")))

	emi = money(EMIApplication.compute_emi(
		loan, cint(scheme.get("tenure_months")), flt(scheme.get("interest_rate")),
		scheme.get("interest_type") or "Flat"))

	quote = dict(scheme)
	quote.update({
		"suggested_down_payment": money(down_payment),
		"loan_amount": loan,
		"emi_amount": emi,
		"processing_fee_amount": money(fee),
		"documentation_fee": flt(scheme.get("documentation_fee")),
		"customer_payable_today": money(down_payment + fee + flt(scheme.get("documentation_fee"))),
		"total_repayment": money(emi * cint(scheme.get("tenure_months"))),
		"total_interest": money(emi * cint(scheme.get("tenure_months")) - loan),
		"indicative": True,
	})
	return quote


@frappe.whitelist()
def calculate(price: float, down_payment: float = 0, interest_rate: float = 0,
              tenure_months: int = 12, interest_type: str = "Flat",
              processing_fee: float = 0, other_charges: float = 0) -> dict:
	"""The calculator popup. Indicative — it approves nothing and quotes nobody."""
	_me()
	price = flt(price)
	down = min(flt(down_payment), price)
	loan = money(price - down)
	emi = money(EMIApplication.compute_emi(loan, cint(tenure_months), flt(interest_rate),
	                                       interest_type))
	repayment = money(emi * cint(tenure_months))

	return {
		"loan_amount": loan,
		"emi_amount": emi,
		"tenure_months": cint(tenure_months),
		"total_interest": money(repayment - loan),
		"total_repayment": repayment,
		"customer_payable_today": money(down + flt(processing_fee) + flt(other_charges)),
		"total_cost": money(repayment + down + flt(processing_fee) + flt(other_charges)),
		"indicative": True,
	}


@frappe.whitelist()
def save_scheme(payload) -> dict:
	"""Create or update a scheme — the shop's commercial configuration."""
	_me()
	require_permission("EMI Scheme", "write")
	data = parse_payload(payload)

	name = data.get("name")
	if name and frappe.db.exists("EMI Scheme", name):
		doc = frappe.get_doc("EMI Scheme", name)
	else:
		doc = frappe.new_doc("EMI Scheme")
		doc.scheme_name = (data.get("scheme_name") or "").strip()
		if not doc.scheme_name:
			frappe.throw(_("Give the scheme a name the counter will recognise."),
			             title=_("Name needed"))

	if not data.get("finance_partner"):
		frappe.throw(_("A scheme belongs to a financier — pick one."), title=_("Financier needed"))

	for field in ("finance_partner", "scheme_code", "description", "notes"):
		if data.get(field) is not None:
			doc.set(field, data.get(field))

	doc.tenure_months = cint(data.get("tenure_months")) or doc.tenure_months
	doc.is_no_cost_emi = cint(data.get("is_no_cost_emi"))
	doc.interest_rate = 0 if doc.is_no_cost_emi else flt(data.get("interest_rate"))
	doc.interest_type = data.get("interest_type") or "Flat"
	doc.processing_fee = flt(data.get("processing_fee"))
	doc.processing_fee_type = data.get("processing_fee_type") or "Fixed"
	doc.documentation_fee = flt(data.get("documentation_fee"))
	doc.down_payment_percent = flt(data.get("down_payment_percent"))
	doc.min_down_payment = flt(data.get("min_down_payment"))
	doc.max_down_payment = flt(data.get("max_down_payment"))
	doc.subvention_percent = flt(data.get("subvention_percent"))
	doc.customer_subvention_percent = flt(data.get("customer_subvention_percent"))
	doc.cashback_amount = flt(data.get("cashback_amount"))
	doc.min_invoice_amount = flt(data.get("min_invoice_amount"))
	doc.max_invoice_amount = flt(data.get("max_invoice_amount"))
	doc.valid_from = data.get("valid_from") or None
	doc.valid_upto = data.get("valid_upto") or None
	doc.is_active = cint(data.get("is_active", 1))

	if data.get("brands") is not None:
		doc.set("applicable_brands", [{"brand": brand} for brand in data["brands"] if brand])
	if data.get("item_groups") is not None:
		doc.set("applicable_item_groups",
		        [{"item_group": group} for group in data["item_groups"] if group])
	if data.get("branches") is not None:
		doc.set("applicable_branches", [{"branch": branch} for branch in data["branches"] if branch])
	if data.get("documents") is not None:
		doc.set("required_documents", [
			{"document_type": row.get("document_type"),
			 "is_mandatory": cint(row.get("is_mandatory"))}
			for row in data["documents"] if row.get("document_type")
		])

	doc.save()
	return {"scheme": doc.name, "is_active": bool(cint(doc.is_active))}


@frappe.whitelist()
def set_scheme_active(name: str, active: int = 1) -> dict:
	_me()
	require_permission("EMI Scheme", "write")
	doc = frappe.get_doc("EMI Scheme", name)
	doc.is_active = cint(active)
	doc.save()
	return {"scheme": doc.name, "is_active": bool(cint(doc.is_active))}


@frappe.whitelist()
def save_partner(payload) -> dict:
	"""Create or update a financing partner, branch codes and all.

	Credentials are never handled here: `api_key` is a Password field on the
	doctype, written and read server-side only, and this endpoint refuses to
	carry one from a browser.
	"""
	_me()
	require_permission("Finance Partner", "write")
	data = parse_payload(payload)

	if data.get("api_key"):
		frappe.throw(
			_("API credentials are not set from this screen. A system administrator stores them "
			  "on the Finance Partner record itself."),
			title=_("Not from here"),
		)

	name = data.get("name")
	if name and frappe.db.exists("Finance Partner", name):
		doc = frappe.get_doc("Finance Partner", name)
	else:
		doc = frappe.new_doc("Finance Partner")
		doc.partner_name = (data.get("partner_name") or "").strip()
		if not doc.partner_name:
			frappe.throw(_("Give the financier a name."), title=_("Name needed"))

	for field in ("partner_type", "legal_name", "gstin", "merchant_id", "mode_of_payment",
	              "settlement_account", "mdr_expense_account", "subvention_borne_by",
	              "support_contact", "support_email", "api_base_url"):
		if data.get(field) is not None:
			doc.set(field, data.get(field))

	doc.is_active = cint(data.get("is_active", 1))
	doc.settlement_tat_days = cint(data.get("settlement_tat_days"))
	doc.mdr_percent = flt(data.get("mdr_percent"))
	doc.tds_applicable = cint(data.get("tds_applicable"))
	doc.min_ticket_size = flt(data.get("min_ticket_size"))
	doc.max_ticket_size = flt(data.get("max_ticket_size"))
	doc.api_integration_enabled = cint(data.get("api_integration_enabled"))

	if data.get("branch_codes") is not None:
		doc.set("branch_merchant_ids", [
			{"branch": row.get("branch"), "merchant_id": row.get("merchant_id"),
			 "terminal_id": row.get("terminal_id"), "dealer_code": row.get("dealer_code"),
			 "settlement_account": row.get("settlement_account"),
			 "is_active": cint(row.get("is_active", 1))}
			for row in data["branch_codes"] if row.get("branch")
		])
	if data.get("documents") is not None:
		doc.set("required_documents", [
			{"document_type": row.get("document_type"),
			 "is_mandatory": cint(row.get("is_mandatory"))}
			for row in data["documents"] if row.get("document_type")
		])

	doc.save()
	return {"partner": doc.name, "is_active": bool(cint(doc.is_active))}


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
@frappe.whitelist()
def settlement(name: str) -> dict:
	"""One settlement, with the applications it covers."""
	_me()
	require_permission("Financier Settlement", "read")

	doc = frappe.get_doc("Financier Settlement", name)
	return {
		"name": doc.name,
		"partner": doc.finance_partner,
		"from_date": str(doc.from_date or ""),
		"to_date": str(doc.to_date or ""),
		"status": doc.status,
		"tone": SETTLEMENT_TONES.get(doc.status, "pill-sky"),
		"docstatus": cint(doc.docstatus),
		"bank_account": doc.bank_account,
		"utr_reference": doc.utr_reference,
		"totals": {
			"gross": flt(doc.gross_amount),
			"mdr": flt(doc.mdr_amount),
			"subvention": flt(doc.subvention_amount),
			"gst_on_mdr": flt(doc.gst_on_mdr),
			"tds": flt(doc.tds_amount),
			"other": flt(doc.other_deductions),
			"expected": flt(doc.net_expected),
			"received": flt(doc.net_received),
			"variance": flt(doc.variance),
		},
		"journal_entry": doc.journal_entry,
		"rows": [
			{"application": row.emi_application, "invoice": row.sales_invoice,
			 "customer": row.customer, "invoice_date": str(row.invoice_date or ""),
			 "loan_amount": flt(row.loan_amount), "mdr": flt(row.mdr),
			 "subvention": flt(row.subvention), "gst": flt(row.gst_on_mdr),
			 "net_amount": flt(row.net_amount), "received": bool(cint(row.is_received))}
			for row in doc.get("applications") or []
		],
		"print_url": print_url(doc.name, "Financier Settlement Statement",
		                       doctype="Financier Settlement"),
		"can": {
			"record": cint(doc.docstatus) == 0
			and bool(frappe.has_permission("Financier Settlement", "submit")),
			"dispute": cint(doc.docstatus) == 0,
		},
	}


@frappe.whitelist()
def draft_settlement(partner: str, from_date: str, to_date: str,
                     bank_account: str | None = None) -> dict:
	"""Open a settlement and pull in everything the financier still owes."""
	_me()
	require_permission("Financier Settlement", "create")

	doc = frappe.new_doc("Financier Settlement")
	doc.finance_partner = partner
	doc.from_date = getdate(from_date)
	doc.to_date = getdate(to_date)
	doc.company = frappe.db.get_single_value("Global Defaults", "default_company")
	# The account the credit lands in. It can be changed when the bank statement
	# is in front of somebody; the document needs one to exist at all.
	doc.bank_account = bank_account or _default_bank_account(doc.company)
	if not doc.bank_account:
		frappe.throw(
			_("No bank account is set up for {0}, so there is nowhere to record the credit.")
			.format(doc.company),
			title=_("No bank account"),
		)
	doc.insert()

	added = doc.get_pending_applications()
	if not added:
		frappe.db.rollback()
		frappe.throw(
			_("{0} has nothing outstanding between {1} and {2}. Everything disbursed in that "
			  "period has already been settled.").format(
				partner, frappe.utils.format_date(from_date), frappe.utils.format_date(to_date)),
			title=_("Nothing to settle"),
		)

	doc.save()
	return {"settlement": doc.name, "applications": added,
	        "expected": flt(doc.net_expected)}


def _default_bank_account(company: str) -> str | None:
	account = frappe.get_cached_value("Company", company, "default_bank_account")
	if account:
		return account
	return frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name")


@frappe.whitelist()
def record_settlement(name: str, net_received: float, utr_reference: str | None = None,
                      bank_account: str | None = None, other_deductions: float = 0,
                      submit: int = 1) -> dict:
	"""Key in the bank credit. Submitting posts the Journal Entry the doctype owns."""
	_me()
	require_permission("Financier Settlement", "write")

	doc = frappe.get_doc("Financier Settlement", name)
	if cint(doc.docstatus) != 0:
		frappe.throw(_("{0} has already been posted.").format(name), title=_("Already posted"))

	doc.net_received = flt(net_received)
	doc.utr_reference = utr_reference or doc.utr_reference
	doc.bank_account = bank_account or doc.bank_account
	doc.other_deductions = flt(other_deductions)
	doc.save()

	if cint(submit):
		if not doc.bank_account:
			frappe.throw(_("Which account did the money land in?"), title=_("Bank account needed"))
		doc.submit()

	doc.reload()
	return {
		"settlement": doc.name,
		"status": doc.status,
		"expected": flt(doc.net_expected),
		"received": flt(doc.net_received),
		"variance": flt(doc.variance),
		"journal_entry": doc.journal_entry,
		"posted": cint(doc.docstatus) == 1,
	}


@frappe.whitelist()
def raise_dispute(name: str, remarks: str) -> dict:
	"""A short credit stays open and on the record until the financier answers."""
	_me()
	require_permission("Financier Settlement", "write")

	if not (remarks or "").strip():
		frappe.throw(_("Write down what is being queried with the financier."),
		             title=_("Say what is wrong"))

	doc = frappe.get_doc("Financier Settlement", name)
	doc.db_set("status", "Variance - Under Query", update_modified=False)
	doc.add_comment("Comment", _("Queried with the financier: {0}").format(remarks))
	return {"settlement": doc.name, "status": "Variance - Under Query"}


# ---------------------------------------------------------------------------
# Elsewhere in the app
# ---------------------------------------------------------------------------
@frappe.whitelist()
def customer_history(customer: str, limit: int = 20) -> list[dict]:
	"""This customer's financing, for the Customer Overview page."""
	_me()
	require_permission("EMI Application", "read")

	rows = frappe.get_all(
		"EMI Application",
		filters={"customer": customer, "docstatus": ["<", 2]},
		fields=["name", "application_date", "finance_partner", "emi_scheme", "sales_invoice",
		        "loan_amount", "emi_amount", "tenure_months", "status", "loan_account_number",
		        "branch"],
		order_by="application_date desc", limit=cint(limit) or 20,
	)
	for row in rows:
		row["tone"] = tone_of(row.status)
		row["products"] = ", ".join(frappe.get_all(
			"EMI Application Item", filters={"parent": row.name}, pluck="item_name") or [])
	return rows


@frappe.whitelist()
def print_url(name: str, print_format: str = "EMI Application Form",
              doctype: str = "EMI Application") -> str:
	"""The application's own print, through the app's print system."""
	from urllib.parse import urlencode

	_me()
	require_permission(doctype, "read")

	query = urlencode({
		"doctype": doctype,
		"name": name,
		"format": print_format,
		"no_letterhead": 0,
		"_lang": "en",
	})
	return f"/api/method/frappe.utils.print_format.download_pdf?{query}"
