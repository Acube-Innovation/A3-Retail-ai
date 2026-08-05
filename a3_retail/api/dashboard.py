# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Service Control Tower data contract (scope 12.1).

One call returns everything the screen draws: counters, funnel, TAT, the live job
board, parts position, delivery delays, technician load and the branch strip.
Each counter is a single indexed COUNT(*) — the composite indexes added in
`patches/v1_0/add_dashboard_indexes.py` are what keep this fast on a busy day —
and the branch strip, the expensive part, is cached in Redis for 60 seconds.
"""

import frappe
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_datetime,
	now_datetime,
	nowdate,
	time_diff_in_hours,
)

from a3_retail.api import require_branch_access, require_permission
from a3_retail.utils.permissions import get_permitted_branches

OPEN_STATUSES = (
	"Open", "Under Diagnosis", "Estimate Pending", "Estimate Sent", "Estimate Approved",
	"Awaiting Parts", "In Progress", "QC Pending", "QC Failed", "Ready for Delivery",
	"On Hold", "Awaiting Customer Approval",
)
WIP_STATUSES = ("Under Diagnosis", "In Progress", "Awaiting Parts")
FUNNEL_STATUSES = (
	"Open", "Under Diagnosis", "Estimate Sent", "Estimate Approved", "Awaiting Parts",
	"In Progress", "QC Pending", "Ready for Delivery",
)

BRANCH_STRIP_CACHE_KEY = "a3_control_tower_branch_strip"
BRANCH_STRIP_TTL = 60


@frappe.whitelist()
def control_tower(branch: str | None = None, period: str = "today") -> dict:
	"""The whole screen in one round trip (scope 12.1)."""
	require_permission("Service Job Card")
	require_branch_access(branch)

	branches = _visible_branches(branch)
	start, end = period_range(period)

	return {
		"branch": branch,
		"period": period,
		"as_of": str(now_datetime()),
		"counters": counters(branches, start, end),
		"funnel": funnel(branches),
		"tat": tat_summary(branches, start, end),
		"job_cards": job_board(branches),
		"parts": parts_position(branches),
		"delivery_delays": delivery_delays(branches),
		"technician_load": technician_load(branches),
		"branches": [] if branch else branch_strip(start, end),
	}


def period_range(period: str) -> tuple[str, str]:
	today = nowdate()
	if period == "week":
		return str(add_days(today, -6)), today
	if period == "month":
		return str(add_days(today, -29)), today
	return today, today


def _visible_branches(branch: str | None) -> list[str]:
	"""The branches this call may read — the user's permissions, narrowed by the filter."""
	permitted = get_permitted_branches()
	if branch:
		return [branch]
	if permitted:
		return list(permitted)
	return frappe.get_all("Branch", pluck="name")


def _branch_clause(branches: list[str], alias: str = "jc", field: str = "branch") -> str:
	if not branches:
		return ""
	values = ", ".join(frappe.db.escape(b) for b in branches)
	return f" and {alias}.`{field}` in ({values})"


# ------------------------------------------------------------------ counters
def counters(branches: list[str], start: str, end: str) -> dict:
	jc = _branch_clause(branches)
	si = _branch_clause(branches, "si")
	values = {"start": start, "end": end}

	def count(condition: str) -> int:
		return cint(
			frappe.db.sql(
				f"select count(*) from `tabService Job Card` jc "
				f"where jc.docstatus = 1 and {condition}{jc}",
				values,
			)[0][0]
		)

	received = count("date(jc.received_on) between %(start)s and %(end)s")
	ongoing = count(f"jc.status in {WIP_STATUSES}")
	awaiting_parts = count("jc.status = 'Awaiting Parts'")
	ready = count("jc.status = 'Ready for Delivery'")
	delivered = count("date(jc.delivered_on) between %(start)s and %(end)s")
	delayed = count("jc.is_delayed = 1 and jc.status not in ('Delivered', 'Closed', 'Cancelled')")

	revenue = frappe.db.sql(
		f"""
		select
			sum(case when exists (
					select 1 from `tabSales Invoice Item` sii
					join `tabItem` i on i.name = sii.item_code
					where sii.parent = si.name and ifnull(i.a3_is_service_item, 0) = 1)
				then si.base_grand_total else 0 end) as service_revenue,
			sum(si.base_grand_total) as total_revenue
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_return = 0
		  and si.posting_date between %(start)s and %(end)s{si}
		""",
		values,
		as_dict=True,
	)[0]

	footfall = cint(
		frappe.db.sql(
			f"select count(*) from `tabBranch Visit Log` jc "
			f"where date(jc.visit_datetime) between %(start)s and %(end)s{jc}",
			values,
		)[0][0]
	)

	open_tickets = cint(
		frappe.db.sql(
			f"select count(*) from `tabIssue` jc "
			f"where jc.status not in ('Closed', 'Resolved')"
			f"{_branch_clause(branches, 'jc', 'a3_branch')}"
		)[0][0]
	)

	service_revenue = flt(revenue.service_revenue)
	return {
		"received_today": received,
		"ongoing": ongoing,
		"awaiting_parts": awaiting_parts,
		"ready_for_delivery": ready,
		"delivered_today": delivered,
		"delayed": delayed,
		"service_revenue_today": service_revenue,
		"sales_revenue_today": flt(revenue.total_revenue) - service_revenue,
		"footfall_today": footfall,
		"open_tickets": open_tickets,
	}


def funnel(branches: list[str]) -> list[dict]:
	rows = frappe.db.sql(
		f"""
		select jc.status, count(*) as count from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status in {FUNNEL_STATUSES}{_branch_clause(branches)}
		group by jc.status
		""",
		as_dict=True,
	)
	by_status = {row.status: row.count for row in rows}
	return [{"status": status, "count": by_status.get(status, 0)} for status in FUNNEL_STATUSES]


def tat_summary(branches: list[str], start: str, end: str) -> dict:
	row = frappe.db.sql(
		f"""
		select
			count(*) as total,
			sum(case when jc.sla_due_on is null or jc.delivered_on <= jc.sla_due_on
			         then 1 else 0 end) as on_time,
			avg(timestampdiff(hour, jc.received_on, jc.delivered_on) - ifnull(jc.paused_hours, 0))
				as avg_hours
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.delivered_on is not null
		  and date(jc.delivered_on) between %(start)s and %(end)s{_branch_clause(branches)}
		""",
		{"start": start, "end": end},
		as_dict=True,
	)[0]

	total = cint(row.total)
	if not total:
		return {"on_time": 0.0, "breached": 0.0, "avg_hours": 0.0, "delivered": 0}

	on_time = round(cint(row.on_time) / total * 100, 1)
	return {
		"on_time": on_time,
		"breached": round(100 - on_time, 1),
		"avg_hours": round(flt(row.avg_hours), 1),
		"delivered": total,
	}


# ---------------------------------------------------------------- job board
def job_board(branches: list[str], limit: int = 200) -> list[dict]:
	rows = frappe.db.sql(
		f"""
		select jc.name, jc.customer_name, jc.device_model, jc.imei_1, jc.status,
		       jc.assigned_technician, jc.received_on, jc.sla_due_on, jc.is_delayed,
		       jc.branch, jc.priority
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status in {OPEN_STATUSES}{_branch_clause(branches)}
		order by jc.is_delayed desc, jc.sla_due_on asc
		limit {cint(limit)}
		""",
		as_dict=True,
	)

	now = now_datetime()
	return [
		{
			"name": row.name,
			"customer": row.customer_name,
			"device": row.device_model,
			"imei": row.imei_1,
			"status": row.status,
			"technician": row.assigned_technician,
			"branch": row.branch,
			"age_hours": round(time_diff_in_hours(now, get_datetime(row.received_on)), 1)
			if row.received_on else 0,
			"due_on": str(row.sla_due_on or ""),
			"flag": _flag(row, now),
		}
		for row in rows
	]


def _flag(row, now) -> str:
	"""green on time · amber past 80% of the TAT · red breached · grey on hold."""
	if row.status in ("On Hold", "Awaiting Customer Approval"):
		return "grey"
	if row.is_delayed:
		return "red"
	if not row.sla_due_on or not row.received_on:
		return "green"

	total = time_diff_in_hours(get_datetime(row.sla_due_on), get_datetime(row.received_on))
	elapsed = time_diff_in_hours(now, get_datetime(row.received_on))
	if total <= 0 or elapsed >= total:
		return "red"
	return "amber" if elapsed / total >= 0.8 else "green"


# -------------------------------------------------------------- side panels
def parts_position(branches: list[str], limit: int = 25) -> list[dict]:
	"""What the bay is waiting for, and whether it is anywhere in the company."""
	rows = frappe.db.sql(
		f"""
		select p.item_code, sum(p.qty) as required
		from `tabJob Card Part` p
		join `tabService Job Card` jc on jc.name = p.parent
		where jc.docstatus = 1 and jc.status = 'Awaiting Parts'
		  and p.part_status in ('Required', 'Awaiting Purchase', 'Awaiting Transfer')
		  {_branch_clause(branches)}
		group by p.item_code
		order by required desc
		limit {cint(limit)}
		""",
		as_dict=True,
	)

	position = []
	for row in rows:
		available = flt(
			frappe.db.sql(
				"select sum(actual_qty) from `tabBin` where item_code = %s", row.item_code
			)[0][0]
		)
		incoming = frappe.db.sql(
			"""select poi.parent, min(poi.schedule_date) as eta
			   from `tabPurchase Order Item` poi
			   join `tabPurchase Order` po on po.name = poi.parent
			   where poi.item_code = %s and po.docstatus = 1 and po.status != 'Closed'
			     and poi.received_qty < poi.qty
			   group by poi.parent limit 1""",
			row.item_code,
			as_dict=True,
		)
		position.append(
			{
				"item": row.item_code,
				"required": flt(row.required),
				"available": available,
				"short": max(flt(row.required) - available, 0),
				"eta": str(incoming[0].eta) if incoming else "",
				"source": incoming[0].parent if incoming else "",
			}
		)
	return position


def delivery_delays(branches: list[str], limit: int = 25) -> list[dict]:
	rows = frappe.db.sql(
		f"""
		select jc.name, jc.customer_name, jc.estimated_delivery_date, jc.status,
		       jc.delay_reason, jc.hold_reason,
		       datediff(curdate(), date(jc.estimated_delivery_date)) as days_late
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status not in ('Delivered', 'Closed', 'Cancelled')
		  and jc.estimated_delivery_date is not null
		  and jc.estimated_delivery_date < now(){_branch_clause(branches)}
		order by days_late desc
		limit {cint(limit)}
		""",
		as_dict=True,
	)
	return [
		{
			"job_card": row.name,
			"customer": row.customer_name,
			"promised": str(row.estimated_delivery_date or ""),
			"days_late": cint(row.days_late),
			"reason": row.delay_reason or row.hold_reason or row.status,
		}
		for row in rows
	]


def technician_load(branches: list[str]) -> list[dict]:
	rows = frappe.db.sql(
		f"""
		select t.name, t.employee_name, t.employee, t.max_concurrent_jobs as capacity,
		       (select count(*) from `tabService Job Card` jc
		        where jc.assigned_technician = t.employee and jc.docstatus = 1
		          and jc.status in {WIP_STATUSES}) as wip
		from `tabTechnician Profile` t
		where t.is_active = 1{_branch_clause(branches, 't')}
		order by wip desc
		""",
		as_dict=True,
	)
	load = []
	for row in rows:
		capacity = cint(row.capacity) or 1
		load.append(
			{
				"technician": row.employee_name or row.name,
				"wip": cint(row.wip),
				"capacity": capacity,
				"utilisation": round(cint(row.wip) / capacity * 100),
			}
		)
	return load


# ------------------------------------------------------------- branch strip
def branch_strip(start: str, end: str, use_cache: bool = True) -> list[dict]:
	"""One row per branch. Cached for 60 s — it is the expensive query (scope 12.1)."""
	cache_key = f"{BRANCH_STRIP_CACHE_KEY}:{start}:{end}:{frappe.session.user}"
	if use_cache:
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached

	permitted = get_permitted_branches()
	branches = list(permitted) if permitted else frappe.get_all("Branch", pluck="name")

	strip = []
	for branch in branches:
		single = [branch]
		row = counters(single, start, end)
		tat = tat_summary(single, start, end)
		strip.append(
			{
				"branch": branch,
				"in": row["received_today"],
				"wip": row["ongoing"],
				"ready": row["ready_for_delivery"],
				"delayed": row["delayed"],
				"tat_pct": tat["on_time"],
				"service": row["service_revenue_today"],
				"sales": row["sales_revenue_today"],
				"footfall": row["footfall_today"],
			}
		)

	if use_cache:
		frappe.cache().set_value(cache_key, strip, expires_in_sec=BRANCH_STRIP_TTL)
	return strip


# ---------------------------------------------------------------- realtime
def notify(doc, method=None):
	"""Nudge every subscribed control tower after a document that moves a counter."""
	from a3_retail.utils import publish_dashboard_update

	branch = doc.get("branch") or doc.get("a3_branch") or doc.get("requesting_branch")
	code = frappe.db.get_value("Branch Profile", {"branch": branch}, "branch_code") if branch else None
	publish_dashboard_update(code or branch, {"branch": branch, "doctype": doc.doctype})


# -------------------------------------------------------------- cross-check
@frappe.whitelist()
def counter_cross_check(branch: str | None = None) -> dict:
	"""Scope 12.8 — the same numbers straight from SQL, for reconciliation."""
	require_permission("Service Job Card")
	clause = _branch_clause([branch]) if branch else ""

	return frappe.db.sql(
		f"""
		select
			(select count(*) from `tabService Job Card` jc
			 where jc.docstatus = 1 and date(jc.received_on) = curdate(){clause}) as received_today,
			(select count(*) from `tabService Job Card` jc
			 where jc.docstatus = 1 and jc.status in {WIP_STATUSES}{clause}) as wip,
			(select count(*) from `tabService Job Card` jc
			 where jc.docstatus = 1 and jc.status = 'Ready for Delivery'{clause}) as ready,
			(select count(*) from `tabService Job Card` jc
			 where jc.docstatus = 1 and jc.is_delayed = 1
			   and jc.status not in ('Delivered', 'Closed'){clause}) as `delayed`
		""",
		as_dict=True,
	)[0]
