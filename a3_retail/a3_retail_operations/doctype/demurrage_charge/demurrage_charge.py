# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Demurrage / detention charges (scope 6.4).

Two flavours: charges a transporter or warehouse levies on us, and storage we
charge a customer whose repaired device sits uncollected past the free period.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from a3_retail.utils import commit_if_not_testing, money

GST_RATE = 18.0
CUSTOMER_STORAGE = "Customer Device Storage"


class DemurrageCharge(Document):
	def validate(self):
		self.compute_period()
		self.compute_amount()

	def compute_period(self):
		if not self.arrival_date:
			return

		self.free_until_date = add_days(getdate(self.arrival_date), cint(self.free_days))
		clearance = getdate(self.actual_clearance_date or nowdate())
		self.chargeable_days = max(date_diff(clearance, getdate(self.free_until_date)), 0)

	def compute_amount(self):
		self.charge_amount = money(cint(self.chargeable_days) * flt(self.rate_per_day))
		self.tax_amount = money(flt(self.charge_amount) * GST_RATE / 100) if self.gst_applicable else 0
		self.total_amount = money(flt(self.charge_amount) + flt(self.tax_amount))


def raise_storage_charges():
	"""Daily — charge for devices left uncollected past the free period (scope 6.4).

	Also drives the reminder ladder at D+7 / D+15 / D+30 / D+60, with a final
	unclaimed-goods notice at D+90.
	"""
	from a3_retail.a3_retail_service.doctype.service_job_card import state as st
	from a3_retail.communication.engine import notify

	free_days = cint(frappe.db.get_single_value("A3 Retail Settings", "free_storage_days")) or 15
	rate = flt(frappe.db.get_single_value("A3 Retail Settings", "storage_charge_per_day")) or 20

	rows = frappe.get_all(
		"Service Job Card",
		filters={"docstatus": 1, "status": st.READY_FOR_DELIVERY, "ready_on": ["is", "set"]},
		fields=["name", "customer", "customer_mobile", "customer_name", "branch", "ready_on",
		        "device_model"],
	)

	created = 0
	for row in rows:
		waiting = date_diff(nowdate(), getdate(row.ready_on))
		if waiting <= free_days:
			continue

		created += _ensure_charge(row, free_days, rate)
		_send_reminder(row, waiting, notify)

	commit_if_not_testing()
	return created


def _ensure_charge(row, free_days: int, rate: float) -> int:
	"""One open charge per job card, refreshed as the days tick up."""
	existing = frappe.db.get_value(
		"Demurrage Charge",
		{"reference_type": "Service Job Card", "reference_name": row.name,
		 "status": ["in", ["Draft", "Approved"]]},
		"name",
	)

	if existing:
		doc = frappe.get_doc("Demurrage Charge", existing)
		doc.actual_clearance_date = None
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		return 0

	doc = frappe.new_doc("Demurrage Charge")
	doc.charge_type = CUSTOMER_STORAGE
	doc.branch = row.branch
	doc.party_type = "Customer"
	doc.party = row.customer
	doc.reference_type = "Service Job Card"
	doc.reference_name = row.name
	doc.arrival_date = getdate(row.ready_on)
	doc.free_days = free_days
	doc.rate_per_day = rate
	doc.payable_or_recoverable = "Recoverable from Party"
	doc.responsibility = "Company"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return 1


REMINDER_DAYS = (7, 15, 30, 60, 90)


def _send_reminder(row, waiting_days: int, notify):
	if waiting_days not in REMINDER_DAYS:
		return

	template = "unclaimed_goods_notice" if waiting_days >= 90 else "pickup_reminder"
	notify(
		template,
		to_number=row.customer_mobile,
		params={"1": row.customer_name, "2": row.device_model, "3": str(row.ready_on),
		        "4": str(waiting_days)},
		stream="Service",
	)


def generate_dead_stock_todos():
	"""Weekly — a ToDo per branch listing SKUs that have not moved (scope 6.5)."""
	settings = frappe.get_cached_doc("A3 Retail Settings")
	rules = {row.item_group: cint(row.dead_stock_days) for row in settings.get("dead_stock_rules") or []}
	default_days = 90

	rows = frappe.db.sql(
		"""
		select w.custom_branch as branch, b.item_code, i.item_group, b.warehouse,
		       b.actual_qty, b.stock_value,
		       (select max(sle.posting_date) from `tabStock Ledger Entry` sle
		        where sle.item_code = b.item_code and sle.warehouse = b.warehouse
		          and sle.actual_qty < 0 and sle.is_cancelled = 0) as last_outward
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where b.actual_qty > 0 and ifnull(w.custom_branch, '') != '' and w.disabled = 0
		""",
		as_dict=True,
	)

	by_branch: dict[str, list] = {}
	for row in rows:
		threshold = rules.get(row.item_group, default_days)
		idle = date_diff(nowdate(), getdate(row.last_outward)) if row.last_outward else threshold + 1
		if idle >= threshold:
			by_branch.setdefault(row.branch, []).append((row.item_code, row.actual_qty, idle))

	created = 0
	for branch, items in by_branch.items():
		manager = frappe.db.get_value("Branch Profile", {"branch": branch}, "branch_manager")
		user = frappe.db.get_value("Employee", manager, "user_id") if manager else None
		if not user:
			continue

		lines = "".join(
			f"<li>{code} — {qty:g} units, idle {idle} days</li>" for code, qty, idle in items[:25]
		)
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"description": _("Dead stock at {0}: {1} SKUs<ul>{2}</ul>").format(
					branch, len(items), lines
				),
				"priority": "Medium",
			}
		).insert(ignore_permissions=True)
		created += 1

	commit_if_not_testing()
	return created


@frappe.whitelist()
def dead_stock(branch: str | None = None, days: int = 90) -> list[dict]:
	"""Dead-stock rows for the explorer footer and the report (scope 6.5)."""
	from a3_retail.api import require_permission

	require_permission("Item", "read")

	conditions = "and w.custom_branch = %(branch)s" if branch else ""
	return frappe.db.sql(
		f"""
		select w.custom_branch as branch, b.item_code, b.warehouse, b.actual_qty, b.stock_value,
		       (select max(sle.posting_date) from `tabStock Ledger Entry` sle
		        where sle.item_code = b.item_code and sle.warehouse = b.warehouse
		          and sle.actual_qty < 0 and sle.is_cancelled = 0) as last_sold
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.actual_qty > 0 and w.disabled = 0 {conditions}
		having last_sold is null or last_sold < date_sub(curdate(), interval %(days)s day)
		order by b.stock_value desc
		""",
		{"branch": branch, "days": cint(days)},
		as_dict=True,
	)
