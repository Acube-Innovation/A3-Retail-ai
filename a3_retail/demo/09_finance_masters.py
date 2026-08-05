"""Seed 09 — 5 Finance Partners, 7 EMI Schemes, 16 EMI Document Types (scope 4.2 – 4.4)."""

import frappe

from a3_retail.setup.accounts import get_abbr, get_company

# name, type, mode of payment, settlement account, mdr %, subvention by, tat, min, max
PARTNERS = [
	("Bajaj Finserv", "NBFC", "EMI - Bajaj Finserv", "Bajaj Finserv Settlement Receivable",
	 2.50, "Merchant", 3, 8000, 200000),
	("HDB Financial Services", "NBFC", "EMI - HDB", "HDB Settlement Receivable",
	 2.75, "Merchant", 4, 10000, 150000),
	("IDFC First Bank", "Bank", "EMI - IDFC First", "IDFC Settlement Receivable",
	 2.00, "Manufacturer", 2, 12000, 300000),
	("ZestMoney", "Fintech / BNPL", "EMI - Zest", "Zest Settlement Receivable",
	 3.50, "Merchant", 5, 5000, 60000),
	("HDFC Card EMI", "Card EMI", "EMI - HDFC Card", "HDFC Card EMI Receivable",
	 1.80, "Manufacturer", 2, 5000, 500000),
]

# name, partner, tenure, no cost, interest, fee, dp %, subvention %, brands, min, max
SCHEMES = [
	("Bajaj 6M No Cost", "Bajaj Finserv", 6, 1, 0, 599, 10, 5.0, [], 8000, 200000),
	("Bajaj 9M No Cost", "Bajaj Finserv", 9, 1, 0, 699, 15, 7.5, ["Samsung", "Apple"], 15000, 200000),
	("Bajaj 12M Standard", "Bajaj Finserv", 12, 0, 16, 799, 20, 0, [], 15000, 200000),
	("HDB 6M No Cost", "HDB Financial Services", 6, 1, 0, 549, 10, 5.5, [], 10000, 150000),
	("IDFC 12M Manufacturer Subvented", "IDFC First Bank", 12, 1, 0, 0, 0, 0, ["Apple"], 40000, 300000),
	("Zest 3M BNPL", "ZestMoney", 3, 1, 0, 199, 0, 3.0, [], 5000, 60000),
	("HDFC Card 9M", "HDFC Card EMI", 9, 1, 0, 299, 0, 0, ["Samsung", "Apple"], 10000, 500000),
]

# name, category, applies to, mandatory, original verification
DOCUMENTS = [
	("Aadhaar Card (Front & Back)", "Identity (KYC)", "All", 1, 1),
	("PAN Card", "Identity (KYC)", "All", 1, 1),
	("Passport Size Photograph", "Identity (KYC)", "All", 1, 0),
	("Cancelled Cheque", "Banking", "All", 1, 1),
	("Bank Statement (Last 3 Months)", "Banking", "Salaried", 1, 0),
	("Bank Statement (Last 6 Months)", "Banking", "Self Employed", 1, 0),
	("Latest Salary Slip", "Income Proof", "Salaried", 1, 0),
	("Form 16 / ITR (Last 2 Years)", "Income Proof", "Self Employed", 1, 0),
	("Electricity Bill / Rent Agreement", "Address Proof", "All", 0, 0),
	("GST Certificate", "Income Proof", "Self Employed", 0, 0),
	("NACH / e-Mandate Form", "Loan Forms", "All", 1, 1),
	("Signed Loan Agreement", "Loan Forms", "All", 1, 1),
	("Customer Declaration & Consent", "Loan Forms", "All", 1, 1),
	("Device Invoice Copy", "Device / Sale", "All", 1, 0),
	("IMEI / Serial Photograph", "Device / Sale", "All", 1, 0),
	("Existing Loan Card (Pre-approved)", "Loan Forms", "Existing Customer (Pre-approved)", 1, 1),
]


def run():
	_documents()
	_partners()
	_schemes()


def _documents():
	for name, category, applies_to, mandatory, verify in DOCUMENTS:
		if frappe.db.exists("EMI Document Type", name):
			continue
		doc = frappe.new_doc("EMI Document Type")
		doc.document_name = name
		doc.category = category
		doc.applies_to = applies_to
		doc.is_mandatory_default = mandatory
		doc.requires_original_verification = verify
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _partners():
	company = get_company()
	abbr = get_abbr(company)
	expense = f"MDR & Subvention Expense - {abbr}"

	for name, ptype, mode, account, mdr, subvention_by, tat, minimum, maximum in PARTNERS:
		if frappe.db.exists("Finance Partner", name):
			continue

		settlement_account = f"{account} - {abbr}"
		if not frappe.db.exists("Account", settlement_account) or not frappe.db.exists("Mode of Payment", mode):
			continue

		doc = frappe.new_doc("Finance Partner")
		doc.partner_name = name
		doc.partner_type = ptype
		doc.mode_of_payment = mode
		doc.settlement_account = settlement_account
		doc.mdr_expense_account = expense if frappe.db.exists("Account", expense) else settlement_account
		doc.mdr_percent = mdr
		doc.subvention_borne_by = subvention_by
		doc.settlement_tat_days = tat
		doc.min_ticket_size = minimum
		doc.max_ticket_size = maximum
		doc.is_active = 1

		# Every partner asks for the same core KYC set.
		for document in ("Aadhaar Card (Front & Back)", "PAN Card", "Cancelled Cheque",
		                 "NACH / e-Mandate Form", "Signed Loan Agreement",
		                 "Customer Declaration & Consent", "Device Invoice Copy",
		                 "IMEI / Serial Photograph"):
			if frappe.db.exists("EMI Document Type", document):
				doc.append("required_documents", {"document_type": document, "is_mandatory": 1})

		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _schemes():
	for (name, partner, tenure, no_cost, interest, fee, dp_percent, subvention,
	     brands, minimum, maximum) in SCHEMES:
		if frappe.db.exists("EMI Scheme", name) or not frappe.db.exists("Finance Partner", partner):
			continue

		doc = frappe.new_doc("EMI Scheme")
		doc.scheme_name = name
		doc.finance_partner = partner
		doc.tenure_months = tenure
		doc.is_no_cost_emi = no_cost
		doc.interest_rate = interest
		doc.processing_fee = fee
		doc.processing_fee_type = "Fixed"
		doc.down_payment_percent = dp_percent
		doc.subvention_percent = subvention
		doc.min_invoice_amount = minimum
		doc.max_invoice_amount = maximum
		doc.is_active = 1
		for brand in brands:
			if frappe.db.exists("Brand", brand):
				doc.append("applicable_brands", {"brand": brand})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
