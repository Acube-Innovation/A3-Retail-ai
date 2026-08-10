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

# ---------------------------------------------------------------------------
# One workspace: A3 Retail Home
#
# The shop used to have nine — Home, Service, Sales, Branch Manager, Inventory,
# Finance, HR, Customer Care and Management — one per role. Nobody works in one
# role all day, and a person with two of them had to remember which page held
# which shortcut. So there is one page now, in sections.
#
# It is not a permissions hole. Frappe's own `desktop.is_item_allowed` drops a
# shortcut whose doctype or page the signed-in user cannot open, so a technician
# opens this page and sees the workshop, a cashier sees the till, and the branch
# manager sees both — off the same workspace.
# ---------------------------------------------------------------------------
WORKSPACE = "A3 Retail Home"
WORKSPACE_ICON = "getting-started"

# heading, [(type, link_to or url, label)]
SECTIONS = [
	("Every Day", [
		("Page", "a3-reception-desk", "Reception Desk"),
		("Page", "a3-technician-workbench", "Technician Workbench"),
		("Page", "a3-control-tower", "Control Tower"),
		("Page", "a3-stock-explorer", "Stock Explorer"),
	]),
	("The Counters", [
		("URL", "/retail/dashboard", "Branch App"),
		("URL", "/retail/sales", "Sales POS"),
		("URL", "/retail/service", "Service POS"),
		("URL", "/retail/bills", "Bills"),
		("URL", "/retail/emi", "EMI Management"),
		("URL", "/retail/stock", "Stock Control"),
		("URL", "/retail/reports", "Branch Reports"),
	]),
	("Sales", [
		("DocType", "Sales Invoice", "Sales Invoice"),
		("DocType", "POS Invoice", "POS Invoice"),
		("DocType", "Quotation", "Quotation"),
		("DocType", "Seasonal Offer Campaign", "Offers"),
		("DocType", "Device Exchange", "Exchange"),
	]),
	("Service", [
		("DocType", "Service Job Card", "Job Cards"),
		("DocType", "Service Estimate", "Estimates"),
		("DocType", "Service Issue Type", "Issue Types"),
		("DocType", "Service TAT Policy", "TAT Policies"),
		("DocType", "Technician Profile", "Technicians"),
	]),
	("Finance & EMI", [
		("DocType", "Payment Entry", "Payment Entry"),
		("DocType", "Purchase Invoice", "Purchase Invoice"),
		("DocType", "EMI Application", "EMI Applications"),
		("DocType", "EMI Scheme", "EMI Schemes"),
		("DocType", "Finance Partner", "Financiers"),
		("DocType", "Financier Settlement", "Financier Settlement"),
	]),
	("Stock", [
		("DocType", "Stock Request", "Stock Requests"),
		("DocType", "Purchase Receipt", "Purchase Receipt"),
		("DocType", "Stock Damage Report", "Damage Reports"),
		("DocType", "Demurrage Charge", "Demurrage"),
	]),
	("Branch", [
		("DocType", "Branch Profile", "Branch Profile"),
		("DocType", "Branch Visit Log", "Footfall"),
		("DocType", "Incentive Calculation Run", "Incentive Runs"),
	]),
	("Customer Care", [
		("DocType", "Issue", "Tickets"),
		("DocType", "Customer Feedback", "Feedback"),
		("DocType", "Call Task", "Call Tasks"),
		("DocType", "Telecalling Campaign", "Campaigns"),
	]),
	("People & Assets", [
		("DocType", "Attendance", "Attendance"),
		("DocType", "Payroll Entry", "Payroll Entry"),
		("DocType", "Employee Incentive Scheme", "Incentive Schemes"),
		("DocType", "Asset", "Assets"),
	]),
]

# Every card and chart the nine pages carried between them.
CARDS = [
	"Job Cards Received Today", "Work In Progress", "Awaiting Parts", "Ready for Delivery",
	"Delayed Job Cards", "Today's Sales", "Month to Date Sales", "Footfall Today",
	"Converted Visits Today", "EMI Pending Approval", "Financier Receivable", "Stock Value",
	"Dead Stock Items", "Open Tickets", "SLA Breached Tickets",
]

CHARTS = [
	"Job Cards by Status", "Daily Job Card Trend", "Branch-wise Revenue", "Repair Category Mix",
	"EMI Funnel", "Footfall Trend", "Visit Outcomes", "Stock Requests by Status",
	"Technician Productivity", "Complaint Categories",
]

# The pages this one replaced. Removed on migrate so an upgraded site does not
# keep nine half-empty entries in its sidebar.
RETIRED_WORKSPACES = (
	"A3 Service", "A3 Sales", "A3 Branch Manager", "A3 Inventory", "A3 Finance",
	"A3 HR", "A3 Customer Care", "A3 Management",
)


def run():
	ensure_number_cards()
	ensure_dashboard_charts()
	ensure_workspaces()
	retire_workspaces()


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
	"""Upsert the one workspace, with every section on it."""
	sections = [
		(heading, [row for row in rows if _target_exists(row[0], row[1])])
		for heading, rows in SECTIONS
	]
	sections = [(heading, rows) for heading, rows in sections if rows]

	cards = [card for card in CARDS if frappe.db.exists("Number Card", card)]
	charts = [chart for chart in CHARTS if frappe.db.exists("Dashboard Chart", chart)]

	created = 0
	if frappe.db.exists("Workspace", WORKSPACE):
		doc = frappe.get_doc("Workspace", WORKSPACE)
	else:
		doc = frappe.new_doc("Workspace")
		doc.name = WORKSPACE
		created = 1

	doc.title = WORKSPACE
	doc.label = WORKSPACE
	doc.module = MODULE
	doc.icon = WORKSPACE_ICON
	doc.public = 1
	doc.is_hidden = 0
	doc.sequence_id = 1
	doc.content = _workspace_content(sections, cards, charts)
	# No role list: this is the shop's front page, and Frappe already hides the
	# shortcuts a given person cannot use.
	doc.roles = []

	doc.shortcuts = []
	for _heading, rows in sections:
		for link_type, target, shortcut_label in rows:
			row = {"type": link_type, "label": shortcut_label}
			if link_type == "URL":
				row["url"] = target
			else:
				row["link_to"] = target
			doc.append("shortcuts", row)

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


def retire_workspaces() -> list[str]:
	"""Delete the eight pages A3 Retail Home replaced, and their private copies."""
	removed = []
	for label in RETIRED_WORKSPACES:
		for name in frappe.get_all(
			"Workspace",
			filters={"name": ("like", label), "module": MODULE},
			pluck="name",
		):
			frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True,
			                  delete_permanently=True)
			removed.append(name)

	if removed:
		frappe.clear_cache()
	return removed


def _target_exists(link_type: str, link_to: str) -> bool:
	if link_type == "URL":
		return True
	doctype = "Page" if link_type == "Page" else "DocType"
	return bool(frappe.db.exists(doctype, link_to))


def _workspace_content(sections: list, cards: list, charts: list) -> str:
	"""The page itself: a heading per section, then the numbers, then the charts."""
	blocks = [_block("header", {"text": f"<span class='h4'>{WORKSPACE}</span>", "col": 12})]

	for heading, rows in sections:
		blocks.append(_block("header", {"text": f"<span class='h4'>{heading}</span>", "col": 12}))
		for _type, _target, shortcut_label in rows:
			blocks.append(_block("shortcut", {"shortcut_name": shortcut_label, "col": 3}))

	if cards:
		blocks.append(_block("header", {"text": "<span class='h4'>Your Numbers</span>", "col": 12}))
		for card in cards:
			blocks.append(_block("number_card", {"number_card_name": card, "col": 3}))

	if charts:
		blocks.append(_block("header", {"text": "<span class='h4'>Trends</span>", "col": 12}))
		for chart in charts:
			blocks.append(_block("chart", {"chart_name": chart, "col": 12}))

	return json.dumps(blocks)


def _block(kind: str, data: dict) -> dict:
	return {"id": frappe.generate_hash(length=10), "type": kind, "data": data}
