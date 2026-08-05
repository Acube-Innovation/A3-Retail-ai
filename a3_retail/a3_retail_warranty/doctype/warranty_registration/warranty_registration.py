# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Warranty Registration (scope 5.3).

This is the single source of truth for "is this device covered". Every other
module — the job card, the reception desk, the POS, the portal — asks this
record, never the Item or the Serial No directly.
"""

import hashlib
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, flt, get_url, getdate, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin

ACTIVE = "Active"
EXPIRING_SOON = "Expiring Soon"
EXPIRED = "Expired"
FULLY_CLAIMED = "Fully Claimed"
VOID = "Void"
CANCELLED = "Cancelled"

EXPIRING_WINDOW_DAYS = 30


def hash_token(token: str) -> str:
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


class WarrantyRegistration(A3BranchMixin, Document):
	def before_validate(self):
		self.pull_device_details()
		self.set_branch_defaults()

	def validate(self):
		self.compute_brand_warranty()
		self.compute_plan_dates()
		self.compute_claim_limits()
		self.refresh_status()

	def before_update_after_submit(self):
		self.compute_brand_warranty()
		self.compute_plan_dates()
		self.compute_claim_limits()
		self.refresh_status()

	def on_submit(self):
		self.issue_certificate()
		self.stamp_serial()

	def on_cancel(self):
		self.status = CANCELLED
		self.clear_serial_stamp()

	# ------------------------------------------------------------------ detail
	def pull_device_details(self):
		if not self.serial_no or not frappe.db.exists("Serial No", self.serial_no):
			return

		serial = frappe.db.get_value(
			"Serial No", self.serial_no,
			["item_code", "a3_imei_1", "a3_activation_date", "a3_sales_invoice"], as_dict=True,
		)
		self.imei_1 = serial.a3_imei_1 or self.serial_no
		self.item_code = serial.item_code
		if not self.sales_invoice:
			self.sales_invoice = serial.a3_sales_invoice
		if not self.purchase_date:
			self.purchase_date = serial.a3_activation_date

		item = frappe.get_cached_value(
			"Item", serial.item_code, ["item_name", "brand", "a3_device_model", "a3_brand_warranty_months"],
			as_dict=True,
		)
		self.item_name = item.item_name
		self.brand = item.brand
		self.device_model = item.a3_device_model
		if not self.brand_warranty_months:
			self.brand_warranty_months = cint(item.a3_brand_warranty_months)

		if not flt(self.device_value) and self.sales_invoice:
			self.device_value = flt(
				frappe.db.get_value(
					"Sales Invoice Item",
					{"parent": self.sales_invoice, "item_code": serial.item_code},
					"rate",
				)
			)

	def compute_brand_warranty(self):
		if self.purchase_date and cint(self.brand_warranty_months):
			self.brand_warranty_expiry = add_months(
				getdate(self.purchase_date), cint(self.brand_warranty_months)
			)

	def compute_plan_dates(self):
		"""A plan can start at purchase or only once the brand warranty runs out."""
		if not self.ew_plan:
			self.ew_start_date = None
			self.ew_expiry_date = None
			return

		plan = frappe.get_cached_doc("Extended Warranty Plan", self.ew_plan)
		self.plan_item = plan.plan_item
		if not flt(self.plan_amount):
			self.plan_amount = flt(plan.plan_price)

		if plan.starts_from == "After Brand Warranty Expiry" and self.brand_warranty_expiry:
			start = add_days(getdate(self.brand_warranty_expiry), 1)
		else:
			start = getdate(self.purchase_date or nowdate())

		start = add_days(start, cint(plan.waiting_period_days))
		self.ew_start_date = start
		self.ew_expiry_date = add_months(start, cint(plan.duration_months))

	def compute_claim_limits(self):
		if not self.ew_plan:
			self.max_claims = 0
			self.claim_value_cap = 0
			self.deductible_amount = 0
			return

		plan = frappe.get_cached_doc("Extended Warranty Plan", self.ew_plan)
		self.max_claims = cint(plan.max_claims)
		self.deductible_amount = flt(plan.deductible_amount)
		self.claim_value_cap = money(
			flt(self.device_value) * flt(plan.claim_value_cap_percent or 100) / 100
		)

	def refresh_status(self):
		"""Void and Cancelled are sticky; everything else follows the dates."""
		if self.status in (VOID, CANCELLED):
			return

		if cint(self.max_claims) and cint(self.claims_used) >= cint(self.max_claims):
			self.status = FULLY_CLAIMED
			return

		expiry = self.effective_expiry()
		if not expiry:
			self.status = ACTIVE
			return

		today = getdate(nowdate())
		if getdate(expiry) < today:
			self.status = EXPIRED
		elif getdate(expiry) <= add_days(today, EXPIRING_WINDOW_DAYS):
			self.status = EXPIRING_SOON
		else:
			self.status = ACTIVE

	def effective_expiry(self):
		"""The later of the two covers — that is when protection really ends."""
		dates = [d for d in (self.brand_warranty_expiry, self.ew_expiry_date) if d]
		return max(getdate(d) for d in dates) if dates else None

	# ------------------------------------------------------------ certificate
	def issue_certificate(self):
		token = secrets.token_urlsafe(18)
		self.db_set("certificate_no", self.name, update_modified=False)
		self.db_set("certificate_token_hash", hash_token(token), update_modified=False)
		self.db_set("certificate_url", f"{get_url()}/warranty/{token}", update_modified=False)
		self.flags.certificate_token = token

	def stamp_serial(self):
		if not self.serial_no or not frappe.db.exists("Serial No", self.serial_no):
			return

		values = {"a3_brand_warranty_expiry": self.brand_warranty_expiry}
		if self.ew_plan:
			values["a3_ew_registration"] = self.name
			values["a3_ew_expiry"] = self.ew_expiry_date

		frappe.db.set_value("Serial No", self.serial_no, values, update_modified=False)

	def clear_serial_stamp(self):
		if not self.serial_no or not frappe.db.exists("Serial No", self.serial_no):
			return
		if frappe.db.get_value("Serial No", self.serial_no, "a3_ew_registration") != self.name:
			return
		frappe.db.set_value(
			"Serial No", self.serial_no,
			{"a3_ew_registration": None, "a3_ew_expiry": None}, update_modified=False,
		)

	# ----------------------------------------------------------------- claims
	def covers(self, component: str | None = None) -> bool:
		"""Is this registration usable for a claim right now?"""
		if self.status not in (ACTIVE, EXPIRING_SOON):
			return False
		if cint(self.max_claims) and cint(self.claims_used) >= cint(self.max_claims):
			return False
		if not component or not self.ew_plan:
			return True

		covered = frappe.get_all(
			"Warranty Coverage Item",
			filters={"parent": self.ew_plan},
			fields=["component", "is_covered"],
		)
		# A plan with no component list covers everything; once a list exists it
		# is exhaustive, so anything absent from it is *not* covered — otherwise a
		# screen-only plan would silently cover the motherboard.
		if not covered:
			return True

		match = next((row for row in covered if row.component == component), None)
		return bool(match and match.is_covered)

	def check_claim(self, amount: float, component: str | None = None):
		"""Throw with the actual reason a claim cannot be made (scope 5.3)."""
		if self.status == VOID:
			frappe.throw(_("Warranty {0} is void: {1}").format(self.name, self.void_reason or "-"))
		if self.status == EXPIRED:
			frappe.throw(_("Warranty {0} expired on {1}.").format(self.name, self.effective_expiry()))
		if cint(self.max_claims) and cint(self.claims_used) >= cint(self.max_claims):
			frappe.throw(
				_("Warranty {0} has used all {1} claims.").format(self.name, self.max_claims)
			)
		if not self.covers(component):
			frappe.throw(_("{0} is not covered by {1}.").format(component, self.ew_plan))

		projected = flt(self.claim_value_used) + flt(amount)
		if flt(self.claim_value_cap) and projected > flt(self.claim_value_cap):
			frappe.throw(
				_("This claim would exceed the cap of {0} (already used {1}).").format(
					frappe.format_value(self.claim_value_cap, {"fieldtype": "Currency"}),
					frappe.format_value(self.claim_value_used, {"fieldtype": "Currency"}),
				)
			)

	def record_claim(self, job_card: str, amount: float, status: str = "Approved"):
		"""Book a claim against the registration (called on job card delivery)."""
		self.append(
			"claims",
			{"job_card": job_card, "claim_date": getdate(nowdate()), "amount": flt(amount),
			 "status": status},
		)
		self.claims_used = cint(self.claims_used) + 1
		self.claim_value_used = money(flt(self.claim_value_used) + flt(amount))
		self.refresh_status()
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)
		return self


# ---------------------------------------------------------------------------
# Auto-registration on sale (scope 5.3)
# ---------------------------------------------------------------------------
def register_from_invoice(doc, method=None):
	"""Create a registration for every device line on a submitted invoice."""
	if doc.get("is_return"):
		return

	from a3_retail.overrides.sales_invoice import _row_serials

	plan_rows = [
		row for row in doc.get("items") or []
		if frappe.get_cached_value("Item", row.item_code, "a3_is_ew_plan")
	]

	for row in doc.get("items") or []:
		if not frappe.get_cached_value("Item", row.item_code, "a3_is_device"):
			continue

		for serial in _row_serials(row):
			if frappe.db.exists("Warranty Registration", {"serial_no": serial, "docstatus": 1}):
				continue
			_create_registration(doc, row, serial, plan_rows)


def _create_registration(invoice, item_row, serial: str, plan_rows: list):
	registration = frappe.new_doc("Warranty Registration")
	registration.customer = invoice.customer
	registration.branch = invoice.get("branch")
	registration.serial_no = serial
	registration.sales_invoice = invoice.name
	registration.purchase_date = getdate(invoice.posting_date)
	registration.device_value = flt(item_row.rate)
	registration.registration_type = "Brand Warranty Only"

	# A plan sold on the same invoice attaches to the device automatically.
	plan = _match_plan(plan_rows)
	if plan:
		registration.ew_plan = plan["plan"]
		registration.plan_amount = plan["amount"]
		registration.registration_type = plan["type"]

	registration.flags.ignore_permissions = True
	registration.insert(ignore_permissions=True)
	registration.submit()
	return registration.name


def _match_plan(plan_rows: list) -> dict | None:
	for row in plan_rows:
		plan = frappe.db.get_value(
			"Extended Warranty Plan", {"plan_item": row.item_code, "is_active": 1},
			["name", "coverage_type"], as_dict=True,
		)
		if not plan:
			continue

		mapping = {
			"Extended Warranty": "Extended Warranty",
			"Screen Protection": "Screen Protection",
			"Combo (EW + Screen)": "Combo",
			"Accidental & Liquid Damage": "Extended Warranty",
			"Theft Protection": "Extended Warranty",
		}
		return {
			"plan": plan.name,
			"amount": flt(row.rate),
			"type": mapping.get(plan.coverage_type, "Extended Warranty"),
		}
	return None


@frappe.whitelist()
def attach_plan(serial_no: str, plan: str, sales_invoice: str | None = None,
                amount: float = 0) -> str:
	"""Sell a plan after the device, within the plan's sale window (scope 5.3)."""
	from a3_retail.api import require_permission

	require_permission("Warranty Registration", "create")

	plan_doc = frappe.get_cached_doc("Extended Warranty Plan", plan)
	existing = frappe.db.get_value(
		"Warranty Registration", {"serial_no": serial_no, "docstatus": 1}, "name"
	)
	if not existing:
		frappe.throw(_("{0} has no warranty registration to attach a plan to.").format(serial_no))

	registration = frappe.get_doc("Warranty Registration", existing)
	if registration.ew_plan:
		frappe.throw(_("{0} already carries plan {1}.").format(serial_no, registration.ew_plan))

	window = cint(plan_doc.sale_window_days)
	if window and registration.purchase_date:
		deadline = add_days(getdate(registration.purchase_date), window)
		if getdate(nowdate()) > deadline:
			frappe.throw(
				_("{0} can only be sold within {1} days of purchase (until {2}).").format(
					plan, window, deadline
				)
			)

	registration.ew_plan = plan
	registration.plan_amount = flt(amount) or flt(plan_doc.plan_price)
	registration.registration_type = "Extended Warranty"
	if sales_invoice:
		registration.sales_invoice = sales_invoice
	registration.flags.ignore_permissions = True
	registration.save(ignore_permissions=True)
	registration.stamp_serial()

	return registration.name


# ---------------------------------------------------------------------------
# Scheduler and API
# ---------------------------------------------------------------------------
def recompute_statuses():
	"""Daily — move registrations into Expiring Soon / Expired (scope 5.3)."""
	names = frappe.get_all(
		"Warranty Registration",
		filters={"docstatus": 1, "status": ["not in", [VOID, CANCELLED, EXPIRED]]},
		pluck="name",
	)
	changed = 0
	for name in names:
		doc = frappe.get_doc("Warranty Registration", name)
		before = doc.status
		doc.refresh_status()
		if doc.status != before:
			doc.db_set("status", doc.status, update_modified=False)
			changed += 1

	commit_if_not_testing()
	return changed


def send_renewal_reminders():
	"""Daily — nudge at the offsets configured in A3 Retail Settings."""
	settings = frappe.get_cached_doc("A3 Retail Settings")
	offsets = [cint(row.days_before) for row in settings.get("ew_reminder_days") or []]
	if not offsets:
		return 0

	from a3_retail.communication.engine import notify

	sent = 0
	today = getdate(nowdate())
	for offset in offsets:
		target = add_days(today, offset)
		rows = frappe.get_all(
			"Warranty Registration",
			filters={"docstatus": 1, "status": ["in", [ACTIVE, EXPIRING_SOON, EXPIRED]]},
			fields=["name", "customer", "customer_mobile", "item_name", "ew_expiry_date",
			        "brand_warranty_expiry"],
		)
		for row in rows:
			expiry = row.ew_expiry_date or row.brand_warranty_expiry
			if not expiry or getdate(expiry) != target:
				continue
			notify(
				"ew_renewal_reminder" if offset >= 0 else "ew_winback_offer",
				to_number=row.customer_mobile,
				params={"1": row.customer, "2": str(expiry), "3": row.item_name},
				stream="Warranty",
			)
			sent += 1

	commit_if_not_testing()
	return sent


@frappe.whitelist()
def check(imei: str) -> dict:
	"""Warranty status for an IMEI — the JSON contract in scope 5.6."""
	from a3_retail.api import require_permission
	from a3_retail.utils.imei import normalize_imei

	require_permission("Serial No", "read")

	imei = normalize_imei(imei)
	serial_name = frappe.db.get_value("Serial No", {"a3_imei_1": imei}, "name")
	if not serial_name:
		return {"imei": imei, "found": False}

	serial = frappe.get_doc("Serial No", serial_name)
	item = frappe.get_cached_value("Item", serial.item_code, ["item_name"], as_dict=True)

	payload = {
		"imei": imei,
		"found": True,
		"item_code": serial.item_code,
		"device": item.item_name,
		"customer": serial.customer,
		"sold_by_us": bool(serial.a3_sales_invoice),
		"purchase_date": str(serial.a3_activation_date or ""),
		"brand_warranty_expiry": str(serial.a3_brand_warranty_expiry or ""),
		"brand_warranty_days_left": _days_left(serial.a3_brand_warranty_expiry),
		"extended_warranty": None,
		"state": serial.a3_warranty_state,
		"service_history": [],
	}

	registration = frappe.db.get_value(
		"Warranty Registration",
		{"serial_no": serial_name, "docstatus": 1},
		["name", "ew_plan", "ew_start_date", "ew_expiry_date", "claims_used", "max_claims",
		 "claim_value_used", "claim_value_cap", "status"],
		as_dict=True,
	)
	if registration and registration.ew_plan:
		payload["extended_warranty"] = {
			"registration": registration.name,
			"plan": registration.ew_plan,
			"start": str(registration.ew_start_date or ""),
			"expiry": str(registration.ew_expiry_date or ""),
			"claims_used": cint(registration.claims_used),
			"max_claims": cint(registration.max_claims),
			"claim_value_used": flt(registration.claim_value_used),
			"claim_value_cap": flt(registration.claim_value_cap),
			"status": registration.status,
		}

	if frappe.db.exists("DocType", "Service Job Card"):
		payload["service_history"] = frappe.get_all(
			"Service Job Card",
			filters={"imei_1": imei, "docstatus": 1},
			fields=["name as job_card", "received_on as date", "complaint_description as issue", "status"],
			order_by="received_on desc",
			limit_page_length=10,
		)

	return payload


def _days_left(expiry) -> int:
	if not expiry:
		return 0
	return max(frappe.utils.date_diff(expiry, nowdate()), 0)
