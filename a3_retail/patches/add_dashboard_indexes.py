# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Composite indexes the Control Tower counters rely on (scope 12.1).

Every counter on the tower is a single COUNT(*) filtered by branch plus status or
a date. Without these the queries scan the whole table; with them each counter is
an index range scan.
"""

import frappe

INDEXES = [
	("Service Job Card", ["branch", "status", "docstatus"]),
	("Service Job Card", ["branch", "received_on"]),
	("Service Job Card", ["branch", "delivered_on"]),
	("Service Job Card", ["assigned_technician", "status"]),
	("Sales Invoice", ["branch", "posting_date", "docstatus"]),
	("Branch Visit Log", ["branch", "visit_datetime"]),
	("Courier Dispatch", ["branch", "status"]),
	("Call Task", ["assigned_to", "call_status"]),
]


def execute():
	for doctype, columns in INDEXES:
		if not frappe.db.table_exists(doctype):
			continue
		if not all(frappe.db.has_column(doctype, column) for column in columns):
			continue
		try:
			frappe.db.add_index(doctype, columns)
		except Exception:
			# Already present, or the column was dropped by a later patch.
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: index on {doctype}")
