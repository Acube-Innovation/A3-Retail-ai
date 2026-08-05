# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Device Exchange / buyback (scope 2.4, ADR-10).

On submit the old handset becomes real stock: a used Item under the Used Devices
group, a Serial No carrying the original IMEI, and a Purchase Receipt against the
"Walk-in Public (Unregistered)" supplier into the branch's Used Devices
warehouse.

No ITC is claimed — the device is bought from an unregistered individual — and
the created item is flagged `a3_is_margin_scheme`, so when it is resold GST falls
on the margin alone under Rule 32(5).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from a3_retail.utils import money
from a3_retail.utils.branch import A3BranchMixin, get_branch_profile
from a3_retail.utils.imei import enforce_imei, normalize_imei
from a3_retail.utils.naming import set_branch_code

# score -> grade. The score is what survives the deductions.
GRADE_BANDS = (
	(85, "A - Like New"),
	(65, "B - Good"),
	(40, "C - Average"),
	(0, "D - Poor / Spares"),
)

USED_ITEM_GROUP = "Used Devices"
WALKIN_SUPPLIER = "Walk-in Public (Unregistered)"
USED_DEVICE_HSN = "85171300"


class DeviceExchange(A3BranchMixin, Document):
	def before_naming(self):
		set_branch_code(self)

	def before_validate(self):
		self.set_branch_defaults()
		if not self.exchange_date:
			self.exchange_date = getdate(nowdate())
		if not self.company:
			profile = get_branch_profile(self.branch)
			if profile:
				self.company = profile.company

	def validate(self):
		self.validate_imei()
		self.grade_device()
		self.pull_exchange_bonus()
		self.compute_value()
		if self.docstatus == 0 and self.status == "Draft" and flt(self.final_exchange_value):
			self.status = "Valued"

	def before_submit(self):
		self.validate_gating()
		self.status = "Accepted"

	def on_submit(self):
		self.create_used_item()
		self.create_purchase_receipt()

	def on_cancel(self):
		"""Reversing an exchange must also take the handset back out of stock.

		Without this the Purchase Receipt stays submitted and the branch keeps
		phantom used-device stock for a deal that was undone.
		"""
		receipt_name = self.purchase_receipt
		if receipt_name and frappe.db.exists("Purchase Receipt", receipt_name):
			# Drop the link first: ERPNext refuses to cancel a document that is
			# still referenced by another one.
			self.db_set("purchase_receipt", None, update_modified=False)
			receipt = frappe.get_doc("Purchase Receipt", receipt_name)
			if receipt.docstatus == 1:
				receipt.flags.ignore_permissions = True
				receipt.cancel()

		self.status = "Cancelled"

	# ------------------------------------------------------------------ checks
	def validate_imei(self):
		self.old_imei = normalize_imei(self.old_imei)
		if not self.old_imei:
			frappe.throw(_("The old device's IMEI is required."))
		self.old_imei = enforce_imei(self.old_imei, "IMEI", override=bool(self.imei_override))

		clash = frappe.db.exists(
			"Device Exchange",
			{"old_imei": self.old_imei, "docstatus": 1, "name": ["!=", self.name or ""]},
		)
		if clash:
			frappe.throw(_("IMEI {0} was already taken in on {1}.").format(self.old_imei, clash))

	def validate_gating(self):
		"""Nothing is bought without ID proof and a blacklist check (scope 2.4)."""
		if not self.imei_check_done:
			frappe.throw(_("Complete the IMEI blacklist check before accepting the device."))
		if not self.id_proof_type or not self.id_proof_number_last4:
			frappe.throw(_("Capture the seller's ID proof."))
		if not self.declaration_signed:
			frappe.throw(_("The customer declaration must be signed."))
		if flt(self.final_exchange_value) <= 0:
			frappe.throw(_("The exchange value must be greater than zero."))

	# ----------------------------------------------------------------- grading
	def grade_device(self):
		"""Deductions come off a 100-point score; the score picks the grade."""
		base = flt(self.base_value)
		total_percent = 0.0
		total_amount = 0.0

		for row in self.get("grading_parameters") or []:
			percent = flt(row.deduction_percent)
			row.deduction_amount = money(base * percent / 100.0)
			total_percent += percent
			total_amount += flt(row.deduction_amount)

		# Missing box, charger or bill each cost the customer a little.
		for field, percent in (("has_box", 2.0), ("has_charger", 3.0), ("has_bill", 2.0)):
			if not self.get(field):
				total_percent += percent
				total_amount += money(base * percent / 100.0)

		self.deductions = money(min(total_amount, base))

		score = max(0.0, 100.0 - total_percent)
		self.grade = next(grade for threshold, grade in GRADE_BANDS if score >= threshold)

	def pull_exchange_bonus(self):
		from a3_retail.a3_retail_sales.doctype.seasonal_offer_campaign.seasonal_offer_campaign import (
			active_exchange_bonus,
		)

		if self.docstatus == 0:
			self.exchange_bonus = money(active_exchange_bonus(self.branch))

	def compute_value(self):
		value = flt(self.base_value) - flt(self.deductions) + flt(self.exchange_bonus)
		self.final_exchange_value = money(max(value, 0))

	# ------------------------------------------------------------ stock intake
	def derive_used_item_code(self) -> str:
		"""One used-stock item per model + grade, reused across exchanges.

		Named `derive_*` because `used_item_code` is a field on this doctype —
		a method of that name would be shadowed by the (empty) field value.
		"""
		model = (self.old_model or "device").replace(" ", "-").upper()
		grade = (self.grade or "C")[0]
		return f"USED-{model}-{grade}"[:140]

	def create_used_item(self):
		item_code = self.derive_used_item_code()
		if not frappe.db.exists("Item", item_code):
			_ensure_used_item_group()

			item = frappe.new_doc("Item")
			item.item_code = item_code
			item.item_name = f"{self.old_model} (Used, Grade {(self.grade or '')[0]})"
			item.item_group = USED_ITEM_GROUP
			item.stock_uom = "Nos"
			item.is_stock_item = 1
			item.has_serial_no = 1
			item.brand = self.old_brand
			item.a3_is_device = 1
			item.a3_is_margin_scheme = 1
			item.a3_brand_warranty_months = 0
			# india_compliance requires an HSN on every item; a used handset is
			# still tariff item 8517 13 00.
			if item.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", USED_DEVICE_HSN):
				item.gst_hsn_code = USED_DEVICE_HSN
			item.description = _("Second-hand device acquired via exchange. GST on margin (Rule 32(5)).")
			item.flags.ignore_permissions = True
			item.flags.ignore_mandatory = True
			item.insert(ignore_permissions=True)

		self.db_set("used_item_code", item_code, update_modified=False)
		return item_code

	def create_purchase_receipt(self):
		"""Bring the handset into stock at the value we paid for it."""
		if self.purchase_receipt:
			return self.purchase_receipt

		profile = get_branch_profile(self.branch)
		warehouse = (profile.used_device_warehouse or profile.default_warehouse) if profile else None
		if not warehouse:
			frappe.throw(_("Branch {0} has no Used Devices warehouse.").format(self.branch))

		supplier = _ensure_walkin_supplier()

		receipt = frappe.new_doc("Purchase Receipt")
		receipt.supplier = supplier
		receipt.company = self.company
		receipt.posting_date = getdate(self.exchange_date)
		receipt.set_warehouse = warehouse
		if receipt.meta.has_field("branch"):
			receipt.branch = self.branch
		# Purchases from an unregistered individual carry no ITC (ADR-10).
		if receipt.meta.has_field("gst_category"):
			receipt.gst_category = "Unregistered"

		receipt.append(
			"items",
			{
				"item_code": self.derive_used_item_code(),
				"qty": 1,
				"rate": flt(self.final_exchange_value),
				"warehouse": warehouse,
				"serial_no": self.old_imei,
			},
		)

		receipt.flags.ignore_permissions = True
		receipt.insert(ignore_permissions=True)
		receipt.submit()

		self.db_set("purchase_receipt", receipt.name, update_modified=False)
		self._stamp_serial(warehouse)
		return receipt.name

	def _stamp_serial(self, warehouse: str):
		"""Mark the created serial as exchange stock and record what it cost us."""
		serial = self.old_imei
		if not frappe.db.exists("Serial No", serial):
			return

		frappe.db.set_value(
			"Serial No",
			serial,
			{
				"a3_imei_1": self.old_imei,
				"a3_is_exchanged_device": 1,
				"a3_purchase_cost": flt(self.final_exchange_value),
				"a3_warranty_state": "Out of Warranty",
			},
			update_modified=False,
		)
		self.db_set("used_serial_no", serial, update_modified=False)


def _ensure_used_item_group():
	if frappe.db.exists("Item Group", USED_ITEM_GROUP):
		return
	group = frappe.new_doc("Item Group")
	group.item_group_name = USED_ITEM_GROUP
	group.parent_item_group = "All Item Groups"
	group.is_group = 0
	group.flags.ignore_permissions = True
	group.insert(ignore_permissions=True)


def _ensure_walkin_supplier() -> str:
	configured = frappe.db.get_single_value("A3 Retail Settings", "walkin_public_supplier")
	if configured and frappe.db.exists("Supplier", configured):
		return configured

	if not frappe.db.exists("Supplier", WALKIN_SUPPLIER):
		supplier = frappe.new_doc("Supplier")
		supplier.supplier_name = WALKIN_SUPPLIER
		supplier.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		supplier.country = "India"
		supplier.a3_supplier_category = "Unregistered Local"
		if supplier.meta.has_field("gst_category"):
			supplier.gst_category = "Unregistered"
		supplier.flags.ignore_permissions = True
		supplier.flags.ignore_mandatory = True
		supplier.insert(ignore_permissions=True)

	return WALKIN_SUPPLIER


# ---------------------------------------------------------------------------
# POS integration
# ---------------------------------------------------------------------------
@frappe.whitelist()
def apply_to_invoice(exchange: str, sales_invoice: str) -> dict:
	"""Settle an exchange against a new sale via the Exchange Adjustment mode.

	The value is a payment line, not a discount: the customer is still invoiced
	the full price of the new device, and Exchange Clearing nets to zero once the
	Purchase Receipt has debited used stock against it.
	"""
	from a3_retail.api import require_permission

	doc = frappe.get_doc("Device Exchange", exchange)
	require_permission("Device Exchange", "write", doc)

	if doc.docstatus != 1:
		frappe.throw(_("Submit the exchange before applying it to an invoice."))
	if doc.new_sales_invoice:
		frappe.throw(_("Exchange {0} is already applied to {1}.").format(doc.name, doc.new_sales_invoice))

	invoice = frappe.get_doc("Sales Invoice", sales_invoice)
	require_permission("Sales Invoice", "write", invoice)

	if invoice.docstatus != 0:
		frappe.throw(_("The invoice must still be a draft to add an exchange payment."))

	invoice.is_pos = 1
	invoice.append(
		"payments",
		{"mode_of_payment": "Exchange Adjustment", "amount": flt(doc.final_exchange_value)},
	)
	invoice.flags.ignore_permissions = True
	invoice.save(ignore_permissions=True)

	doc.db_set("new_sales_invoice", invoice.name, update_modified=False)
	return {"exchange": doc.name, "sales_invoice": invoice.name,
	        "amount": flt(doc.final_exchange_value)}


@frappe.whitelist()
def grading_template() -> list[dict]:
	"""Default grading rows the counter fills in."""
	return [
		{"parameter": "Display Condition", "deduction_percent": 0},
		{"parameter": "Body Condition", "deduction_percent": 0},
		{"parameter": "Battery Health", "deduction_percent": 0},
		{"parameter": "Camera", "deduction_percent": 0},
		{"parameter": "Touch", "deduction_percent": 0},
		{"parameter": "Charging Port", "deduction_percent": 0},
		{"parameter": "Water Damage", "deduction_percent": 0},
		{"parameter": "Repair History", "deduction_percent": 0},
	]
