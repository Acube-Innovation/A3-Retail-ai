# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Report register helpers and the Auto Email Report schedule (scope 12.5, 12.6).

The 42 reports themselves live on disk under `<module>/report/`; this module owns
the sweep that proves they all execute, and the ten scheduled deliveries — which
ship disabled, because a fresh install has no business emailing anyone.
"""

import json
import time

import frappe
from frappe.utils import add_months, nowdate

# report, frequency, hour, roles that receive it, format.
# Frappe's Auto Email Report only accepts HTML / XLSX / CSV, so the scope's "PDF"
# deliveries go out as HTML — the same layout, rendered in the mail client.
SCHEDULES = [
	("Daily Service Register", "Daily", "21:00:00", ["Branch Manager", "Service Manager"], "HTML"),
	("Branch Sales Register", "Daily", "21:15:00", ["Branch Manager", "Accounts Manager"], "HTML"),
	("Delivery Delay Report", "Daily", "11:00:00", ["Service Manager", "Branch Manager"], "XLSX"),
	("Awaiting Parts Register", "Daily", "10:00:00", ["Store Keeper", "Service Manager"], "XLSX"),
	("Expiring Warranty Upsell List", "Weekly", "09:00:00", ["Telecaller"], "XLSX"),
	("Stock Ageing and Dead Stock", "Weekly", "09:30:00", ["Branch Manager", "A3 Retail Admin"],
	 "XLSX"),
	("Footfall Conversion Analysis", "Weekly", "10:00:00", ["A3 Retail Admin"], "HTML"),
	("Branch Profitability Statement", "Monthly", "10:00:00",
	 ["A3 Retail Admin", "Accounts Manager"], "XLSX"),
	("Incentive Payout Register", "Monthly", "10:00:00", ["HR Manager", "Accounts Manager"],
	 "XLSX"),
	("RCM Liability and ITC Register", "Monthly", "10:00:00", ["Accounts Manager"], "XLSX"),
]


def run():
	ensure_auto_email_reports()


def ensure_auto_email_reports() -> int:
	"""Create the ten scheduled deliveries, disabled (scope 12.6)."""
	created = 0
	for report, frequency, hour, roles, file_format in SCHEDULES:
		if not frappe.db.exists("Report", report):
			continue

		recipients = _recipients(roles)
		if not recipients:
			continue

		existing = frappe.db.get_value("Auto Email Report", {"report": report}, "name")
		if existing:
			continue

		doc = frappe.new_doc("Auto Email Report")
		doc.report = report
		doc.report_type = frappe.db.get_value("Report", report, "report_type")
		doc.reference_report = report
		doc.user = "Administrator"
		doc.enabled = 0
		doc.frequency = frequency
		doc.format = file_format
		doc.email_to = "\n".join(recipients)
		doc.day_of_week = "Monday" if frequency == "Weekly" else None
		doc.send_if_data = 1
		doc.filters = json.dumps(_default_filters(report))
		doc.description = f"A3 Retail scheduled delivery — {frequency.lower()} at {hour[:5]}."
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_permissions=True)
			created += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: auto email {report}")
	return created


def _recipients(roles: list[str]) -> list[str]:
	users = set()
	for role in roles:
		users.update(
			frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"},
			               pluck="parent")
		)
	return sorted(
		user for user in users
		if "@" in user and frappe.db.get_value("User", user, "enabled")
	)


def _default_filters(report: str) -> dict:
	meta = frappe.db.get_value("Report", report, ["report_type"], as_dict=True)
	if not meta:
		return {}
	return {"from_date": str(add_months(nowdate(), -1)), "to_date": str(nowdate())}


# ---------------------------------------------------------------- smoke test
def registered_reports() -> list[str]:
	return frappe.get_all(
		"Report", filters={"module": ["like", "A3 Retail%"], "disabled": 0},
		order_by="name", pluck="name",
	)


def smoke_test(verbose: bool = True, slow_seconds: float = 3.0) -> dict:
	"""Execute every report with default filters (scope 12.5 acceptance).

	    bench --site <site> execute a3_retail.setup.reports.smoke_test
	"""
	from frappe.desk.query_report import run as run_report

	rows, failures, slow = [], [], []
	filters = {"from_date": str(add_months(nowdate(), -12)), "to_date": str(nowdate())}

	for name in registered_reports():
		started = time.time()
		try:
			result = run_report(name, filters=filters, ignore_prepared_report=True)
			elapsed = time.time() - started
			count = len(result.get("result") or [])
			if elapsed > slow_seconds:
				slow.append(name)
			rows.append((name, "ok", f"{count} rows in {elapsed:.2f}s"))
		except Exception as exc:
			failures.append(name)
			rows.append((name, "FAILED", str(exc).split("\n")[0][:120]))

	if verbose:
		width = max(len(row[0]) for row in rows) + 2
		print(f"\n{'Report'.ljust(width)}{'Status'.ljust(10)}Detail")
		print("-" * (width + 40))
		for name, status, detail in rows:
			print(f"{name.ljust(width)}{status.ljust(10)}{detail}")
		print(f"\n{len(rows) - len(failures)}/{len(rows)} reports executed")
		if slow:
			print(f"slower than {slow_seconds}s: {', '.join(slow)}")

	return {"total": len(rows), "failed": failures, "slow": slow, "rows": rows}
