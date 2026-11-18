# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""GST, reverse charge, TDS and payment modes (scope 11.1 – 11.3).

The RCM pattern is the important one. On a reverse-charge purchase the recipient
owes the GST directly to the government, so the invoice carries the tax twice:

    Input Tax CGST      9%   Add      -> the ITC, in the ordinary input account
    Input Tax CGST RCM  9%   Deduct   -> the liability that will be paid in cash

The two net to zero on the invoice, so the supplier is still paid the base
amount, while the ledger shows both the liability (GSTR-3B table 3.1(d)) and the
credit that offsets output tax on sales (table 4(A)(3)) — which is exactly the
"pay the GST and claim it back" requirement (scope 11.2).

Which account goes on which side is not ours to choose. india_compliance sorts
every GST account into a type in GST Settings and refuses a purchase invoice
carrying one from the wrong type: `Input Tax * RCM` is "Purchase Reverse
Charge", while `Output Tax * RCM` is "Sales Reverse Charge" and belongs to the
self-invoice, not here. Putting the output account on the Deduct side — the
pattern ERPNext used before india_compliance existed — gives

    Row #3: Output Tax CGST RCM - PT is not a valid GST account for this
    transaction

and the bill cannot be saved at all. The credit side is therefore the *ordinary*
input account, which is also where `gst_itemised_purchase_register` and GSTR-2B
matching look for it, and the RCM account carries the liability.
"""

import frappe

from a3_retail.setup.accounts import get_abbr, get_company

# ---------------------------------------------------------------------------
# Chart of accounts additions (scope 11.1)
# ---------------------------------------------------------------------------
# (account_name, root_parent_hint, account_type, is_group)
COA_ADDITIONS = [
	# Current assets — financier settlement receivables
	("Bajaj Finserv Settlement Receivable", "Loans and Advances", None),
	("HDB Settlement Receivable", "Loans and Advances", None),
	("IDFC Settlement Receivable", "Loans and Advances", None),
	("Zest Settlement Receivable", "Loans and Advances", None),
	("HDFC Card EMI Receivable", "Loans and Advances", None),
	("Exchange Clearing", "Loans and Advances", None),
	# Current liabilities
	("Gift Voucher Liability", "Current Liabilities", None),
	("Advance from Customers - Service", "Current Liabilities", "Receivable"),
	("Deferred EW Revenue", "Current Liabilities", None),
	("Provision for Slow Moving Stock", "Current Liabilities", None),
	# Income
	("Sales - Mobile Devices", "Direct Income", "Income Account"),
	("Sales - Accessories", "Direct Income", "Income Account"),
	("Sales - Used Devices (Margin Scheme)", "Direct Income", "Income Account"),
	("Service Income - Labour", "Direct Income", "Income Account"),
	("Service Income - Parts", "Direct Income", "Income Account"),
	("Extended Warranty Income", "Direct Income", "Income Account"),
	("EMI Commission Income", "Indirect Income", "Income Account"),
	("Damage Recovery", "Indirect Income", "Income Account"),
	# Expenses
	("Cost of Goods Sold - Devices", "Direct Expenses", "Cost of Goods Sold"),
	("Cost of Goods Sold - Accessories", "Direct Expenses", "Cost of Goods Sold"),
	("Cost of Goods Sold - Parts", "Direct Expenses", "Cost of Goods Sold"),
	("MDR & Subvention Expense", "Indirect Expenses", "Expense Account"),
	("Warranty Expense (Claims)", "Indirect Expenses", "Expense Account"),
	("Stock Damage Written Off", "Indirect Expenses", "Expense Account"),
	("Courier & Freight Outward", "Indirect Expenses", "Expense Account"),
	("Demurrage & Detention Charges", "Indirect Expenses", "Expense Account"),
	("Sales Incentive Expense", "Indirect Expenses", "Expense Account"),
	("Stock Obsolescence Provision", "Indirect Expenses", "Expense Account"),
]

# RCM tax accounts. india_compliance already ships "Input Tax CGST RCM" /
# "Output Tax CGST RCM" under Duties and Taxes on companies it provisions; we
# reuse those where they exist so its GST reports pick the postings up, and only
# create our own when the company predates the app.
RCM_ACCOUNTS = [
	("Input CGST RCM", "Duties and Taxes", "Tax", "Liability"),
	("Input SGST RCM", "Duties and Taxes", "Tax", "Liability"),
	("Input IGST RCM", "Duties and Taxes", "Tax", "Liability"),
	("Output CGST RCM", "Duties and Taxes", "Tax", "Liability"),
	("Output SGST RCM", "Duties and Taxes", "Tax", "Liability"),
	("Output IGST RCM", "Duties and Taxes", "Tax", "Liability"),
]

# Preferred india_compliance account name -> our fallback name.
RCM_ACCOUNT_ALIASES = {
	"Input CGST RCM": "Input Tax CGST RCM",
	"Input SGST RCM": "Input Tax SGST RCM",
	"Input IGST RCM": "Input Tax IGST RCM",
	"Output CGST RCM": "Output Tax CGST RCM",
	"Output SGST RCM": "Output Tax SGST RCM",
	"Output IGST RCM": "Output Tax IGST RCM",
}


def rcm_account(company: str, our_name: str) -> str | None:
	"""Prefer india_compliance's RCM account, fall back to ours."""
	abbr = get_abbr(company)
	preferred = RCM_ACCOUNT_ALIASES.get(our_name)
	if preferred and frappe.db.exists("Account", f"{preferred} - {abbr}"):
		return f"{preferred} - {abbr}"
	ours = f"{our_name} - {abbr}"
	return ours if frappe.db.exists("Account", ours) else None

MODES_OF_PAYMENT = [
	("Cash", "Cash", "Cash"),
	("UPI", "Bank", "Bank"),
	("Credit Card", "Bank", "Bank"),
	("Debit Card", "Bank", "Bank"),
	("EMI - Bajaj Finserv", "Bank", "Bajaj Finserv Settlement Receivable"),
	("EMI - HDB", "Bank", "HDB Settlement Receivable"),
	("EMI - IDFC First", "Bank", "IDFC Settlement Receivable"),
	("EMI - Zest", "Bank", "Zest Settlement Receivable"),
	("EMI - HDFC Card", "Bank", "HDFC Card EMI Receivable"),
	("Exchange Adjustment", "Bank", "Exchange Clearing"),
	("Gift Voucher", "Bank", "Gift Voucher Liability"),
]

# (name, section, rate, account hint)
TDS_CATEGORIES = [
	("TDS 194-I Rent", "194-I", 10.0),
	("TDS 194-J Professional Fees", "194-J", 10.0),
	("TDS 194-C Contractors", "194-C", 2.0),
	("TDS 194-H Commission", "194-H", 5.0),
]


def run():
	"""Idempotent: accounts, tax templates, payment modes, TDS, GST settings."""
	company = get_company()
	if not company:
		return

	ensure_accounts(company)
	ensure_gst_settings()
	ensure_sales_tax_templates(company)
	ensure_purchase_tax_templates(company)
	ensure_modes_of_payment(company)
	ensure_tds_categories(company)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def _find_parent(company: str, hint: str) -> str | None:
	"""Locate a group account by name fragment; the CoA template varies by country."""
	abbr = get_abbr(company)
	exact = f"{hint} - {abbr}"
	if frappe.db.exists("Account", exact):
		return exact

	match = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "account_name": ["like", f"%{hint}%"]},
		"name",
	)
	if match:
		return match

	# Fall back to the closest root for the family of accounts.
	fallbacks = {
		"Loans and Advances": "Current Assets",
		"Direct Income": "Income",
		"Indirect Income": "Income",
		"Direct Expenses": "Expenses",
		"Indirect Expenses": "Expenses",
		"Current Liabilities": "Liabilities",
		"Duties and Taxes": "Current Liabilities",
	}
	if hint in fallbacks:
		return _find_parent(company, fallbacks[hint])
	return None


def ensure_account(
	company: str,
	account_name: str,
	parent_hint: str,
	account_type: str | None = None,
	root_type: str | None = None,
) -> str | None:
	abbr = get_abbr(company)
	full_name = f"{account_name} - {abbr}"
	if frappe.db.exists("Account", full_name):
		return full_name

	parent = _find_parent(company, parent_hint)
	if not parent:
		return None

	account = frappe.new_doc("Account")
	account.account_name = account_name
	account.parent_account = parent
	account.company = company
	account.is_group = 0
	if account_type:
		account.account_type = account_type
	if root_type:
		account.root_type = root_type
	account.flags.ignore_permissions = True
	try:
		account.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: could not create account {account_name}")
		return None
	return account.name


def ensure_accounts(company: str):
	for account_name, parent_hint, account_type in COA_ADDITIONS:
		ensure_account(company, account_name, parent_hint, account_type)

	for account_name, parent_hint, account_type, root_type in RCM_ACCOUNTS:
		ensure_account(company, account_name, parent_hint, account_type, root_type)

	_set_company_defaults(company)
	_point_settings_at_accounts(company)


def _set_company_defaults(company: str):
	"""Advances need their own party account so branch-wise liability is visible.

	`book_advance_payments_in_separate_party_account` (scope 3.5) makes ERPNext
	demand `default_advance_received_account`, so the two are set together.
	"""
	abbr = get_abbr(company)
	advance_account = f"Advance from Customers - Service - {abbr}"
	if not frappe.db.exists("Account", advance_account):
		return

	doc = frappe.get_doc("Company", company)
	changed = False

	if doc.meta.has_field("default_advance_received_account") and not doc.get(
		"default_advance_received_account"
	):
		doc.default_advance_received_account = advance_account
		changed = True

	if changed:
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)


def _point_settings_at_accounts(company: str):
	abbr = get_abbr(company)
	settings = frappe.get_single("A3 Retail Settings")
	changed = False

	for field, account_name in (
		("deferred_revenue_account", "Deferred EW Revenue"),
		("warranty_expense_account", "Warranty Expense (Claims)"),
	):
		full = f"{account_name} - {abbr}"
		if not settings.get(field) and frappe.db.exists("Account", full):
			settings.set(field, full)
			changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)


def gst_account(company: str, name_fragment: str) -> str | None:
	"""Resolve an ERPNext/india_compliance GST account by name fragment."""
	abbr = get_abbr(company)
	exact = f"{name_fragment} - {abbr}"
	if frappe.db.exists("Account", exact):
		return exact
	return frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 0, "account_name": ["like", f"%{name_fragment}%"]},
		"name",
	)


# ---------------------------------------------------------------------------
# GST settings
# ---------------------------------------------------------------------------
def ensure_gst_settings():
	if not frappe.db.exists("DocType", "GST Settings"):
		return

	settings = frappe.get_single("GST Settings")
	changed = False
	# `round_off_gst_values` is deliberately not here. It was, set to 1, and a
	# deploy turned it back on every time the shop turned it off — their call to
	# make, not the installer's, and india_compliance's own default is off
	# anyway. `patches/gst_round_off_off.py` switched it off once; nothing
	# asserts it on a migrate now.
	for field, value in (
		("enable_e_invoice", 0),
		("enable_e_waybill", 1),
		("enable_reverse_charge_in_sales", 0),
	):
		if settings.meta.has_field(field) and settings.get(field) != value:
			settings.set(field, value)
			changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		try:
			settings.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "A3 Retail: GST Settings save failed")


# ---------------------------------------------------------------------------
# Tax templates
# ---------------------------------------------------------------------------
def _sales_template(company: str, title: str, rows: list[dict]) -> str | None:
	abbr = get_abbr(company)
	full = f"{title} - {abbr}"
	if frappe.db.exists("Sales Taxes and Charges Template", full):
		return full

	doc = frappe.new_doc("Sales Taxes and Charges Template")
	doc.title = title
	doc.company = company
	for row in rows:
		if not row.get("account_head"):
			return None
		doc.append("taxes", row)
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: sales tax template {title}")
		return None
	return doc.name


def _purchase_template(company: str, title: str, rows: list[dict], is_reverse_charge=False) -> str | None:
	abbr = get_abbr(company)
	full = f"{title} - {abbr}"
	if frappe.db.exists("Purchase Taxes and Charges Template", full):
		return full

	doc = frappe.new_doc("Purchase Taxes and Charges Template")
	doc.title = title
	doc.company = company
	if doc.meta.has_field("is_reverse_charge"):
		doc.is_reverse_charge = 1 if is_reverse_charge else 0
	for row in rows:
		if not row.get("account_head"):
			return None
		doc.append("taxes", row)
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 Retail: purchase tax template {title}")
		return None
	return doc.name


def _tax_row(account: str | None, rate: float, description: str, add_deduct="Add", category="Total"):
	return {
		"charge_type": "On Net Total",
		"account_head": account,
		"rate": rate,
		"description": description,
		"add_deduct_tax": add_deduct,
		"category": category,
	}


def ensure_sales_tax_templates(company: str):
	output_cgst = gst_account(company, "Output Tax CGST") or gst_account(company, "CGST")
	output_sgst = gst_account(company, "Output Tax SGST") or gst_account(company, "SGST")
	output_igst = gst_account(company, "Output Tax IGST") or gst_account(company, "IGST")

	# The shop quotes an all-in price — the label on the box and the price list
	# both already carry GST — so the tax is backed out of the rate rather than
	# added to it. Without this a bill reads 18% over what the customer was told.
	for rate in (5, 12, 18, 28):
		half = rate / 2
		_sales_template(
			company,
			f"Output GST In-state {rate}%",
			[
				{"charge_type": "On Net Total", "account_head": output_cgst, "rate": half,
				 "description": f"CGST {half}%", "included_in_print_rate": 1},
				{"charge_type": "On Net Total", "account_head": output_sgst, "rate": half,
				 "description": f"SGST {half}%", "included_in_print_rate": 1},
			],
		)
		_sales_template(
			company,
			f"Output GST Out-state {rate}%",
			[{"charge_type": "On Net Total", "account_head": output_igst, "rate": rate,
			  "description": f"IGST {rate}%", "included_in_print_rate": 1}],
		)

	_sales_template(
		company,
		"Output GST Nil Rated",
		[{"charge_type": "On Net Total", "account_head": output_cgst, "rate": 0,
		  "description": "Nil rated / exempt"}],
	)


def ensure_purchase_tax_templates(company: str):
	input_cgst = gst_account(company, "Input Tax CGST") or gst_account(company, "CGST")
	input_sgst = gst_account(company, "Input Tax SGST") or gst_account(company, "SGST")
	input_igst = gst_account(company, "Input Tax IGST") or gst_account(company, "IGST")

	for rate in (5, 12, 18, 28):
		half = rate / 2
		_purchase_template(
			company,
			f"Input GST In-state {rate}%",
			[
				{"charge_type": "On Net Total", "account_head": input_cgst, "rate": half,
				 "description": f"CGST {half}%", "category": "Total", "add_deduct_tax": "Add"},
				{"charge_type": "On Net Total", "account_head": input_sgst, "rate": half,
				 "description": f"SGST {half}%", "category": "Total", "add_deduct_tax": "Add"},
			],
		)
		_purchase_template(
			company,
			f"Input GST Out-state {rate}%",
			[{"charge_type": "On Net Total", "account_head": input_igst, "rate": rate,
			  "description": f"IGST {rate}%", "category": "Total", "add_deduct_tax": "Add"}],
		)

	_ensure_rcm_templates(company)


def rcm_template_rows(company: str, rate: int, out_of_state: bool) -> list[dict]:
	"""The tax rows of one reverse-charge purchase template.

	Shared with the patch that corrects templates already on a live site, so
	there is one statement of the pattern rather than two that can drift.

	Returns [] when an account is missing, which is how the caller knows not to
	build a half-template that would post to nothing.
	"""
	# Add: the ITC, in the same account an ordinary purchase uses, so the
	# purchase register and GSTR-2B matching find it where they look.
	# Deduct: the liability, in the Purchase Reverse Charge account.
	if out_of_state:
		rows = [
			(gst_account(company, "Input Tax IGST"), rate, f"IGST {rate}%", "Add"),
			(rcm_account(company, "Input IGST RCM"), rate, f"IGST RCM {rate}%", "Deduct"),
		]
	else:
		half = rate / 2
		rows = [
			(gst_account(company, "Input Tax CGST"), half, f"CGST {half}%", "Add"),
			(gst_account(company, "Input Tax SGST"), half, f"SGST {half}%", "Add"),
			(rcm_account(company, "Input CGST RCM"), half, f"CGST RCM {half}%", "Deduct"),
			(rcm_account(company, "Input SGST RCM"), half, f"SGST RCM {half}%", "Deduct"),
		]

	if any(not account for account, *_ in rows):
		return []
	return [_tax_row(account, amount, description, side)
	        for account, amount, description, side in rows]


def _ensure_rcm_templates(company: str):
	"""One template per rate and direction, each netting to the base payable."""
	# Every rate the shop buys at. A rate with no RCM template of its own falls
	# through to none at all, and the bill would carry no tax rather than the
	# wrong tax — silent, and wrong in the return.
	for rate in (5, 12, 18, 28):
		for out_of_state in (False, True):
			rows = rcm_template_rows(company, rate, out_of_state)
			if not rows:
				continue
			kind = "Out-state" if out_of_state else "In-state"
			_purchase_template(company, f"Input GST RCM {kind} {rate}%", rows,
			                   is_reverse_charge=True)


# ---------------------------------------------------------------------------
# Modes of payment
# ---------------------------------------------------------------------------
def ensure_modes_of_payment(company: str):
	abbr = get_abbr(company)
	default_cash = frappe.db.get_value("Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name")
	default_bank = frappe.db.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name")

	for name, mode_type, account_hint in MODES_OF_PAYMENT:
		if account_hint == "Cash":
			account = default_cash
		elif account_hint == "Bank":
			account = default_bank
		else:
			account = f"{account_hint} - {abbr}"
			if not frappe.db.exists("Account", account):
				account = default_bank

		if not frappe.db.exists("Mode of Payment", name):
			doc = frappe.new_doc("Mode of Payment")
			doc.mode_of_payment = name
			doc.type = mode_type
			doc.enabled = 1
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		else:
			doc = frappe.get_doc("Mode of Payment", name)

		if account and not any(row.company == company for row in doc.get("accounts", [])):
			doc.append("accounts", {"company": company, "default_account": account})
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# TDS
# ---------------------------------------------------------------------------
def ensure_tds_categories(company: str):
	abbr = get_abbr(company)
	tds_account = ensure_account(company, "TDS Payable", "Duties and Taxes", "Tax", "Liability")
	if not tds_account:
		return

	fiscal_year = frappe.db.get_value("Fiscal Year", {"disabled": 0}, ["year_start_date", "year_end_date"], as_dict=True)
	if not fiscal_year:
		return

	for name, section, rate in TDS_CATEGORIES:
		if frappe.db.exists("Tax Withholding Category", name):
			continue
		doc = frappe.new_doc("Tax Withholding Category")
		doc.name = name
		doc.category_name = name
		doc.append(
			"rates",
			{
				"from_date": fiscal_year.year_start_date,
				"to_date": fiscal_year.year_end_date,
				"tax_withholding_rate": rate,
				"single_threshold": 0,
				"cumulative_threshold": 0,
			},
		)
		doc.append("accounts", {"company": company, "account": tds_account})
		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: TDS category {name}")
