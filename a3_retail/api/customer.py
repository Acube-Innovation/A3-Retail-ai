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


def normalize_gstin(gstin: str | None) -> str:
	"""Upper-case, strip spaces. A blank GSTIN is a walk-in, not an error."""
	return re.sub(r"\s+", "", str(gstin or "")).upper()


def validate_gstin(gstin: str | None) -> str:
	"""Check a GSTIN before it reaches a bill, in words the counter can act on.

	A wrong GSTIN is worse than none: the buyer cannot claim the credit and the
	return has to be amended. India Compliance checks the length and the check
	digit, so a typo is caught here rather than at the GST portal — but its
	message names field codes, so it is restated for the person at the counter.
	"""
	gstin = normalize_gstin(gstin)
	if not gstin:
		return ""
	try:
		from india_compliance.gst_india.utils import validate_gstin as _check
	except ImportError:
		if len(gstin) != 15:
			frappe.throw(_("A GSTIN is 15 characters. {0} has {1}.")
			             .format(gstin, len(gstin)), title=_("Check the GSTIN"))
		return gstin
	try:
		_check(gstin)
	except frappe.ValidationError:
		frappe.throw(
			_("{0} is not a valid GSTIN. Check it against the buyer's papers — "
			  "a wrong one costs them the input credit.").format(gstin),
			title=_("Check the GSTIN"))
	return gstin


def gstin_state(gstin: str | None) -> str | None:
	"""The state a GSTIN belongs to, from its first two digits.

	This is what decides place of supply, and so whether the bill carries IGST or
	CGST/SGST. Taking it from the GSTIN rather than from a typed address means a
	B2B bill is taxed on the buyer's registration, which is the figure that has
	to agree with their return.
	"""
	gstin = normalize_gstin(gstin)
	if len(gstin) != 15:
		return None
	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS
	except ImportError:
		return None
	return {number: name for name, number in STATE_NUMBERS.items()}.get(gstin[:2])


def gstin_details(gstin: str) -> dict:
	"""Everything a GSTIN can tell us about the party it belongs to.

	Shared by the customer and the supplier screens, because a GST number means
	the same thing whichever side of the counter the party is on, and two copies
	of this would drift apart.

	The live portal lookup needs an India Compliance API subscription. Without
	one the number is still checked and the state read out of it — the first two
	digits *are* the state code — and `note` says which of the two happened, so
	the screen never shows a half-filled form with no explanation.
	"""
	gstin = normalize_gstin(gstin)
	if not gstin:
		frappe.throw(_("Enter the GST number first."), title=_("GSTIN"))

	validate_gstin(gstin)
	out = {"gstin": gstin, "state": gstin_state(gstin), "source": "number"}

	if not frappe.db.get_single_value("GST Settings", "api_secret"):
		out["note"] = _("Checked the number. Full details need the GST API, "
		                "which head office has not switched on yet.")
		return out

	try:
		from india_compliance.gst_india.utils.gstin_info import _get_gstin_info

		info = _get_gstin_info(gstin, throw_error=False) or {}
	except Exception:
		frappe.clear_last_message()
		info = {}

	if not info.get("business_name"):
		out["note"] = _("Checked the number, but the GST portal did not answer. "
		                "Fill the rest in by hand.")
		return out

	address = info.get("permanent_address") or {}
	out.update({
		"party_name": info.get("business_name"),
		"gst_category": info.get("gst_category"),
		"state": address.get("state") or out["state"],
		"address_line1": address.get("address_line1"),
		"address_line2": address.get("address_line2"),
		"city": address.get("city"),
		"pincode": address.get("pincode"),
		"source": "portal",
	})
	return out


@frappe.whitelist()
def gstin_info(gstin: str) -> dict:
	"""Look a buyer's GSTIN up so the counter does not retype their details.

	India Compliance's own endpoint refuses anyone without desk access, and
	branch staff are Website Users by design — so the caller is guarded here and
	the shared lookup does the work.
	"""
	require_permission("Customer", "create")

	out = gstin_details(gstin)
	if out.get("party_name"):
		out["customer_name"] = out["party_name"]
	return out


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
		# So a screen can tell a business buyer from a walk-in, and show the
		# number back when their details are edited.
		"gstin": doc.get("gstin"),
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
	gstin: str | None = None,
) -> dict:
	"""Find a customer by mobile, or create one. Idempotent by mobile number.

	The unique index on `Customer.a3_mobile_no` is what actually prevents
	duplicates; the pre-check just avoids a noisy exception on the happy path.

	`gstin` makes the customer a registered buyer, so the bill can be raised B2B.
	A shop often meets the same buyer as a walk-in first and is handed the GSTIN
	only when they want a company bill, so one supplied for a customer already
	on file is filled in rather than ignored.
	"""
	require_permission("Customer", "read")

	mobile = validate_mobile(mobile_no)
	gstin = validate_gstin(gstin)
	existing = frappe.db.get_value("Customer", {"a3_mobile_no": mobile}, "name")
	if existing:
		if gstin:
			_apply_gstin(existing, gstin)
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
	if gstin:
		doc.gstin = gstin
		doc.gst_category = _gst_category(gstin)
		# A GSTIN belongs to a business, and ERPNext prints the type on the bill.
		doc.customer_type = "Company"

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


def _gst_category(gstin: str) -> str:
	"""What kind of registration this GSTIN is — India Compliance works it out."""
	try:
		from india_compliance.gst_india.utils import guess_gst_category
	except ImportError:
		return "Registered Regular"
	return guess_gst_category(gstin, "India") or "Registered Regular"


def _apply_gstin(customer: str, gstin: str) -> None:
	"""Record a GSTIN against a customer already on file.

	Only ever fills a gap or corrects a typo the counter is re-entering; it never
	quietly moves a bill from one registration to another, because past invoices
	were filed under the old number.
	"""
	current = frappe.db.get_value("Customer", customer, "gstin")
	if normalize_gstin(current) == gstin:
		return
	if current:
		frappe.throw(
			_("{0} is already registered under GSTIN {1}. Head office has to change "
			  "it, because bills already filed carry the old number.")
			.format(frappe.db.get_value("Customer", customer, "customer_name"), current),
			title=_("GSTIN already set"))
	require_permission("Customer", "write")
	doc = frappe.get_doc("Customer", customer)
	doc.gstin = gstin
	doc.gst_category = _gst_category(gstin)
	doc.customer_type = "Company"
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)


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
