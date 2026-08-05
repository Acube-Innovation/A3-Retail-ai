# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Number Cards, Dashboard Charts and role workspaces (scope 12.2 – 12.4).

All three are native Frappe doctypes, so this module only describes them and
upserts the documents; `hooks.fixtures` exports them by module. Cards and charts
carry no branch filter — Frappe applies the user's Branch permission to the
underlying query, so a branch manager sees their own numbers in the same card.
"""

import json

import frappe

MODULE = "A3 Retail Dashboard"

# label, doctype, function, aggregate field, filters, colour
NUMBER_CARDS = [
	("Job Cards Received Today", "Service Job Card", "Count", None,
	 [["Service Job Card", "received_on", "Timespan", "today", False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#0F62FE"),
	("Work In Progress", "Service Job Card", "Count", None,
	 [["Service Job Card", "status", "in", ["Under Diagnosis", "In Progress", "Awaiting Parts"], False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#0F62FE"),
	("Awaiting Parts", "Service Job Card", "Count", None,
	 [["Service Job Card", "status", "=", "Awaiting Parts", False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#f59e0b"),
	("Ready for Delivery", "Service Job Card", "Count", None,
	 [["Service Job Card", "status", "=", "Ready for Delivery", False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#16a34a"),
	("Delayed Job Cards", "Service Job Card", "Count", None,
	 [["Service Job Card", "is_delayed", "=", 1, False],
	  ["Service Job Card", "status", "not in", ["Delivered", "Closed"], False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#dc2626"),
	("Uncollected Over 7 Days", "Service Job Card", "Count", None,
	 [["Service Job Card", "status", "=", "Ready for Delivery", False],
	  ["Service Job Card", "ready_on", "Timespan", "last month", False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#dc2626"),
	("Today's Sales", "Sales Invoice", "Sum", "base_grand_total",
	 [["Sales Invoice", "posting_date", "Timespan", "today", False],
	  ["Sales Invoice", "docstatus", "=", 1, False],
	  ["Sales Invoice", "is_return", "=", 0, False]], "#0F62FE"),
	("Today's Service Revenue", "Service Job Card", "Sum", "grand_total",
	 [["Service Job Card", "delivered_on", "Timespan", "today", False],
	  ["Service Job Card", "docstatus", "=", 1, False]], "#0F62FE"),
	("Month to Date Sales", "Sales Invoice", "Sum", "base_grand_total",
	 [["Sales Invoice", "posting_date", "Timespan", "this month", False],
	  ["Sales Invoice", "docstatus", "=", 1, False],
	  ["Sales Invoice", "is_return", "=", 0, False]], "#0F62FE"),
	("Footfall Today", "Branch Visit Log", "Count", None,
	 [["Branch Visit Log", "visit_datetime", "Timespan", "today", False]], "#0F62FE"),
	("Converted Visits Today", "Branch Visit Log", "Count", None,
	 [["Branch Visit Log", "visit_datetime", "Timespan", "today", False],
	  ["Branch Visit Log", "outcome", "like", "Converted%", False]], "#16a34a"),
	("Open Tickets", "Issue", "Count", None,
	 [["Issue", "status", "not in", ["Closed", "Resolved"], False]], "#f59e0b"),
	("SLA Breached Tickets", "Issue", "Count", None,
	 [["Issue", "agreement_status", "=", "Failed", False]], "#dc2626"),
	("Stock Value", "Bin", "Sum", "stock_value", [], "#0F62FE"),
	("Dead Stock Items", "Demurrage Charge", "Count", None,
	 [["Demurrage Charge", "status", "=", "Unpaid", False]], "#f59e0b"),
	("EMI Pending Approval", "EMI Application", "Count", None,
	 [["EMI Application", "status", "=", "Submitted to Financier", False],
	  ["EMI Application", "docstatus", "=", 1, False]], "#f59e0b"),
	("Financier Receivable", "EMI Application", "Sum", "loan_amount",
	 [["EMI Application", "status", "=", "Disbursed", False],
	  ["EMI Application", "docstatus", "=", 1, False]], "#0F62FE"),
	("Warranty Expiring in 30 Days", "Warranty Registration", "Count", None,
	 [["Warranty Registration", "ew_expiry_date", "Timespan", "next month", False],
	  ["Warranty Registration", "status", "=", "In Extended Warranty", False]], "#f59e0b"),
	("Courier In Transit", "Courier Dispatch", "Count", None,
	 [["Courier Dispatch", "status", "=", "In Transit", False],
	  ["Courier Dispatch", "docstatus", "=", 1, False]], "#0F62FE"),
	("Delayed Deliveries", "Courier Dispatch", "Count", None,
	 [["Courier Dispatch", "delay_days", ">", 0, False],
	  ["Courier Dispatch", "status", "not in", ["Delivered"], False],
	  ["Courier Dispatch", "docstatus", "=", 1, False]], "#dc2626"),
]

# name, chart type, doctype, chart_type(Count/Sum/Group By), group by field, value field,
# based_on date field, timespan, timeseries
DASHBOARD_CHARTS = [
	("Job Cards by Status", "Donut", "Service Job Card", "Group By", "status", None, None, None, 0),
	("Daily Job Card Trend", "Line", "Service Job Card", "Count", None, None, "received_on",
	 "Last Month", 1),
	("TAT Compliance Trend", "Line", "Service Job Card", "Count", None, None, "delivered_on",
	 "Last Quarter", 1),
	("Service Revenue Trend", "Bar", "Service Job Card", "Sum", None, "grand_total", "delivered_on",
	 "Last Quarter", 1),
	("Branch-wise Revenue", "Bar", "Sales Invoice", "Group By", "branch", "base_grand_total",
	 None, None, 0),
	("Repair Category Mix", "Pie", "Service Job Card", "Group By", "repair_category", None,
	 None, None, 0),
	("Top Failing Device Models", "Bar", "Service Job Card", "Group By", "device_model", None,
	 None, None, 0),
	("Technician Productivity", "Bar", "Service Job Card", "Group By", "assigned_technician",
	 None, None, None, 0),
	("Footfall Trend", "Line", "Branch Visit Log", "Count", None, None, "visit_datetime",
	 "Last Month", 1),
	("Visit Outcomes", "Donut", "Branch Visit Log", "Group By", "outcome", None, None, None, 0),
	("EMI Funnel", "Bar", "EMI Application", "Group By", "status", None, None, None, 0),
	("Warranty Registrations Trend", "Line", "Warranty Registration", "Count", None, None,
	 "purchase_date", "Last Quarter", 1),
	("Complaint Categories", "Pie", "Issue", "Group By", "a3_complaint_category", None, None,
	 None, 0),
	("Stock Requests by Status", "Donut", "Stock Request", "Group By", "status", None, None,
	 None, 0),
	("Courier Spend by Partner", "Bar", "Courier Dispatch", "Group By", "courier_partner",
	 "total_cost", None, None, 0),
]

# label, icon, roles, shortcuts [(type, link_to, label)], cards, charts
WORKSPACES = [
	("A3 Retail Home", "getting-started", [],
	 [("Page", "a3-reception-desk", "Reception Desk"),
	  ("Page", "a3-control-tower", "Control Tower"),
	  ("Page", "a3-stock-explorer", "Stock Explorer"),
	  ("DocType", "Service Job Card", "Job Cards"),
	  ("DocType", "Sales Invoice", "Sales Invoices")],
	 ["Job Cards Received Today", "Work In Progress", "Ready for Delivery", "Today's Sales"],
	 ["Job Cards by Status"]),

	("A3 Service", "tool", ["Service Manager", "Technician"],
	 [("Page", "a3-technician-workbench", "Technician Workbench"),
	  ("DocType", "Service Job Card", "Job Cards"),
	  ("DocType", "Service Estimate", "Estimates"),
	  ("DocType", "Service Issue Type", "Issue Types"),
	  ("DocType", "Service TAT Policy", "TAT Policies"),
	  ("DocType", "Technician Profile", "Technicians")],
	 ["Work In Progress", "Awaiting Parts", "Ready for Delivery", "Delayed Job Cards"],
	 ["Job Cards by Status", "Daily Job Card Trend", "Repair Category Mix"]),

	("A3 Sales", "sell", ["Sales Executive", "Branch Manager"],
	 [("DocType", "Sales Invoice", "Sales Invoice"),
	  ("DocType", "POS Invoice", "POS Invoice"),
	  ("DocType", "Quotation", "Quotation"),
	  ("DocType", "Seasonal Offer Campaign", "Offers"),
	  ("DocType", "Device Exchange", "Exchange"),
	  ("DocType", "EMI Application", "EMI")],
	 ["Today's Sales", "Month to Date Sales", "Footfall Today", "Converted Visits Today"],
	 ["Branch-wise Revenue", "Visit Outcomes"]),

	("A3 Branch Manager", "organization", ["Branch Manager"],
	 [("Page", "a3-control-tower", "Control Tower"),
	  ("DocType", "Branch Profile", "Branch Profile"),
	  ("DocType", "Stock Request", "Stock Requests"),
	  ("DocType", "Branch Visit Log", "Footfall"),
	  ("DocType", "Incentive Calculation Run", "Incentives")],
	 ["Delayed Job Cards", "Today's Sales", "Footfall Today", "Stock Value"],
	 ["Daily Job Card Trend", "Footfall Trend"]),

	("A3 Inventory", "stock", ["Store Keeper"],
	 [("Page", "a3-stock-explorer", "Stock Explorer"),
	  ("DocType", "Stock Request", "Stock Requests"),
	  ("DocType", "Purchase Receipt", "Purchase Receipt"),
	  ("DocType", "Stock Damage Report", "Damage Reports"),
	  ("DocType", "Demurrage Charge", "Demurrage")],
	 ["Stock Value", "Dead Stock Items", "Awaiting Parts"],
	 ["Stock Requests by Status"]),

	("A3 Finance", "accounting", ["Accounts Manager"],
	 [("DocType", "Sales Invoice", "Sales Invoice"),
	  ("DocType", "Purchase Invoice", "Purchase Invoice"),
	  ("DocType", "Payment Entry", "Payment Entry"),
	  ("DocType", "Financier Settlement", "Financier Settlement"),
	  ("DocType", "EMI Application", "EMI Applications")],
	 ["Month to Date Sales", "Financier Receivable", "EMI Pending Approval"],
	 ["Branch-wise Revenue", "EMI Funnel"]),

	("A3 HR", "hr", ["HR Manager"],
	 [("DocType", "Attendance", "Attendance"),
	  ("DocType", "Payroll Entry", "Payroll Entry"),
	  ("DocType", "Employee Incentive Scheme", "Incentive Schemes"),
	  ("DocType", "Incentive Calculation Run", "Incentive Runs"),
	  ("DocType", "Asset", "Assets")],
	 [], []),

	("A3 Customer Care", "support", ["Helpdesk Agent", "Telecaller"],
	 [("DocType", "Issue", "Tickets"),
	  ("DocType", "Customer Feedback", "Feedback"),
	  ("DocType", "Call Task", "Call Tasks"),
	  ("DocType", "Telecalling Campaign", "Campaigns")],
	 ["Open Tickets", "SLA Breached Tickets"],
	 ["Complaint Categories"]),

	("A3 Management", "dashboard", ["A3 Retail Admin"],
	 [("Page", "a3-control-tower", "Control Tower"),
	  ("DocType", "Branch Profile", "Branches"),
	  ("DocType", "Employee Incentive Scheme", "Incentive Schemes")],
	 ["Today's Sales", "Month to Date Sales", "Delayed Job Cards", "Open Tickets"],
	 ["Branch-wise Revenue", "Daily Job Card Trend", "Technician Productivity"]),
]


def run():
	ensure_number_cards()
	ensure_dashboard_charts()
	ensure_workspaces()


# --------------------------------------------------------------- number cards
def ensure_number_cards() -> int:
	created = 0
	for label, doctype, function, aggregate_field, filters, colour in NUMBER_CARDS:
		if not frappe.db.exists("DocType", doctype):
			continue

		values = {
			"label": label,
			"document_type": doctype,
			"type": "Document Type",
			"function": function,
			"aggregate_function_based_on": aggregate_field,
			"filters_json": json.dumps(_valid_filters(doctype, filters)),
			"is_public": 1,
			"show_percentage_stats": 1,
			"stats_time_interval": "Daily",
			"color": colour,
			"module": MODULE,
		}

		if frappe.db.exists("Number Card", label):
			frappe.db.set_value("Number Card", label, values, update_modified=False)
			continue

		doc = frappe.new_doc("Number Card")
		doc.name = label
		doc.update(values)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
	return created


def _valid_filters(doctype: str, filters: list) -> list:
	"""Drop filters whose field does not exist on this site."""
	meta = frappe.get_meta(doctype)
	return [
		row for row in filters
		if row[1] in ("docstatus", "name", "owner") or meta.has_field(row[1])
	]


# ------------------------------------------------------------ dashboard charts
def ensure_dashboard_charts() -> int:
	created = 0
	for (name, chart_style, doctype, chart_type, group_by, value_field, based_on, timespan,
	     timeseries) in DASHBOARD_CHARTS:
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if group_by and not meta.has_field(group_by):
			continue
		if based_on and not meta.has_field(based_on):
			continue

		values = {
			"chart_name": name,
			"chart_type": chart_type,
			"document_type": doctype,
			"type": chart_style,
			"group_by_type": "Count" if chart_type == "Group By" and not value_field else
				("Sum" if value_field else "Count"),
			"group_by_based_on": group_by,
			"aggregate_function_based_on": value_field,
			"based_on": based_on,
			"time_interval": "Daily",
			"timespan": timespan or "Last Month",
			"timeseries": timeseries,
			"is_public": 1,
			"filters_json": json.dumps(
				[[doctype, "docstatus", "=", 1, False]] if meta.is_submittable else []
			),
			"module": MODULE,
		}

		if frappe.db.exists("Dashboard Chart", name):
			frappe.db.set_value("Dashboard Chart", name, values, update_modified=False)
			continue

		doc = frappe.new_doc("Dashboard Chart")
		doc.name = name
		doc.update(values)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
	return created


# ----------------------------------------------------------------- workspaces
def ensure_workspaces() -> int:
	created = 0
	for label, icon, roles, shortcuts, cards, charts in WORKSPACES:
		shortcuts = [row for row in shortcuts if _target_exists(row[0], row[1])]
		cards = [card for card in cards if frappe.db.exists("Number Card", card)]
		charts = [chart for chart in charts if frappe.db.exists("Dashboard Chart", chart)]

		content = _workspace_content(label, shortcuts, cards, charts)

		if frappe.db.exists("Workspace", label):
			doc = frappe.get_doc("Workspace", label)
		else:
			doc = frappe.new_doc("Workspace")
			doc.name = label
			created += 1

		doc.title = label
		doc.label = label
		doc.module = MODULE
		doc.icon = icon
		doc.public = 1
		doc.is_hidden = 0
		doc.content = content
		doc.roles = []
		for role in roles:
			if frappe.db.exists("Role", role):
				doc.append("roles", {"role": role})

		doc.shortcuts = []
		for link_type, link_to, shortcut_label in shortcuts:
			doc.append("shortcuts", {"type": link_type, "link_to": link_to,
			                         "label": shortcut_label})

		doc.number_cards = []
		for card in cards:
			doc.append("number_cards", {"number_card_name": card, "label": card})

		doc.charts = []
		for chart in charts:
			doc.append("charts", {"chart_name": chart, "label": chart})

		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
	return created


def _target_exists(link_type: str, link_to: str) -> bool:
	doctype = "Page" if link_type == "Page" else "DocType"
	return bool(frappe.db.exists(doctype, link_to))


def _workspace_content(label: str, shortcuts: list, cards: list, charts: list) -> str:
	blocks = [{"id": frappe.generate_hash(length=10), "type": "header",
	           "data": {"text": f"<span class='h4'>{label}</span>", "col": 12}}]

	if shortcuts:
		blocks.append({"id": frappe.generate_hash(length=10), "type": "header",
		               "data": {"text": "<span class='h4'>Shortcuts</span>", "col": 12}})
		for _type, _link, shortcut_label in shortcuts:
			blocks.append({"id": frappe.generate_hash(length=10), "type": "shortcut",
			               "data": {"shortcut_name": shortcut_label, "col": 3}})

	if cards:
		blocks.append({"id": frappe.generate_hash(length=10), "type": "header",
		               "data": {"text": "<span class='h4'>Your Numbers</span>", "col": 12}})
		for card in cards:
			blocks.append({"id": frappe.generate_hash(length=10), "type": "number_card",
			               "data": {"number_card_name": card, "col": 3}})

	for chart in charts:
		blocks.append({"id": frappe.generate_hash(length=10), "type": "chart",
		               "data": {"chart_name": chart, "col": 12}})

	return json.dumps(blocks)
