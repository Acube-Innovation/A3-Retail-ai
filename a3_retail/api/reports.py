# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Reports for the branch app (`/retail/reports`).

The reports themselves are the 42 that already live in the ERP — real Query and
Script Reports with their own SQL, their own roles and their own filters. This
module does not restate any of them. It reads their definitions off disk, runs
them through `frappe.desk.query_report.run` (which enforces Frappe's own report
permissions), and shapes the answer for a page that has no desk around it.

Adding a report to the shop therefore means adding a report to the app, not
touching this file.
"""

import os
import re

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, nowdate

from a3_retail.api.staff import _me

FAVOURITE_KEY = "a3_favourite_reports"

# The categories the shop thinks in, and how a report finds its way into one.
# Module first, then a word in the report's own name — so a new report lands
# somewhere sensible without being listed here.
CATEGORIES = [
	("sales", "Sales", "Sales performance and invoice analysis", "tag",
	 ("A3 Retail Sales",), ("sales", "pos", "offer", "exchange", "imei")),
	("service", "Service", "Bookings, repairs and technician performance", "wrench",
	 ("A3 Retail Service",), ("service", "job card", "repair", "tat", "technician")),
	("customers", "Customers", "Customer activity and service history", "users",
	 (), ("customer", "footfall", "telecalling", "helpdesk")),
	("payments", "Payments", "Collections, settlements and outstanding money", "cash",
	 ("A3 Retail Finance",), ("payment", "settlement", "receivable", "emi", "collection")),
	("inventory", "Inventory", "Stock on hand, movement and ageing", "box",
	 (), ("stock", "damage", "availability", "transfer", "asset")),
	("warranty", "Warranty", "Cover sold, cover claimed and cover expiring", "shield",
	 ("A3 Retail Warranty",), ("warranty", "ew ")),
	("delivery", "Delivery", "Dispatch, courier and delivery performance", "truck",
	 (), ("delivery", "courier", "dispatch")),
	("financial", "Financial", "GST, margins and branch profitability", "chart",
	 (), ("gst", "rcm", "margin", "profitability", "incentive")),
	("people", "Branch & People", "Attendance, productivity and branch comparison", "grid",
	 (), ("attendance", "productivity", "branch", "performance")),
]

# One line per report, in the counter's language rather than the scope's.
DESCRIPTIONS = {
	"Branch Sales Register": "Every submitted sale in the period, with tax and what is still owed.",
	"Sales Person Performance": "What each sales person billed, and what it was worth.",
	"IMEI Sales Register": "Which handset went to which customer, by IMEI.",
	"Hourly POS Sales Heatmap": "When the counter is busy, hour by hour.",
	"Offer Effectiveness": "What each campaign discounted, and what it sold.",
	"Exchange Register": "Devices taken in part-exchange and what they were valued at.",
	"Daily Service Register": "Every device booked in, with its status and promised date.",
	"Job Card Status Summary": "Where the workshop's open jobs are standing.",
	"Pending Job Cards Ageing": "How long open repairs have been waiting.",
	"TAT Compliance": "Repairs delivered inside the promised turnaround, and the ones that were not.",
	"Technician Productivity": "Jobs closed and labour earned, per technician.",
	"Service Revenue and GP": "Parts, labour and the margin left on each repair.",
	"Awaiting Parts Register": "Repairs stopped for a part, and what they are waiting for.",
	"Delivery Delay Report": "Devices ready but not yet handed back.",
	"Repeat Repair Analysis": "Devices that came back for the same fault.",
	"Device Model Failure Analysis": "Which models fail, and how.",
	"Warranty vs Chargeable Mix": "How much work the warranty bore against what the customer paid.",
	"Warranty Register": "Every warranty on record and where it stands.",
	"Active Warranty": "Cover still running.",
	"EW Attach Rate": "How often an extended warranty went out with a handset.",
	"Expiring Warranty Upsell List": "Cover about to lapse, for the telecallers.",
	"Warranty Claim Cost": "What the shop spent honouring warranties.",
	"EMI Application Register": "Finance applications and where each one stopped.",
	"EMI Conversion Funnel": "How many EMI enquiries became sales.",
	"EMI Sales by Branch": "What each branch financed, and with which partner.",
	"Financier Performance": "Approval rates, ticket sizes and what each partner still owes.",
	"EMI Scheme Performance": "Which schemes the counter actually sells.",
	"EMI Pending Approval": "Applications sitting with a financier, and for how long.",
	"EMI Commission and Subvention": "What financing costs the shop, per partner.",
	"Outstanding Financier Settlement": "Disbursed sales the financier has not paid for.",
	"EMI Cancellation Register": "Applications that never became sales, and why.",
	"Salesperson EMI Sales": "Who is selling finance, and how much of it.",
	"Financier Receivable Ageing": "Money the financiers still owe, by age.",
	"Settlement Reconciliation": "Card and UPI settlements against the bills they paid.",
	"Branch Stock Summary": "What is on the shelf at each branch.",
	"Stock Ageing and Dead Stock": "Stock that has not moved, by how long.",
	"Stock Transfer Register": "Stock moved between branches.",
	"Cross-Branch Availability": "Where a model is, when this branch has none.",
	"Damage and Loss Register": "Written-off stock and what it cost.",
	"Asset Register by Branch": "The shop's own equipment, by branch.",
	"Courier Cost Analysis": "What dispatch cost, by courier.",
	"Branch Profitability Statement": "Revenue, cost and margin per branch.",
	"Margin Scheme Register": "Second-hand sales under the margin scheme.",
	"RCM Liability and ITC Register": "Reverse charge owed and input credit claimable.",
	"Incentive Payout Register": "What each employee earned in incentive.",
	"Attendance Register": "Who was in, and when.",
	"Daily Footfall Register": "Walk-ins logged at the door.",
	"Footfall Conversion Analysis": "How many walk-ins became bills.",
	"Helpdesk SLA Compliance": "Complaints answered inside the promise.",
	"Telecalling Productivity": "Calls made, and what came of them.",
	"WhatsApp Delivery Report": "Messages sent, delivered and read.",
}


def _category_of(name: str, module: str) -> str:
	lowered = name.lower()
	for key, _label, _desc, _icon, modules, words in CATEGORIES:
		if module in modules:
			return key
	for key, _label, _desc, _icon, _modules, words in CATEGORIES:
		if any(word in lowered for word in words):
			return key
	return "financial"


def _favourites() -> list[str]:
	stored = frappe.defaults.get_user_default(FAVOURITE_KEY) or ""
	return [name for name in stored.split("\n") if name]


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
@frappe.whitelist()
def catalogue() -> dict:
	"""Every report this person may actually run, grouped the way a shop thinks."""
	_me()

	rows = frappe.get_all(
		"Report",
		filters={"module": ["like", "A3 Retail%"], "disabled": 0},
		fields=["name", "module", "ref_doctype", "report_type"],
		order_by="name",
	)

	favourites = _favourites()
	reports = []
	for row in rows:
		if not _may_run(row.name):
			continue
		category = _category_of(row.name, row.module)
		reports.append({
			"name": row.name,
			"description": DESCRIPTIONS.get(row.name)
			or _("Built from {0} records.").format(_(row.ref_doctype or "the ledger")),
			"category": category,
			"module": row.module,
			"ref_doctype": row.ref_doctype,
			"favourite": row.name in favourites,
			"last_run": _last_run(row.name),
		})

	counts = {}
	for report in reports:
		counts[report["category"]] = counts.get(report["category"], 0) + 1

	return {
		"categories": [
			{"key": key, "label": label, "description": description, "icon": icon,
			 "count": counts.get(key, 0)}
			for key, label, description, icon, _modules, _words in CATEGORIES
		],
		"reports": reports,
		"favourites": favourites,
	}


def _may_run(report: str) -> bool:
	"""Frappe's own answer to 'may this person run this report?'."""
	try:
		doc = frappe.get_cached_doc("Report", report)
	except frappe.DoesNotExistError:
		return False

	# Two gates, both Frappe's own: the report's role list, and report permission
	# on the doctype it reads. The runner enforces the second one anyway — asking
	# here as well is what keeps a report the person cannot run off the shelf.
	roles = {row.role for row in doc.get("roles") or []}
	if roles and not roles & set(frappe.get_roles()):
		return False
	if doc.ref_doctype:
		return bool(frappe.has_permission(doc.ref_doctype, "report"))
	return True


def _last_run(report: str) -> str | None:
	return frappe.db.get_value(
		"Prepared Report", {"report_name": report, "status": "Completed"}, "creation",
		order_by="creation desc",
	)


@frappe.whitelist()
def toggle_favourite(report: str) -> dict:
	"""A star against a report, kept per user."""
	_me()
	favourites = _favourites()
	if report in favourites:
		favourites.remove(report)
		starred = False
	else:
		favourites.append(report)
		starred = True

	frappe.defaults.set_user_default(FAVOURITE_KEY, "\n".join(favourites))
	return {"report": report, "favourite": starred}


# ---------------------------------------------------------------------------
# One report
# ---------------------------------------------------------------------------
@frappe.whitelist()
def definition(report: str) -> dict:
	"""The report's own filters, read from the report's own file.

	The filters live beside the report in its `.js`, which is where whoever
	writes a report declares them. Reading them here means a new report brings
	its filters with it and this page needs no edit at all.
	"""
	_me()
	if not _may_run(report):
		frappe.throw(_("You do not have access to {0}.").format(report),
		             frappe.PermissionError)

	doc = frappe.get_cached_doc("Report", report)
	return {
		"name": doc.name,
		"description": DESCRIPTIONS.get(doc.name) or "",
		"category": _category_of(doc.name, doc.module),
		"ref_doctype": doc.ref_doctype,
		"report_type": doc.report_type,
		"filters": _filters_of(doc),
		"favourite": doc.name in _favourites(),
		# A branch filter this person cannot widen is shown as what it is: their
		# own branch, fixed — rather than an empty box that quietly ignores them.
		"branch_locked": not _may_see_every_branch(),
		"branch": _me().branch,
	}


FILTER_BLOCK = re.compile(r"\{[^{}]*fieldname[^{}]*\}", re.S)
FIELD = re.compile(r"(\w+)\s*:\s*(?:__\(\s*)?([\"'])(.*?)\2")
FLAG = re.compile(r"(\w+)\s*:\s*(\d+)")


def _filters_of(doc) -> list[dict]:
	path = _report_js(doc)
	if not path or not os.path.exists(path):
		return _default_filters()

	body = open(path).read()
	start = body.find("filters:")
	if start == -1:
		return []

	filters = []
	for block in FILTER_BLOCK.findall(body[start:]):
		fields = {key: value for key, _quote, value in FIELD.findall(block)}
		flags = {key: cint(value) for key, value in FLAG.findall(block)}
		if not fields.get("fieldname"):
			continue

		filters.append({
			"fieldname": fields["fieldname"],
			"label": fields.get("label") or fields["fieldname"].replace("_", " ").title(),
			"fieldtype": fields.get("fieldtype") or "Data",
			"options": fields.get("options"),
			"reqd": bool(flags.get("reqd")),
			"default": _default_for(fields["fieldname"], block),
		})
	return filters


def _report_js(doc) -> str | None:
	module_path = frappe.get_module_path(doc.module)
	slug = frappe.scrub(doc.name)
	return os.path.join(module_path, "report", slug, f"{slug}.js")


def _default_for(fieldname: str, block: str) -> str | None:
	"""Only the two defaults these reports actually use: today, and a month back."""
	if "add_months" in block:
		return add_months(nowdate(), -1)
	if "get_today" in block:
		return nowdate()
	if fieldname == "from_date":
		return add_months(nowdate(), -1)
	if fieldname == "to_date":
		return nowdate()
	return None


def _default_filters() -> list[dict]:
	return [
		{"fieldname": "from_date", "label": _("From Date"), "fieldtype": "Date",
		 "reqd": True, "default": add_months(nowdate(), -1), "options": None},
		{"fieldname": "to_date", "label": _("To Date"), "fieldtype": "Date",
		 "reqd": True, "default": nowdate(), "options": None},
	]


@frappe.whitelist()
def run(report: str, filters=None) -> dict:
	"""Run the report the ERP already owns, and shape it for a page with no desk."""
	employee = _me()
	if not _may_run(report):
		frappe.throw(_("You do not have access to {0}.").format(report),
		             frappe.PermissionError)

	data = frappe.parse_json(filters) if isinstance(filters, str) else dict(filters or {})
	data = {key: value for key, value in data.items() if value not in (None, "", "all")}

	# A raw SQL report does not go through user permissions, so the branch this
	# person works at is applied here rather than trusted from the browser.
	definition_filters = {row["fieldname"] for row in _filters_of(
		frappe.get_cached_doc("Report", report))}
	if "branch" in definition_filters and not _may_see_every_branch():
		data["branch"] = employee.branch

	from frappe.desk.query_report import run as query_report_run

	result = query_report_run(report, filters=data, ignore_prepared_report=True,
	                          are_default_filters=False)

	columns = [_column(column) for column in result.get("columns") or []]
	rows = _rows(result.get("result") or [], columns)

	return {
		"report": report,
		"columns": columns,
		"rows": rows,
		"totals": _totals(rows, columns),
		"kpis": _kpis(rows, columns),
		"chart": _chart(rows, columns),
		"filters": data,
		"branch": data.get("branch") or employee.branch,
		"generated_on": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M"),
		"generated_by": employee.employee_name,
		"row_count": len(rows),
	}


def _may_see_every_branch() -> bool:
	return bool({"A3 Retail Admin", "Accounts Manager", "System Manager"} & set(frappe.get_roles()))


def _column(column) -> dict:
	"""Frappe hands columns back as dicts or as "label:Type/Options:width" strings."""
	if isinstance(column, dict):
		return {
			"label": column.get("label") or column.get("fieldname"),
			"fieldname": column.get("fieldname") or frappe.scrub(column.get("label") or ""),
			"fieldtype": column.get("fieldtype") or "Data",
			"options": column.get("options"),
			"width": cint(column.get("width")) or 120,
		}

	parts = str(column).split(":")
	label = parts[0]
	fieldtype = parts[1].split("/")[0] if len(parts) > 1 else "Data"
	options = parts[1].split("/")[1] if len(parts) > 1 and "/" in parts[1] else None
	return {
		"label": label,
		"fieldname": frappe.scrub(label),
		"fieldtype": fieldtype or "Data",
		"options": options,
		"width": cint(parts[2]) if len(parts) > 2 else 120,
	}


NUMERIC = ("Currency", "Float", "Int", "Percent")


def _rows(result: list, columns: list[dict]) -> list[dict]:
	rows = []
	for row in result:
		if isinstance(row, dict):
			rows.append({column["fieldname"]: row.get(column["fieldname"]) for column in columns})
		else:
			rows.append({column["fieldname"]: row[index] if index < len(row) else None
			             for index, column in enumerate(columns)})
	return rows


def _totals(rows: list[dict], columns: list[dict]) -> dict:
	"""Money and counts add up. An average turnaround does not — adding three
	technicians' average hours together produces a number that means nothing, so
	those columns get no total at all rather than a wrong one.
	"""
	totals = {}
	for column in columns:
		if column["fieldtype"] in ("Currency", "Int"):
			totals[column["fieldname"]] = sum(flt(row.get(column["fieldname"])) for row in rows)
	return totals


def _kpis(rows: list[dict], columns: list[dict]) -> list[dict]:
	"""The money and the counts, as cards — at most five, in column order."""
	kpis = [{"label": _("Rows"), "value": len(rows), "fieldtype": "Int"}]

	for column in columns:
		if column["fieldtype"] not in ("Currency", "Int"):
			continue
		if len(kpis) >= 6:
			break
		kpis.append({
			"label": column["label"],
			"value": sum(flt(row.get(column["fieldname"])) for row in rows),
			"fieldtype": column["fieldtype"],
		})
	return kpis


def _chart(rows: list[dict], columns: list[dict]) -> dict | None:
	"""One series, and only when the report actually has a shape worth drawing.

	A date down the side and money across it is a trend; anything else is a
	table, and a chart of it would be decoration.
	"""
	if len(rows) < 2:
		return None

	label_column = next(
		(column for column in columns if column["fieldtype"] in ("Date", "Datetime")), None
	)
	if not label_column:
		label_column = next(
			(column for column in columns if column["fieldtype"] in ("Data", "Link")), None
		)
	value_column = next((column for column in columns if column["fieldtype"] == "Currency"), None)
	if not label_column or not value_column:
		return None

	buckets: dict[str, float] = {}
	for row in rows:
		key = str(row.get(label_column["fieldname"]) or "")[:10]
		if not key:
			continue
		buckets[key] = buckets.get(key, 0) + flt(row.get(value_column["fieldname"]))

	if len(buckets) < 2 or len(buckets) > 60:
		return None

	points = sorted(buckets.items())
	return {
		"label": f"{value_column['label']} by {label_column['label']}",
		"kind": "line" if label_column["fieldtype"] in ("Date", "Datetime") else "bar",
		"points": [{"label": key, "value": value} for key, value in points],
	}
