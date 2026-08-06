# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Job Card — the heart of the service module (scope 3.2).

Named `Service Job Card` rather than `Job Card` because ERPNext Manufacturing
already owns that name (ADR-03).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from a3_retail.a3_retail_service import tat
from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.utils import commit_if_not_testing, money, publish_dashboard_update
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.imei import enforce_imei, normalize_imei
from a3_retail.utils.naming import set_branch_code

# Statuses after which parts and labour may no longer be edited.
FROZEN_STATUSES = (st.DELIVERED, st.CLOSED, st.CANCELLED)


class ServiceJobCard(A3BranchMixin, Document):
	# ------------------------------------------------------------------ hooks
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.received_on:
			self.received_on = now_datetime()
		if not self.company:
			profile = get_branch_profile(self.branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.validate_status_transition()
		self.validate_imei()
		self.match_serial_number()
		self.detect_warranty()
		self.set_repair_category()
		self.compute_parts()
		self.compute_labour()
		self.compute_totals()
		self.apply_tat()
		self.set_payment_status()
		self.flag_repeat_customer()

	def before_update_after_submit(self):
		"""Frappe skips `validate` for submitted documents.

		A job card lives almost its entire life in docstatus 1 — technician
		assignment, parts, labour and every status hop happen after submit — so
		the same pipeline has to run here or none of it would ever execute.
		"""
		self.validate_status_transition()
		self.detect_warranty()
		self.compute_parts()
		self.compute_labour()
		self.compute_totals()
		self.apply_tat()
		self.set_payment_status()

	def before_submit(self):
		if self.status == st.DRAFT:
			self.status = st.OPEN
		self.validate_consent()
		if _require_signature() and not self.customer_signature:
			frappe.throw(_("Customer signature is required before submitting a job card."))
		if _require_photos() and self.photo_count() < _min_photos():
			frappe.throw(_("At least {0} device photo(s) required.").format(_min_photos()))

	def on_update(self):
		self.notify_dashboard()

	def on_update_after_submit(self):
		self.notify_dashboard()

	def on_submit(self):
		self.recompute_technician_wip()

	def on_cancel(self):
		self.flags.ignore_validate_update_after_submit = True
		self.db_set("status", st.CANCELLED, update_modified=False)
		self.recompute_technician_wip()

	# -------------------------------------------------------------- validation
	def validate_status_transition(self):
		"""Guard the state machine and record every hop (scope 3.3)."""
		if self.is_new():
			return

		previous = frappe.db.get_value("Service Job Card", self.name, "status")
		if not previous or previous == self.status:
			return

		st.validate_transition(previous, self.status)
		st.log_transition(self, previous, self.status)
		self.on_status_changed(previous, self.status)

	def on_status_changed(self, previous: str, current: str):
		"""Side effects that belong to a specific status (scope 3.3)."""
		now = now_datetime()

		if current == st.UNDER_DIAGNOSIS and not self.assigned_on:
			self.assigned_on = now
		if current in (st.ESTIMATE_PENDING, st.IN_PROGRESS) and not self.diagnosed_on:
			self.diagnosed_on = now
		if current == st.READY_FOR_DELIVERY:
			# A timestamp already on the document wins — back-dated history keeps
			# the date it actually happened.
			self.ready_on = self.ready_on or now
			self.generate_delivery_otp()
		if current == st.DELIVERED:
			self.delivered_on = self.delivered_on or now
		# Accumulate paused time so the TAT clock excludes it (scope 3.11).
		if previous in st.PAUSED_STATUSES and current not in st.PAUSED_STATUSES:
			self.accumulate_paused_hours(previous)

	def accumulate_paused_hours(self, paused_status: str):
		"""Add the hours just spent in a paused status to `paused_hours`."""
		entered_at = None
		for row in reversed(self.get("status_log") or []):
			if row.to_status == paused_status and row.changed_on:
				entered_at = row.changed_on
				break
		if not entered_at:
			return

		hours = tat.working_hours_between(entered_at, now_datetime(), self.branch)
		self.paused_hours = flt(self.paused_hours) + hours

	def validate_imei(self):
		self.imei_1 = normalize_imei(self.imei_1)
		self.imei_2 = normalize_imei(self.imei_2)

		if self.device_type in ("Mobile", "Tablet") and not self.imei_1:
			# A dead handset with a smashed screen cannot be asked for its IMEI,
			# and the box is rarely still around. The shop still takes it in —
			# but somebody has to say so on the card, which is what the override
			# is for, and the physical condition then has to describe what came
			# across the counter.
			if not self.imei_override:
				frappe.throw(
					_("IMEI 1 is required for a {0}. Tick 'IMEI Override' if the device "
					  "cannot show one, and describe it under physical condition.").format(
						self.device_type)
				)
			if not (self.physical_condition or "").strip():
				frappe.throw(
					_("Describe the device under physical condition — it came in without "
					  "an IMEI, so that description is all that identifies it.")
				)

		if self.imei_1:
			self.imei_1 = enforce_imei(self.imei_1, "IMEI 1", override=bool(self.imei_override))
		if self.imei_2:
			self.imei_2 = enforce_imei(self.imei_2, "IMEI 2", override=bool(self.imei_override))

	def match_serial_number(self):
		"""Link the device to our IMEI register when we sold it."""
		if not self.imei_1:
			self.sold_by_us = 0
			return

		serial = frappe.db.get_value(
			"Serial No",
			{"a3_imei_1": self.imei_1},
			["name", "a3_sales_invoice", "a3_activation_date", "a3_brand_warranty_expiry",
			 "a3_ew_registration"],
			as_dict=True,
		)
		if not serial:
			self.serial_no = None
			self.sold_by_us = 0
			return

		self.serial_no = serial.name
		self.sold_by_us = 1 if serial.a3_sales_invoice else 0
		self.purchase_invoice_ref = serial.a3_sales_invoice
		if not self.device_purchase_date:
			self.device_purchase_date = serial.a3_activation_date
		self.warranty_expiry_date = serial.a3_brand_warranty_expiry
		if serial.a3_ew_registration and not self.warranty_registration:
			self.warranty_registration = serial.a3_ew_registration

	def detect_warranty(self):
		"""Derive coverage and chargeability from the device's warranty state."""
		today = getdate(nowdate())

		if self.warranty_type == "Goodwill/Free":
			self.is_chargeable = 0
			return
		if self.warranty_type == "Insurance Claim":
			self.is_chargeable = 1
			return

		in_brand_warranty = bool(
			self.warranty_expiry_date and getdate(self.warranty_expiry_date) >= today
		)

		ew_expiry = None
		if self.warranty_registration and frappe.db.exists("DocType", "Warranty Registration"):
			ew_expiry = frappe.db.get_value(
				"Warranty Registration", self.warranty_registration, "ew_expiry_date"
			)
		in_ew = bool(ew_expiry and getdate(ew_expiry) >= today)

		if self.warranty_type not in ("Screen Protection Plan",):
			if in_brand_warranty:
				self.warranty_type = "Brand Warranty"
			elif in_ew:
				self.warranty_type = "Extended Warranty"
			else:
				self.warranty_type = "Out of Warranty"

		covered = self.warranty_type in (
			"Brand Warranty", "Extended Warranty", "Screen Protection Plan"
		)

		# Liquid or physical damage voids a manufacturer warranty (scope 3.6).
		if covered and self.warranty_type == "Brand Warranty" and self.repair_category in (
			"Liquid Damage", "Physical Damage"
		):
			self.warranty_type = "Out of Warranty"
			covered = False

		self.is_chargeable = 0 if covered else 1

	def validate_consent(self):
		"""Wiping a device without a backup needs consent on record (scope 3.2)."""
		if self.data_backup_required or self.data_loss_consent:
			return
		frappe.throw(
			_("Tick either 'Data Backup Required' or 'Customer Consented to Data Loss' before submitting.")
		)

	def set_repair_category(self):
		"""Default the repair category from the first reported issue."""
		if self.repair_category or not self.get("reported_issues"):
			return

		category = frappe.db.get_value(
			"Service Issue Type", self.reported_issues[0].issue_type, "category"
		)
		mapping = {
			"Display": "Display",
			"Battery": "Battery",
			"Software": "Software",
			"Board Level": "Hardware - Board Level",
			"Liquid Damage": "Liquid Damage",
			"Physical Damage": "Physical Damage",
		}
		self.repair_category = mapping.get(category, "Hardware - Component")

	# ------------------------------------------------------------------ totals
	def compute_parts(self):
		profile = get_branch_profile(self.branch)
		default_warehouse = profile.service_warehouse if profile else None

		for row in self.get("parts") or []:
			if not row.warehouse:
				row.warehouse = default_warehouse

			if row.is_customer_provided:
				row.rate = 0

			row.qty = flt(row.qty) or 1
			row.amount = money(flt(row.rate) * flt(row.qty))
			row.available_qty = get_bin_qty(row.item_code, row.warehouse)

			if not row.valuation_rate:
				row.valuation_rate = get_valuation_rate(row.item_code, row.warehouse)

	def compute_labour(self):
		# A device we could not repair is never charged for labour (scope 3.3,
		# status 14). Enforced here rather than on the transition so a later
		# recompute cannot silently put the rate back.
		no_labour_charge = self.status == st.NOT_REPAIRABLE

		for row in self.get("labour") or []:
			row.qty = flt(row.qty) or 1

			if no_labour_charge:
				row.rate = 0
				row.amount = 0
				row.technician_incentive = 0
				continue

			if not row.rate:
				row.rate = get_item_rate(row.service_item)
			if not row.minutes:
				row.minutes = cint(
					frappe.get_cached_value("Item", row.service_item, "a3_default_labour_minutes")
				)
			row.amount = money(flt(row.rate) * flt(row.qty))
			if not row.technician:
				row.technician = self.assigned_technician
			row.technician_incentive = money(
				flt(frappe.get_cached_value("Item", row.service_item, "a3_technician_incentive"))
				* flt(row.qty)
			)

	def compute_totals(self):
		"""Parts + labour - discount + tax, split by who bears the cost."""
		self.parts_total = money(sum(flt(r.amount) for r in self.get("parts") or []))
		self.labour_total = money(sum(flt(r.amount) for r in self.get("labour") or []))
		self.total_before_discount = money(flt(self.parts_total) + flt(self.labour_total))

		self.validate_discount()
		self.net_total = money(flt(self.total_before_discount) - flt(self.discount_amount))

		rate = self.tax_rate()
		self.tax_amount = money(flt(self.net_total) * rate / 100.0)
		self.grand_total = money(flt(self.net_total) + flt(self.tax_amount))

		# Lines flagged warranty-covered are borne by us / the underwriter.
		warranty_net = sum(
			flt(r.amount)
			for r in (self.get("parts") or []) + (self.get("labour") or [])
			if r.get("is_warranty_covered")
		)
		if not self.is_chargeable:
			warranty_net = flt(self.total_before_discount)

		warranty_gross = warranty_net * (1 + rate / 100.0)
		self.warranty_borne_amount = money(min(warranty_gross, flt(self.grand_total)))
		self.customer_payable = money(flt(self.grand_total) - flt(self.warranty_borne_amount))
		self.outstanding_amount = money(flt(self.customer_payable) - flt(self.advance_amount))

	def validate_discount(self):
		if not flt(self.discount_amount):
			return

		if not self.discount_reason:
			frappe.throw(_("A discount needs a reason."))

		if flt(self.discount_amount) > flt(self.total_before_discount):
			frappe.throw(_("Discount cannot exceed the total."))

		max_percent = flt(
			frappe.db.get_single_value("A3 Retail Settings", "max_discount_percent_branch_user")
		)
		if not max_percent or flt(self.total_before_discount) <= 0:
			return

		percent = flt(self.discount_amount) / flt(self.total_before_discount) * 100
		if percent > max_percent and not may_discount():
			frappe.throw(
				_("A discount above {0}% needs a Branch Manager.").format(max_percent),
				frappe.PermissionError,
			)

	def tax_rate(self) -> float:
		"""Total tax percentage from the selected template (default 18%)."""
		if not self.tax_template:
			return 18.0
		rows = frappe.get_all("Sales Taxes and Charges", filters={"parent": self.tax_template}, pluck="rate")
		total = sum(flt(r) for r in rows)
		return total or 18.0

	def apply_tat(self):
		tat.apply_policy(self)

	def set_payment_status(self):
		if not flt(self.customer_payable):
			self.payment_status = "Warranty - No Charge" if not self.is_chargeable else "Unpaid"
		elif flt(self.outstanding_amount) <= 0:
			self.payment_status = "Paid"
		elif flt(self.advance_amount) > 0:
			self.payment_status = "Partly Paid (Advance)"
		else:
			self.payment_status = "Unpaid"

	def flag_repeat_customer(self):
		if not self.customer:
			return
		count = frappe.db.count(
			"Service Job Card",
			{"customer": self.customer, "name": ["!=", self.name or "new"], "docstatus": 1},
		)
		self.is_repeat_customer = 1 if count else 0

	# ---------------------------------------------------------------- helpers
	def photo_count(self) -> int:
		return sum(1 for i in range(1, 5) if self.get(f"device_photo_{i}"))

	def generate_delivery_otp(self):
		"""6-digit OTP handed to the customer when the device is ready."""
		import secrets

		self.delivery_otp = f"{secrets.randbelow(1000000):06d}"
		self.otp_verified = 0

	def recompute_technician_wip(self):
		if not self.assigned_technician:
			return
		from a3_retail.a3_retail_service.doctype.technician_profile.technician_profile import recompute_wip

		recompute_wip(self.assigned_technician)

	def notify_dashboard(self):
		publish_dashboard_update(self.branch_code, {"branch": self.branch, "job_card": self.name})

	@property
	def is_frozen(self) -> bool:
		return self.status in FROZEN_STATUSES


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
def get_bin_qty(item_code: str | None, warehouse: str | None) -> float:
	if not item_code or not warehouse:
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


def get_valuation_rate(item_code: str | None, warehouse: str | None) -> float:
	if not item_code or not warehouse:
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))


def get_item_rate(item_code: str | None, price_list: str | None = None) -> float:
	if not item_code:
		return 0.0
	price_list = (
		price_list
		or frappe.db.get_single_value("Selling Settings", "selling_price_list")
		or "Retail Kerala"
	)
	rate = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list, "selling": 1}, "price_list_rate"
	)
	return flt(rate) or flt(frappe.get_cached_value("Item", item_code, "standard_rate"))


def _require_signature() -> bool:
	return bool(frappe.db.get_single_value("A3 Retail Settings", "require_signature"))


def _require_photos() -> bool:
	return bool(frappe.db.get_single_value("A3 Retail Settings", "require_device_photos"))


def _min_photos() -> int:
	return cint(frappe.db.get_single_value("A3 Retail Settings", "min_photos")) or 1


def may_discount(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	roles = {"Branch Manager", "A3 Retail Admin", "System Manager"}
	settings = frappe.get_cached_doc("A3 Retail Settings")
	for row in settings.get("allow_discount_roles") or []:
		if row.get("role"):
			roles.add(row.role)
	return bool(roles & set(frappe.get_roles(user)))


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def flag_delayed_job_cards():
	"""Hourly — set is_delayed, delay_hours and escalation_level (scope 3.2)."""
	now = now_datetime()
	rows = frappe.get_all(
		"Service Job Card",
		filters={
			"docstatus": 1,
			"status": ["not in", list(st.TERMINAL_STATUSES)],
			"sla_due_on": ["is", "set"],
		},
		fields=["name", "branch", "sla_due_on", "is_delayed", "tat_policy"],
	)

	flagged = 0
	for row in rows:
		due = get_datetime(row.sla_due_on)
		if due >= now:
			if row.is_delayed:
				frappe.db.set_value(
					"Service Job Card",
					row.name,
					{"is_delayed": 0, "delay_hours": 0, "escalation_level": "None"},
					update_modified=False,
				)
			continue

		delay_hours = tat.working_hours_between(due, now, row.branch)
		frappe.db.set_value(
			"Service Job Card",
			row.name,
			{
				"is_delayed": 1,
				"delay_hours": delay_hours,
				"escalation_level": escalation_for(delay_hours, row.tat_policy),
			},
			update_modified=False,
		)
		flagged += 1

	commit_if_not_testing()
	return flagged


def escalation_for(delay_hours: float, policy_name: str | None = None) -> str:
	"""Escalate at 1x / 2x / 4x of a quarter of the policy TAT."""
	threshold = 12.0
	if policy_name:
		policy_tat = flt(frappe.db.get_value("Service TAT Policy", policy_name, "tat_hours"))
		if policy_tat:
			threshold = max(policy_tat * 0.25, 4.0)

	if delay_hours >= threshold * 4:
		return "L3 - Head Office"
	if delay_hours >= threshold * 2:
		return "L2 - Branch Manager"
	if delay_hours >= threshold:
		return "L1 - Service Manager"
	return "None"


def auto_close_delivered():
	"""Daily — close job cards delivered more than N days ago (scope 3.3, status 17)."""
	days = cint(frappe.db.get_single_value("A3 Retail Settings", "auto_close_after_days")) or 7
	cutoff = add_days(nowdate(), -days)

	names = frappe.get_all(
		"Service Job Card",
		filters={"docstatus": 1, "status": st.DELIVERED, "delivered_on": ["<", cutoff]},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc("Service Job Card", name)
		doc.status = st.CLOSED
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

	commit_if_not_testing()
	return len(names)


# ---------------------------------------------------------------------------
# Whitelisted actions
# ---------------------------------------------------------------------------
@frappe.whitelist()
def assign_technician(job_card: str, technician: str) -> dict:
	"""Assign a technician and move the card into diagnosis."""
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	doc.assigned_technician = technician
	doc.assigned_on = now_datetime()
	if doc.status == st.OPEN:
		doc.status = st.UNDER_DIAGNOSIS
	doc.save()

	return {"job_card": doc.name, "status": doc.status, "technician": technician}


@frappe.whitelist()
def set_status(job_card: str, status: str, remarks: str | None = None) -> dict:
	"""Move a job card through the state machine with validation."""
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Service Job Card", job_card)
	require_permission("Service Job Card", "write", doc)

	previous = doc.status
	doc.status = status
	if remarks and status == st.ON_HOLD:
		doc.hold_reason = remarks
	if remarks and status == st.CANCELLED:
		doc.delay_reason = None
	doc.save()

	return {"job_card": doc.name, "from": previous, "to": doc.status}


@frappe.whitelist()
def get_allowed_transitions(job_card: str) -> list[str]:
	from a3_retail.api import require_permission

	require_permission("Service Job Card", "read")
	status = frappe.db.get_value("Service Job Card", job_card, "status")
	return list(st.next_statuses(status))
