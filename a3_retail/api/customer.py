"""A3 Retail — customer API.

The counter must be able to turn a 10-digit mobile number into a Customer in one
call, without leaving POS or the Reception Desk (scope 1.3).
"""

import re

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from a3_retail.api import require_permission
from a3_retail.utils.branch import get_user_branch

MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def normalize_mobile(mobile_no: str | None) -> str:
	"""Strip spaces, +91 and leading zeros down to the 10-digit subscriber number."""
	digits = re.sub(r"\D", "", str(mobile_no or ""))
	if len(digits) > 10:
		digits = digits[-10:]
	return digits


def validate_mobile(mobile_no: str) -> str:
	mobile = normalize_mobile(mobile_no)
	if not MOBILE_RE.match(mobile):
		frappe.throw(_("{0} is not a valid 10-digit Indian mobile number.").format(mobile_no))
	return mobile


@frappe.whitelist()
def find_by_mobile(mobile_no: str) -> dict | None:
	"""Return the customer for a mobile number, or None."""
	require_permission("Customer", "read")

	mobile = normalize_mobile(mobile_no)
	if not mobile:
		return None

	name = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	if not name:
		return None

	return get_profile(name)


@frappe.whitelist()
def get_profile(customer: str) -> dict:
	"""Customer plus the context the counter needs: devices, jobs, outstanding."""
	require_permission("Customer", "read")

	doc = frappe.get_doc("Customer", customer)
	devices = frappe.get_all(
		"Serial No",
		filters={"customer": customer},
		fields=[
			"name as serial_no",
			"a3_imei_1 as imei",
			"item_code",
			"a3_warranty_state",
			"a3_brand_warranty_expiry",
		],
		limit_page_length=20,
		order_by="creation desc",
	)

	past_jobs = []
	if frappe.db.exists("DocType", "Service Job Card"):
		past_jobs = frappe.get_all(
			"Service Job Card",
			filters={"customer": customer, "docstatus": ["<", 2]},
			fields=["name", "status", "device_model", "imei_1", "received_on", "grand_total"],
			order_by="received_on desc",
			limit_page_length=10,
		)

	outstanding = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabSales Invoice`
		   where customer = %s and docstatus = 1 and outstanding_amount > 0""",
		customer,
	)[0][0] or 0

	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"mobile_no": doc.a3_mobile_no,
		"whatsapp_no": doc.a3_whatsapp_no,
		"email": doc.get("email_id"),
		"customer_group": doc.customer_group,
		"territory": doc.territory,
		"source_branch": doc.a3_source_branch,
		"customer_since": doc.a3_customer_since,
		"lifetime_value": doc.a3_lifetime_value,
		"device_count": doc.a3_device_count,
		"last_purchase_date": doc.a3_last_purchase_date,
		"last_service_date": doc.a3_last_service_date,
		"marketing_optin": doc.a3_marketing_optin,
		"dnc": doc.a3_dnc,
		"outstanding": outstanding,
		"devices": devices,
		"past_jobs": past_jobs,
	}


@frappe.whitelist()
def get_or_create(
	mobile_no: str,
	customer_name: str | None = None,
	branch: str | None = None,
	email: str | None = None,
	marketing_optin: int = 1,
	customer_group: str | None = None,
) -> dict:
	"""Find a customer by mobile, or create one. Idempotent by mobile number.

	The unique index on `Customer.a3_mobile_no` is what actually prevents
	duplicates; the pre-check just avoids a noisy exception on the happy path.
	"""
	require_permission("Customer", "read")

	mobile = validate_mobile(mobile_no)
	existing = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	if existing:
		return get_profile(existing)

	require_permission("Customer", "create")

	if not customer_name:
		frappe.throw(_("Customer Name is required to create a new customer."))

	branch = branch or get_user_branch()

	doc = frappe.new_doc("Customer")
	doc.customer_name = customer_name.strip()
	doc.customer_type = "Individual"
	doc.customer_group = _default_customer_group(customer_group)
	doc.territory = _default_territory(branch)
	doc.a3_mobile_no = mobile
	doc.a3_whatsapp_no = mobile
	doc.a3_source_branch = branch
	doc.a3_customer_since = getdate(nowdate())
	doc.a3_marketing_optin = 1 if int(marketing_optin or 0) else 0
	if email:
		doc.email_id = email

	try:
		doc.insert()
	except frappe.DuplicateEntryError:
		# Lost a race against another counter — return the winner.
		frappe.db.rollback()
		existing = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
		if existing:
			return get_profile(existing)
		raise

	return get_profile(doc.name)


def _default_customer_group(preferred: str | None = None) -> str:
	candidates = [preferred] if preferred else []
	candidates += ["Retail Walk-in", "Individual", "All Customer Groups"]
	for group in candidates:
		if group and frappe.db.exists("Customer Group", group):
			return group
	return frappe.db.get_value("Customer Group", {"is_group": 0}, "name")


def _default_territory(branch: str | None) -> str:
	"""Prefer a territory named after the branch, else the system default."""
	if branch:
		mapped = {
			"Kochi": "Ernakulam",
			"Thiruvananthapuram": "Thiruvananthapuram",
			"Kozhikode": "Kozhikode",
		}
		candidate = mapped.get(branch, branch)
		if frappe.db.exists("Territory", candidate):
			return candidate
	return frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"


def refresh_customer_stats(customer: str):
	"""Recompute lifetime value / device count / last dates for one customer."""
	if not frappe.db.exists("Customer", customer):
		return

	ltv = frappe.db.sql(
		"""select sum(base_grand_total) from `tabSales Invoice`
		   where customer = %s and docstatus = 1 and is_return = 0""",
		customer,
	)[0][0] or 0

	last_purchase = frappe.db.sql(
		"""select max(posting_date) from `tabSales Invoice`
		   where customer = %s and docstatus = 1""",
		customer,
	)[0][0]

	device_count = frappe.db.count("Serial No", {"customer": customer})

	frappe.db.set_value(
		"Customer",
		customer,
		{
			"a3_lifetime_value": ltv,
			"a3_last_purchase_date": last_purchase,
			"a3_device_count": device_count,
		},
		update_modified=False,
	)


def validate_customer(doc, method=None):
	"""Customer hook — normalise the mobile number and default WhatsApp to it."""
	if doc.get("a3_mobile_no"):
		doc.a3_mobile_no = normalize_mobile(doc.a3_mobile_no)
	if doc.get("a3_alternate_mobile"):
		doc.a3_alternate_mobile = normalize_mobile(doc.a3_alternate_mobile)
	if doc.get("a3_mobile_no") and not doc.get("a3_whatsapp_no"):
		doc.a3_whatsapp_no = doc.a3_mobile_no
	if not doc.get("a3_customer_since"):
		doc.a3_customer_since = getdate(nowdate())
