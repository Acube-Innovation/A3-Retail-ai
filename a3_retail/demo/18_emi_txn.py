"""Seed 18 — EMI applications across the funnel and three settlements (scope 14.2)."""

import frappe
from frappe.utils import add_days, flt, nowdate

# status, count
FUNNEL = [
	("Disbursed", 6),
	("Approved", 3),
	("Submitted to Financier", 3),
	("Rejected", 2),
	("Documents Pending", 2),
]

MARKER = "A3 demo EMI"


def run():
	_applications()
	_settlements()


def _applications():
	if frappe.db.count("EMI Application") >= 34:
		# 18 from the July incentive seed plus this seed's 16.
		return

	schemes = frappe.get_all("EMI Scheme", fields=["name", "finance_partner"], limit=5)
	customers = frappe.get_all("Customer", filters={"a3_mobile_no": ["is", "set"]}, pluck="name")
	if not schemes or not customers:
		return

	# Attributed to the branch manager, not the EMI coordinator: these overlap the
	# July window that seed 24 uses for the incentive run, and doubling up there
	# would change a payout the scope pins down.
	coordinator = frappe.db.get_value(
		"Employee", {"designation": "Branch Manager", "status": "Active"}, "name"
	)

	index = 0
	for status, count in FUNNEL:
		for _ in range(count):
			_application(index, status, schemes[index % len(schemes)], customers, coordinator)
			index += 1


def _application(index: int, status: str, scheme, customers: list[str], coordinator: str | None):
	application_date = add_days(nowdate(), -(index * 3 + 2))

	doc = frappe.new_doc("EMI Application")
	doc.customer = customers[index % len(customers)]
	doc.branch = ["Kochi", "Thiruvananthapuram", "Kozhikode"][index % 3]
	doc.coordinator = coordinator
	doc.application_date = application_date
	doc.employment_type = ["Salaried", "Self Employed", "Business Owner"][index % 3]
	doc.pan_number = f"ABCPK{1000 + index}F"
	doc.aadhaar_last4 = f"{2000 + index}"[-4:]
	doc.monthly_income = 25000 + index * 1500
	doc.finance_partner = scheme.finance_partner
	doc.emi_scheme = scheme.name
	# Schemes carry a minimum invoice value and a minimum down payment; keep the
	# demo applications comfortably inside both.
	doc.invoice_total = 45000 + (index % 5) * 2500
	doc.down_payment = round(doc.invoice_total * 0.30)
	doc.tenure_months = [6, 9, 12][index % 3]
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True

	try:
		doc.insert(ignore_permissions=True)
		if status != "Documents Pending":
			for row in doc.get("documents") or []:
				row.is_received = 1
				row.attachment = "/files/demo-emi-document.pdf"
			doc.save(ignore_permissions=True)
			doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"A3 demo: EMI application {index}")
		return

	if status in ("Documents Pending", "Ready to Submit"):
		return

	values = {"status": status, "submitted_on": f"{application_date} 11:00:00"}
	if status in ("Approved", "Disbursed"):
		values.update(
			{
				"partner_application_no": f"DEMO-APP-{index + 1:04d}",
				"approved_loan_amount": flt(doc.loan_amount),
				"loan_account_number": f"LN{index + 1:08d}",
				"approval_date": add_days(application_date, 1),
				"cibil_score": 700 + index * 5,
			}
		)
	if status == "Disbursed":
		values["disbursement_date"] = add_days(application_date, 2)
	if status == "Rejected":
		values.update({"rejection_reason": "Low CIBIL Score",
		               "rejection_remarks": "Bureau score below the partner's cut-off."})

	frappe.db.set_value("EMI Application", doc.name, values, update_modified=False)


def _settlements():
	if frappe.db.count("Financier Settlement", {"docstatus": ["<", 2]}) >= 3:
		return

	partners = frappe.get_all("Finance Partner", pluck="name", limit=3)
	for index, partner in enumerate(partners):
		doc = frappe.new_doc("Financier Settlement")
		doc.finance_partner = partner
		doc.from_date = add_days(nowdate(), -(30 + index * 15))
		doc.to_date = add_days(nowdate(), -(15 + index * 15))
		doc.utr_reference = f"UTR{index + 1:010d}"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 demo: settlement {index}")
