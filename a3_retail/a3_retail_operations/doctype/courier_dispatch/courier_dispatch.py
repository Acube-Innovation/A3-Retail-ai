# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Courier Dispatch (scope 7.4).

Freight comes off the partner's rate card, the tracking URL is built from their
pattern, and the status drives the rest of the system: Delivered closes the job
card, Lost/Damaged raises a Stock Damage Report against the courier.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, now_datetime, nowdate

from a3_retail.utils import commit_if_not_testing, money
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.naming import set_branch_code

GST_RATE = 18.0

BOOKED = "Booked"
IN_TRANSIT = "In Transit"
DELIVERED = "Delivered"
FAILED = "Delivery Failed"
RTO = "RTO (Returned)"
LOST = "Lost / Damaged"

OPEN_STATUSES = (BOOKED, "Picked Up", IN_TRANSIT, "Out for Delivery")


class CourierDispatch(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.dispatch_date:
			self.dispatch_date = now_datetime()
		if not self.company:
			profile = get_branch_profile(self.branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.pull_consignee()
		self.derive_zone()
		self.set_expected_delivery()
		self.compute_freight()
		self.build_tracking_url()
		self.compute_delay()

	def before_update_after_submit(self):
		self.set_expected_delivery()
		self.compute_freight()
		self.build_tracking_url()
		self.compute_delay()
		self.status_updated_on = now_datetime()

	def before_submit(self):
		if not self.awb_no and self.courier_partner != "Own Rider":
			frappe.throw(_("An AWB / docket number is required before dispatching."))

	def on_update_after_submit(self):
		self.apply_status_side_effects()

	# ------------------------------------------------------------------ detail
	def pull_consignee(self):
		"""Fill the address block from the linked party or job card."""
		if self.consignee_name and self.consignee_mobile:
			return

		if self.consignee_type == "Customer" and self.consignee:
			customer = frappe.db.get_value(
				"Customer", self.consignee, ["customer_name", "a3_mobile_no"], as_dict=True
			)
			if customer:
				self.consignee_name = self.consignee_name or customer.customer_name
				self.consignee_mobile = self.consignee_mobile or customer.a3_mobile_no

		if self.reference_type == "Service Job Card" and self.reference_name:
			job = frappe.db.get_value(
				"Service Job Card", self.reference_name,
				["customer", "customer_name", "customer_mobile"], as_dict=True,
			)
			if job:
				self.consignee = self.consignee or job.customer
				self.consignee_name = self.consignee_name or job.customer_name
				self.consignee_mobile = self.consignee_mobile or job.customer_mobile

	def derive_zone(self):
		"""Rate cards are priced by zone, and the pincode is what we actually know.

		Kerala pincodes start 67-69; the six metro circles are listed explicitly.
		Anything else is Rest of India.
		"""
		if self.zone or not self.pincode:
			return

		pincode = str(self.pincode).strip()
		if len(pincode) < 2:
			return

		prefix2 = pincode[:2]
		branch_pincode = _branch_pincode(self.branch)

		if branch_pincode and pincode[:3] == str(branch_pincode)[:3]:
			self.zone = "Within City"
		elif prefix2 in ("67", "68", "69"):
			self.zone = "Within State"
		elif prefix2 in ("11", "40", "56", "60", "70", "50"):
			self.zone = "Metro"
		elif prefix2 in ("78", "79", "18"):
			self.zone = "North East & J&K"
		else:
			self.zone = "Rest of India"

	def set_expected_delivery(self):
		if self.expected_delivery_date or not self.courier_partner:
			return

		tat = cint(frappe.db.get_value("Courier Partner", self.courier_partner, "standard_tat_days")) or 2
		rate_row = self._rate_row()
		if rate_row and cint(rate_row.tat_days):
			tat = cint(rate_row.tat_days)

		self.expected_delivery_date = add_days(getdate(self.dispatch_date), tat)

	def _rate_row(self):
		"""The rate-card row matching this service type and weight."""
		if not self.courier_partner:
			return None

		rows = frappe.get_all(
			"Courier Rate Card",
			filters={"parent": self.courier_partner},
			fields=["zone", "service_type", "weight_slab_from", "weight_slab_to", "base_rate",
			        "per_additional_500g", "fuel_surcharge_percent", "tat_days"],
		)
		weight = flt(self.weight_kg) or 0.5

		def matches(row, check_zone: bool) -> bool:
			if check_zone and self.zone and row.zone != self.zone:
				return False
			if self.service_type and row.service_type != self.service_type:
				return False
			if weight < flt(row.weight_slab_from):
				return False
			return True

		# Prefer the row for this zone. When the partner has no card for the zone,
		# fall back to the cheapest row for the service rather than whichever
		# happens to come back first — never silently over-charge.
		zoned = [row for row in rows if matches(row, True)]
		if zoned:
			return frappe._dict(min(zoned, key=lambda r: flt(r.base_rate)))

		any_service = [row for row in rows if matches(row, False)]
		if any_service:
			return frappe._dict(min(any_service, key=lambda r: flt(r.base_rate)))

		return frappe._dict(min(rows, key=lambda r: flt(r.base_rate))) if rows else None

	def compute_freight(self):
		"""Base rate plus per-500 g overflow, then fuel surcharge and GST."""
		row = self._rate_row()
		if row and not flt(self.freight_amount):
			weight = flt(self.weight_kg) or 0.5
			slab_to = flt(row.weight_slab_to) or weight
			extra_kg = max(weight - slab_to, 0)
			extra_units = int(extra_kg / 0.5 + 0.999) if extra_kg > 0 else 0
			self.freight_amount = money(
				flt(row.base_rate) + extra_units * flt(row.per_additional_500g)
			)

		surcharge_percent = flt(row.fuel_surcharge_percent) if row else 0
		self.fuel_surcharge = money(flt(self.freight_amount) * surcharge_percent / 100)

		taxable = flt(self.freight_amount) + flt(self.fuel_surcharge) + flt(self.other_charges)
		self.gst_amount = money(taxable * GST_RATE / 100)
		self.total_cost = money(taxable + flt(self.gst_amount))

	def build_tracking_url(self):
		if not self.awb_no or not self.courier_partner:
			return
		pattern = frappe.db.get_value("Courier Partner", self.courier_partner, "tracking_url_pattern")
		if pattern:
			self.tracking_url = pattern.replace("{awb}", self.awb_no)

	def compute_delay(self):
		"""Delay measured against the promise, whether or not it has arrived."""
		if not self.expected_delivery_date:
			self.delay_days = 0
			return

		if self.status == DELIVERED and self.actual_delivery_date:
			reference = getdate(self.actual_delivery_date)
		elif self.status in OPEN_STATUSES:
			reference = getdate(nowdate())
		else:
			self.delay_days = 0
			return

		self.delay_days = max(date_diff(reference, getdate(self.expected_delivery_date)), 0)

	# ------------------------------------------------------------ side effects
	def apply_status_side_effects(self):
		if self.status == DELIVERED:
			self._close_job_card()
		elif self.status == LOST:
			self._raise_damage_report()

	def _close_job_card(self):
		"""A delivered service return marks the job card delivered too."""
		if self.reference_type != "Service Job Card" or not self.reference_name:
			return

		from a3_retail.a3_retail_service.doctype.service_job_card import state as st

		job = frappe.get_doc("Service Job Card", self.reference_name)
		if job.status != st.READY_FOR_DELIVERY:
			return

		job.status = st.DELIVERED
		job.receiver_name = self.received_by or self.consignee_name
		job.accessories_returned = 1
		job.otp_verified = 1
		job.flags.ignore_permissions = True
		job.save(ignore_permissions=True)

	def _raise_damage_report(self):
		"""A lost parcel is a stock loss the courier is responsible for."""
		if not self.get("items"):
			return
		if frappe.db.exists(
			"Stock Damage Report", {"reference_type": "Stock Request", "reference_name": self.name}
		):
			return

		profile = get_branch_profile(self.branch)
		if not profile:
			return

		report = frappe.new_doc("Stock Damage Report")
		report.branch = self.branch
		report.damage_type = "Transit Damage"
		report.discovered_during = "Inter-branch Transfer Receipt"
		report.source_warehouse = profile.default_warehouse
		report.responsibility = "Courier / Transporter"
		report.is_recoverable = 1
		report.recovery_mode = "Courier Claim"
		# The claim is settled against the courier separately; the recovery amount
		# is left for the manager, since it cannot exceed the stock value here.
		report.remarks = _("Courier dispatch {0} (AWB {1}) reported lost. Declared value {2}.").format(
			self.name, self.awb_no or "-",
			frappe.format_value(flt(self.declared_value), {"fieldtype": "Currency"}),
		)

		for row in self.get("items") or []:
			if not row.item_code:
				continue
			report.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": flt(row.qty) or 1,
					"warehouse": profile.default_warehouse,
					"serial_no": row.serial_no,
					"damage_description": _("Lost in transit"),
				},
			)

		if not report.get("items"):
			return

		report.flags.ignore_permissions = True
		report.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------
def auto_draft_for_job_card(doc, method=None):
	"""A job card marked for courier delivery gets a draft dispatch (scope 7.4)."""
	from a3_retail.a3_retail_service.doctype.service_job_card import state as st

	if doc.delivery_mode != "Courier" or doc.status != st.READY_FOR_DELIVERY:
		return
	if doc.courier_dispatch:
		return
	if frappe.db.exists(
		"Courier Dispatch", {"reference_type": "Service Job Card", "reference_name": doc.name}
	):
		return

	partner = frappe.db.get_value("Courier Partner", {"is_active": 1}, "name")
	if not partner:
		return

	dispatch = frappe.new_doc("Courier Dispatch")
	dispatch.dispatch_type = "Service Device Return"
	dispatch.branch = doc.branch
	dispatch.reference_type = "Service Job Card"
	dispatch.reference_name = doc.name
	dispatch.courier_partner = partner
	dispatch.consignee_type = "Customer"
	dispatch.consignee = doc.customer
	dispatch.pincode = "000000"
	dispatch.dispatch_date = now_datetime()
	dispatch.declared_value = flt(doc.grand_total)
	dispatch.append(
		"items",
		{"description": f"{doc.device_model} ({doc.imei_1})", "qty": 1,
		 "serial_no": doc.imei_1, "value": flt(doc.grand_total)},
	)
	dispatch.flags.ignore_permissions = True
	dispatch.insert(ignore_permissions=True)

	frappe.db.set_value("Service Job Card", doc.name, "courier_dispatch", dispatch.name,
	                    update_modified=False)


def scan_delayed_dispatches():
	"""Hourly — flag dispatches past their promise and escalate after two days."""
	rows = frappe.get_all(
		"Courier Dispatch",
		filters={"docstatus": 1, "status": ["in", list(OPEN_STATUSES)],
		         "expected_delivery_date": ["<", nowdate()]},
		fields=["name", "branch", "expected_delivery_date", "awb_no", "courier_partner"],
	)

	escalated = []
	for row in rows:
		delay = date_diff(nowdate(), getdate(row.expected_delivery_date))
		frappe.db.set_value("Courier Dispatch", row.name, "delay_days", delay, update_modified=False)
		if delay >= 2:
			escalated.append(row.name)
			_notify_branch(row, delay)

	commit_if_not_testing()
	return {"delayed": len(rows), "escalated": len(escalated)}


def _branch_pincode(branch: str | None) -> str | None:
	if not branch:
		return None
	address = frappe.db.get_value("Branch Profile", {"branch": branch}, "address")
	return frappe.db.get_value("Address", address, "pincode") if address else None


def _notify_branch(row, delay: int):
	manager = frappe.db.get_value("Branch Profile", {"branch": row.branch}, "branch_manager")
	user = frappe.db.get_value("Employee", manager, "user_id") if manager else None
	if not user:
		return

	if frappe.db.exists("ToDo", {"reference_type": "Courier Dispatch", "reference_name": row.name,
	                             "status": "Open"}):
		return

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"reference_type": "Courier Dispatch",
			"reference_name": row.name,
			"priority": "High",
			"description": _("Courier {0} (AWB {1}) is {2} days late.").format(
				row.name, row.awb_no or "-", delay
			),
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def reconcile_monthly_bill(courier_partner: str, from_date: str, to_date: str) -> dict:
	"""Match a month of dispatches against the courier's bill (scope 7.4)."""
	from a3_retail.api import require_role

	require_role("Accounts Manager", "Branch Manager")

	rows = frappe.get_all(
		"Courier Dispatch",
		filters={
			"docstatus": 1,
			"courier_partner": courier_partner,
			"dispatch_date": ["between", [from_date, to_date]],
			"purchase_invoice": ["in", ["", None]],
		},
		fields=["name", "awb_no", "total_cost", "branch"],
	)
	if not rows:
		return {"matched": 0, "purchase_invoice": None}

	supplier = frappe.db.get_value("Courier Partner", courier_partner, "supplier")
	if not supplier:
		frappe.throw(_("Courier Partner {0} has no supplier to bill against.").format(courier_partner))

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	expense = f"Courier & Freight Outward - {abbr}"

	invoice = frappe.new_doc("Purchase Invoice")
	invoice.supplier = supplier
	invoice.company = company
	invoice.posting_date = getdate(to_date)
	invoice.append(
		"items",
		{
			"item_name": _("Courier charges {0} to {1}").format(from_date, to_date),
			"description": _("{0} dispatches").format(len(rows)),
			"qty": 1,
			"rate": sum(flt(r.total_cost) for r in rows),
			"expense_account": expense if frappe.db.exists("Account", expense) else None,
		},
	)
	invoice.flags.ignore_permissions = True
	invoice.insert(ignore_permissions=True)

	for row in rows:
		frappe.db.set_value("Courier Dispatch", row.name, "purchase_invoice", invoice.name,
		                    update_modified=False)

	return {"matched": len(rows), "purchase_invoice": invoice.name,
	        "amount": sum(flt(r.total_cost) for r in rows)}
