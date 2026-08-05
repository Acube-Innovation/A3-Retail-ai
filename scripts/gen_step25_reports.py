#!/usr/bin/env python3
"""Generate the 42 standard reports in the scope 12.5 register.

Each report becomes a folder under <module>/report/<scrub>/ holding the Report
JSON, a filters .js and an execute() that runs one SQL statement through
`a3_retail.reporting.run_query` — which is what applies the caller's branch
permissions. Re-running this script rewrites every file, so the register here is
the single source of truth.
"""

import json
import os

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "a3_retail")

MODULE_DIRS = {
	"A3 Retail Service": "a3_retail_service",
	"A3 Retail Sales": "a3_retail_sales",
	"A3 Retail Finance": "a3_retail_finance",
	"A3 Retail Warranty": "a3_retail_warranty",
	"A3 Retail Operations": "a3_retail_operations",
	"A3 Retail Communication": "a3_retail_communication",
	"A3 Retail Dashboard": "a3_retail_dashboard",
}

PERIOD_FILTERS = """frappe.query_reports["{title}"] = {{
	filters: [
		{{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		}},
		{{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		}},
		{{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" }},
{extra}	],
}};
"""

BRANCH_FILTERS = """frappe.query_reports["{title}"] = {{
	filters: [
		{{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" }},
{extra}	],
}};
"""

REPORT_PY = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""{title} — scope 12.5 report #{number}."""

import frappe

from a3_retail.reporting import col, run_query{extra_imports}

COLUMNS = [
{columns}]

SQL = """
{sql}
"""


def execute(filters=None):
{body}
'''

DEFAULT_BODY = """	return run_query(COLUMNS, SQL, filters, alias={alias!r}, branch_field={branch_field!r},
	                 date_field={date_field!r})"""


def spec(number, title, module, ref_doctype, roles, columns, sql, alias="t",
         branch_field="branch", date_field=None, filters="period", extra_filters="",
         body=None, extra_imports=""):
	return {
		"number": number,
		"title": title,
		"module": module,
		"ref_doctype": ref_doctype,
		"roles": roles,
		"columns": columns,
		"sql": sql.strip(),
		"alias": alias,
		"branch_field": branch_field,
		"date_field": date_field,
		"filters": filters,
		"extra_filters": extra_filters,
		"body": body,
		"extra_imports": extra_imports,
	}


SERVICE_ROLES = ["Service Manager", "Branch Manager", "A3 Retail Admin"]
SALES_ROLES = ["Sales Executive", "Branch Manager", "A3 Retail Admin"]
ACCOUNTS_ROLES = ["Accounts Manager", "A3 Retail Admin"]
STORE_ROLES = ["Store Keeper", "Branch Manager", "A3 Retail Admin"]
CARE_ROLES = ["Helpdesk Agent", "Branch Manager", "A3 Retail Admin"]
HR_ROLES = ["HR Manager", "A3 Retail Admin"]

REPORTS = [
	# ------------------------------------------------------------------ service
	spec(1, "Daily Service Register", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Job Card", "name", "Link", 140, "Service Job Card"),
	      ("Received", "received_on", "Datetime", 150),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 150),
	      ("Mobile", "customer_mobile", "Data", 110),
	      ("Device", "device_model", "Data", 150),
	      ("IMEI", "imei_1", "Data", 130),
	      ("Complaint", "complaint_description", "Data", 200),
	      ("Technician", "assigned_technician", "Link", 120, "Employee"),
	      ("Status", "status", "Data", 130),
	      ("Amount", "grand_total", "Currency", 110)],
	     """
		select jc.name, jc.received_on, jc.branch, jc.customer_name, jc.customer_mobile,
		       jc.device_model, jc.imei_1, jc.complaint_description, jc.assigned_technician,
		       jc.status, jc.grand_total
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		order by jc.received_on desc
	     """, alias="jc", date_field="jc.received_on"),

	spec(2, "Job Card Status Summary", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Status", "status", "Data", 180),
	      ("Job Cards", "count", "Int", 100),
	      ("Value", "value", "Currency", 130),
	      ("Oldest (days)", "oldest_days", "Int", 120)],
	     """
		select jc.status, count(*) as count, sum(jc.grand_total) as value,
		       max(datediff(curdate(), date(jc.received_on))) as oldest_days
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		group by jc.status
		order by count desc
	     """, alias="jc", date_field="jc.received_on"),

	spec(3, "Pending Job Cards Ageing", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Job Card", "name", "Link", 140, "Service Job Card"),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 150),
	      ("Status", "status", "Data", 140),
	      ("Age (days)", "age_days", "Int", 100),
	      ("Bucket", "bucket", "Data", 110),
	      ("Technician", "assigned_technician", "Link", 130, "Employee"),
	      ("Due", "sla_due_on", "Datetime", 150)],
	     """
		select jc.name, jc.branch, jc.customer_name, jc.status, jc.assigned_technician,
		       jc.sla_due_on, datediff(curdate(), date(jc.received_on)) as age_days,
		       case
		         when datediff(curdate(), date(jc.received_on)) <= 3 then '0-3 days'
		         when datediff(curdate(), date(jc.received_on)) <= 7 then '4-7 days'
		         when datediff(curdate(), date(jc.received_on)) <= 15 then '8-15 days'
		         else '15+ days' end as bucket
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status not in ('Delivered', 'Closed', 'Cancelled')
		  {conditions}
		order by age_days desc
	     """, alias="jc", filters="branch"),

	spec(4, "TAT Compliance", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Delivered", "delivered", "Int", 100),
	      ("On Time", "on_time", "Int", 100),
	      ("Breached", "breached", "Int", 100),
	      ("Compliance %", "compliance", "Percent", 120),
	      ("Average TAT (h)", "avg_hours", "Float", 130)],
	     """
		select jc.branch,
		       count(*) as delivered,
		       sum(case when jc.sla_due_on is null or jc.delivered_on <= jc.sla_due_on
		                then 1 else 0 end) as on_time,
		       sum(case when jc.sla_due_on is not null and jc.delivered_on > jc.sla_due_on
		                then 1 else 0 end) as breached,
		       avg(timestampdiff(hour, jc.received_on, jc.delivered_on)
		           - ifnull(jc.paused_hours, 0)) as avg_hours
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.delivered_on is not null {conditions}
		group by jc.branch
	     """, alias="jc", date_field="jc.delivered_on",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="jc", date_field="jc.delivered_on")
	for row in data:
		row["compliance"] = percent(row.get("on_time"), row.get("delivered"))
		row["avg_hours"] = round(row.get("avg_hours") or 0, 1)
	return columns, data"""),

	spec(5, "Technician Productivity", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Technician", "assigned_technician", "Link", 140, "Employee"),
	      ("Name", "employee_name", "Data", 150),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Jobs Delivered", "jobs", "Int", 120),
	      ("Labour Value", "labour_value", "Currency", 130),
	      ("Parts Value", "parts_value", "Currency", 130),
	      ("Average TAT (h)", "avg_hours", "Float", 130),
	      ("QC Failures", "qc_failures", "Int", 110)],
	     """
		select jc.assigned_technician, e.employee_name, jc.branch,
		       count(*) as jobs,
		       sum(jc.labour_total) as labour_value,
		       sum(jc.parts_total) as parts_value,
		       round(avg(timestampdiff(hour, jc.received_on, jc.delivered_on)), 1) as avg_hours,
		       (select count(distinct l.parent) from `tabJob Card Status Log` l
		        join `tabService Job Card` j2 on j2.name = l.parent
		        where l.to_status = 'QC Failed' and j2.assigned_technician = jc.assigned_technician
		          and date(j2.received_on) between %(from_date)s and %(to_date)s) as qc_failures
		from `tabService Job Card` jc
		left join `tabEmployee` e on e.name = jc.assigned_technician
		where jc.docstatus = 1 and jc.status in ('Delivered', 'Closed')
		  and jc.assigned_technician is not null {conditions}
		group by jc.assigned_technician, e.employee_name, jc.branch
		order by jobs desc
	     """, alias="jc", date_field="jc.delivered_on"),

	spec(6, "Awaiting Parts Register", "A3 Retail Service", "Service Job Card", STORE_ROLES,
	     [("Job Card", "name", "Link", 140, "Service Job Card"),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 150),
	      ("Part", "item_code", "Link", 160, "Item"),
	      ("Qty", "qty", "Float", 80),
	      ("Status", "part_status", "Data", 130),
	      ("Waiting (days)", "waiting_days", "Int", 120),
	      ("Request", "stock_request", "Link", 140, "Stock Request")],
	     """
		select jc.name, jc.branch, jc.customer_name, p.item_code, p.qty, p.part_status,
		       p.stock_request, datediff(curdate(), date(jc.received_on)) as waiting_days
		from `tabJob Card Part` p
		join `tabService Job Card` jc on jc.name = p.parent
		where jc.docstatus = 1 and jc.status = 'Awaiting Parts'
		  and p.part_status in ('Required', 'Awaiting Purchase', 'Awaiting Transfer')
		  {conditions}
		order by waiting_days desc
	     """, alias="jc", filters="branch"),

	spec(7, "Repeat Repair Analysis", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("IMEI", "imei_1", "Data", 140),
	      ("Device", "device_model", "Data", 150),
	      ("Customer", "customer_name", "Data", 150),
	      ("Visits", "visits", "Int", 90),
	      ("First Visit", "first_visit", "Datetime", 150),
	      ("Last Visit", "last_visit", "Datetime", 150),
	      ("Days Between", "days_between", "Int", 120),
	      ("Total Billed", "billed", "Currency", 130)],
	     """
		select jc.imei_1, max(jc.device_model) as device_model, max(jc.customer_name) as customer_name,
		       count(*) as visits, min(jc.received_on) as first_visit, max(jc.received_on) as last_visit,
		       datediff(max(jc.received_on), min(jc.received_on)) as days_between,
		       sum(jc.grand_total) as billed
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.imei_1, '') != '' {conditions}
		group by jc.imei_1
		having visits > 1 and days_between <= 30
		order by visits desc, days_between asc
	     """, alias="jc", date_field="jc.received_on"),

	spec(8, "Warranty vs Chargeable Mix", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Warranty Type", "warranty_type", "Data", 160),
	      ("Job Cards", "jobs", "Int", 100),
	      ("Customer Payable", "customer_payable", "Currency", 140),
	      ("Warranty Borne", "warranty_borne", "Currency", 140)],
	     """
		select jc.branch, ifnull(jc.warranty_type, 'Not Recorded') as warranty_type,
		       count(*) as jobs, sum(jc.customer_payable) as customer_payable,
		       sum(jc.warranty_borne_amount) as warranty_borne
		from `tabService Job Card` jc
		where jc.docstatus = 1 {conditions}
		group by jc.branch, jc.warranty_type
		order by jc.branch, jobs desc
	     """, alias="jc", date_field="jc.received_on"),

	spec(9, "Service Revenue and GP", "A3 Retail Service", "Service Job Card", ACCOUNTS_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Jobs", "jobs", "Int", 90),
	      ("Parts Revenue", "parts_total", "Currency", 130),
	      ("Labour Revenue", "labour_total", "Currency", 130),
	      ("Parts Cost", "parts_cost", "Currency", 130),
	      ("Gross Profit", "gross_profit", "Currency", 130),
	      ("GP %", "gp_percent", "Percent", 100)],
	     """
		select jc.branch, count(*) as jobs,
		       sum(jc.parts_total) as parts_total, sum(jc.labour_total) as labour_total,
		       (select ifnull(sum(p.qty * p.valuation_rate), 0) from `tabJob Card Part` p
		        where p.parent = jc.name) as parts_cost
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.status in ('Delivered', 'Closed') {conditions}
		group by jc.branch
	     """, alias="jc", date_field="jc.delivered_on",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="jc", date_field="jc.delivered_on")
	for row in data:
		revenue = (row.get("parts_total") or 0) + (row.get("labour_total") or 0)
		row["gross_profit"] = revenue - (row.get("parts_cost") or 0)
		row["gp_percent"] = percent(row["gross_profit"], revenue)
	return columns, data"""),

	spec(10, "Delivery Delay Report", "A3 Retail Service", "Service Job Card", SERVICE_ROLES,
	     [("Job Card", "name", "Link", 140, "Service Job Card"),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 150),
	      ("Promised", "estimated_delivery_date", "Datetime", 150),
	      ("Delivered", "delivered_on", "Datetime", 150),
	      ("Days Late", "days_late", "Int", 100),
	      ("Reason", "reason", "Data", 200)],
	     """
		select jc.name, jc.branch, jc.customer_name, jc.estimated_delivery_date, jc.delivered_on,
		       datediff(ifnull(date(jc.delivered_on), curdate()),
		                date(jc.estimated_delivery_date)) as days_late,
		       coalesce(nullif(jc.delay_reason, ''), nullif(jc.hold_reason, ''), jc.status) as reason
		from `tabService Job Card` jc
		where jc.docstatus = 1 and jc.estimated_delivery_date is not null
		  and (jc.delivered_on is null or jc.delivered_on > jc.estimated_delivery_date)
		  {conditions}
		having days_late > 0
		order by days_late desc
	     """, alias="jc", date_field="jc.received_on"),

	spec(11, "Device Model Failure Analysis", "A3 Retail Service", "Service Job Card",
	     SERVICE_ROLES,
	     [("Device Model", "device_model", "Data", 180),
	      ("Brand", "brand", "Link", 120, "Brand"),
	      ("Job Cards", "jobs", "Int", 100),
	      ("Top Category", "repair_category", "Data", 160),
	      ("Average Cost", "avg_cost", "Currency", 130),
	      ("Warranty Jobs", "warranty_jobs", "Int", 120)],
	     """
		select jc.device_model, jc.brand, count(*) as jobs,
		       jc.repair_category,
		       round(avg(jc.grand_total), 2) as avg_cost,
		       sum(case when jc.warranty_type like '%%Warranty%%' then 1 else 0 end) as warranty_jobs
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.device_model, '') != '' {conditions}
		group by jc.device_model, jc.brand, jc.repair_category
		order by jobs desc
	     """, alias="jc", date_field="jc.received_on"),

	# -------------------------------------------------------------------- sales
	spec(12, "Branch Sales Register", "A3 Retail Sales", "Sales Invoice", SALES_ROLES,
	     [("Invoice", "name", "Link", 140, "Sales Invoice"),
	      ("Date", "posting_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 160),
	      ("Net Total", "base_net_total", "Currency", 120),
	      ("Tax", "base_total_taxes_and_charges", "Currency", 110),
	      ("Grand Total", "base_grand_total", "Currency", 130),
	      ("Outstanding", "outstanding_amount", "Currency", 120)],
	     """
		select si.name, si.posting_date, si.branch, si.customer_name, si.base_net_total,
		       si.base_total_taxes_and_charges, si.base_grand_total, si.outstanding_amount
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		order by si.posting_date desc, si.name desc
	     """, alias="si", date_field="si.posting_date"),

	spec(13, "IMEI Sales Register", "A3 Retail Sales", "Sales Invoice", ACCOUNTS_ROLES,
	     [("IMEI / Serial", "serial_no", "Link", 150, "Serial No"),
	      ("Item", "item_code", "Link", 170, "Item"),
	      ("Invoice", "parent", "Link", 140, "Sales Invoice"),
	      ("Date", "posting_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 160),
	      ("Rate", "rate", "Currency", 110)],
	     """
		select sbe.serial_no, sii.item_code, si.name as parent, si.posting_date, si.branch,
		       si.customer_name, sii.rate
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		join `tabSerial and Batch Bundle` sbb on sbb.name = sii.serial_and_batch_bundle
		join `tabSerial and Batch Entry` sbe on sbe.parent = sbb.name
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		union all
		select sii.serial_no, sii.item_code, si.name as parent, si.posting_date, si.branch,
		       si.customer_name, sii.rate
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.is_return = 0 and ifnull(sii.serial_no, '') != ''
		  {conditions}
		order by 4 desc
	     """, alias="si", date_field="si.posting_date"),

	spec(14, "Offer Effectiveness", "A3 Retail Sales", "Seasonal Offer Campaign", SALES_ROLES,
	     [("Campaign", "name", "Link", 180, "Seasonal Offer Campaign"),
	      ("Type", "offer_type", "Data", 140),
	      ("Valid From", "valid_from", "Date", 100),
	      ("Valid Upto", "valid_upto", "Date", 100),
	      ("Status", "status", "Data", 110),
	      ("Budget Cap", "budget_cap", "Currency", 120),
	      ("Consumed", "consumed_amount", "Currency", 120),
	      ("Utilisation %", "utilisation", "Percent", 120)],
	     """
		select c.name, c.offer_type, c.valid_from, c.valid_upto, c.status,
		       c.budget_cap, c.consumed_amount
		from `tabSeasonal Offer Campaign` c
		where c.docstatus < 2
		order by c.valid_from desc
	     """, alias="c", filters="none",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c")
	for row in data:
		row["utilisation"] = percent(row.get("consumed_amount"), row.get("budget_cap"))
	return columns, data"""),

	spec(15, "Sales Person Performance", "A3 Retail Sales", "Sales Invoice", SALES_ROLES,
	     [("Sales Person", "sales_person", "Link", 160, "Sales Person"),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Invoices", "invoices", "Int", 90),
	      ("Net Sales", "net_sales", "Currency", 130),
	      ("Average Ticket", "avg_ticket", "Currency", 130),
	      ("Returns", "returns", "Currency", 120)],
	     """
		select st.sales_person, si.branch, count(distinct si.name) as invoices,
		       sum(si.base_net_total * st.allocated_percentage / 100) as net_sales,
		       round(avg(si.base_net_total), 2) as avg_ticket,
		       (select ifnull(sum(abs(r.base_net_total)), 0) from `tabSales Invoice` r
		        join `tabSales Team` rst on rst.parent = r.name
		        where r.docstatus = 1 and r.is_return = 1
		          and rst.sales_person = st.sales_person
		          and r.posting_date between %(from_date)s and %(to_date)s) as returns
		from `tabSales Team` st
		join `tabSales Invoice` si on si.name = st.parent
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by st.sales_person, si.branch
		order by net_sales desc
	     """, alias="si", date_field="si.posting_date"),

	spec(16, "Exchange Register", "A3 Retail Sales", "Device Exchange", ACCOUNTS_ROLES,
	     [("Exchange", "name", "Link", 140, "Device Exchange"),
	      ("Date", "exchange_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer", "Link", 150, "Customer"),
	      ("Old Device", "old_model", "Data", 150),
	      ("IMEI", "old_imei", "Data", 130),
	      ("Grade", "grade", "Data", 80),
	      ("Value", "final_exchange_value", "Currency", 120),
	      ("Resale Status", "resale_status", "Data", 130)],
	     """
		select x.name, x.exchange_date, x.branch, x.customer, x.old_model, x.old_imei,
		       x.grade, x.final_exchange_value, x.resale_status
		from `tabDevice Exchange` x
		where x.docstatus = 1 {conditions}
		order by x.exchange_date desc
	     """, alias="x", date_field="x.exchange_date"),

	spec(17, "Hourly POS Sales Heatmap", "A3 Retail Sales", "Sales Invoice", SALES_ROLES,
	     [("Hour", "hour", "Data", 100),
	      ("Branch", "branch", "Link", 130, "Branch"),
	      ("Invoices", "invoices", "Int", 100),
	      ("Sales", "sales", "Currency", 130),
	      ("Average Ticket", "avg_ticket", "Currency", 130)],
	     """
		select lpad(hour(si.posting_time), 2, '0') as hour, si.branch,
		       count(*) as invoices, sum(si.base_grand_total) as sales,
		       round(avg(si.base_grand_total), 2) as avg_ticket
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by hour, si.branch
		order by hour
	     """, alias="si", date_field="si.posting_date"),

	# ------------------------------------------------------------------ finance
	spec(18, "EMI Application Register", "A3 Retail Finance", "EMI Application",
	     ["EMI Coordinator"] + ACCOUNTS_ROLES,
	     [("Application", "name", "Link", 140, "EMI Application"),
	      ("Date", "application_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer_name", "Data", 150),
	      ("Partner", "finance_partner", "Link", 130, "Finance Partner"),
	      ("Scheme", "emi_scheme", "Link", 150, "EMI Scheme"),
	      ("Loan", "loan_amount", "Currency", 120),
	      ("Status", "status", "Data", 150),
	      ("Coordinator", "coordinator", "Link", 130, "Employee")],
	     """
		select e.name, e.application_date, e.branch, e.customer_name, e.finance_partner,
		       e.emi_scheme, e.loan_amount, e.status, e.coordinator
		from `tabEMI Application` e
		where e.docstatus < 2 {conditions}
		order by e.application_date desc
	     """, alias="e", date_field="e.application_date"),

	spec(19, "EMI Conversion Funnel", "A3 Retail Finance", "EMI Application", ACCOUNTS_ROLES,
	     [("Status", "status", "Data", 180),
	      ("Applications", "applications", "Int", 120),
	      ("Loan Value", "loan_value", "Currency", 140),
	      ("Share %", "share", "Percent", 100)],
	     """
		select e.status, count(*) as applications, sum(e.loan_amount) as loan_value
		from `tabEMI Application` e
		where e.docstatus < 2 {conditions}
		group by e.status
		order by applications desc
	     """, alias="e", date_field="e.application_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="e", date_field="e.application_date")
	total = sum(row.get("applications") or 0 for row in data)
	for row in data:
		row["share"] = percent(row.get("applications"), total)
	return columns, data"""),

	spec(20, "Financier Receivable Ageing", "A3 Retail Finance", "EMI Application",
	     ACCOUNTS_ROLES,
	     [("Partner", "finance_partner", "Link", 160, "Finance Partner"),
	      ("Applications", "applications", "Int", 120),
	      ("Disbursed Value", "disbursed", "Currency", 140),
	      ("0-15 days", "bucket_15", "Currency", 120),
	      ("16-30 days", "bucket_30", "Currency", 120),
	      ("31-60 days", "bucket_60", "Currency", 120),
	      ("60+ days", "bucket_older", "Currency", 120)],
	     """
		select e.finance_partner, count(*) as applications, sum(e.loan_amount) as disbursed,
		       sum(case when datediff(curdate(), e.disbursement_date) <= 15
		                then e.loan_amount else 0 end) as bucket_15,
		       sum(case when datediff(curdate(), e.disbursement_date) between 16 and 30
		                then e.loan_amount else 0 end) as bucket_30,
		       sum(case when datediff(curdate(), e.disbursement_date) between 31 and 60
		                then e.loan_amount else 0 end) as bucket_60,
		       sum(case when datediff(curdate(), e.disbursement_date) > 60
		                then e.loan_amount else 0 end) as bucket_older
		from `tabEMI Application` e
		where e.docstatus = 1 and e.status = 'Disbursed' {conditions}
		group by e.finance_partner
	     """, alias="e", filters="branch"),

	spec(21, "Settlement Reconciliation", "A3 Retail Finance", "Financier Settlement",
	     ACCOUNTS_ROLES,
	     [("Settlement", "name", "Link", 150, "Financier Settlement"),
	      ("Partner", "finance_partner", "Link", 150, "Finance Partner"),
	      ("Period", "period", "Data", 170),
	      ("Gross", "gross_amount", "Currency", 120),
	      ("MDR", "mdr_amount", "Currency", 110),
	      ("Subvention", "subvention_amount", "Currency", 120),
	      ("Expected", "net_expected", "Currency", 120),
	      ("Received", "net_received", "Currency", 120),
	      ("Variance", "variance", "Currency", 110)],
	     """
		select s.name, s.finance_partner,
		       concat(s.from_date, ' to ', s.to_date) as period,
		       s.gross_amount, s.mdr_amount, s.subvention_amount, s.net_expected,
		       s.net_received, s.variance
		from `tabFinancier Settlement` s
		where s.docstatus < 2
		order by s.from_date desc
	     """, alias="s", filters="none"),

	# ----------------------------------------------------------------- warranty
	spec(22, "Warranty Register", "A3 Retail Warranty", "Warranty Registration", SERVICE_ROLES,
	     [("Registration", "name", "Link", 140, "Warranty Registration"),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Customer", "customer", "Link", 150, "Customer"),
	      ("IMEI", "imei_1", "Data", 130),
	      ("Item", "item_name", "Data", 160),
	      ("Purchased", "purchase_date", "Date", 100),
	      ("Brand Expiry", "brand_warranty_expiry", "Date", 110),
	      ("Plan", "ew_plan", "Link", 150, "Extended Warranty Plan"),
	      ("Plan Expiry", "ew_expiry_date", "Date", 110),
	      ("Status", "status", "Data", 130)],
	     """
		select w.name, w.branch, w.customer, w.imei_1, w.item_name, w.purchase_date,
		       w.brand_warranty_expiry, w.ew_plan, w.ew_expiry_date, w.status
		from `tabWarranty Registration` w
		where w.docstatus = 1 {conditions}
		order by w.purchase_date desc
	     """, alias="w", date_field="w.purchase_date"),

	spec(23, "Expiring Warranty Upsell List", "A3 Retail Warranty", "Warranty Registration",
	     ["Telecaller", "Branch Manager", "A3 Retail Admin"],
	     [("Registration", "name", "Link", 140, "Warranty Registration"),
	      ("Customer", "customer", "Link", 150, "Customer"),
	      ("Mobile", "customer_mobile", "Data", 120),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Device", "item_name", "Data", 160),
	      ("Expires", "expiry", "Date", 110),
	      ("Days Left", "days_left", "Int", 100),
	      ("Plan", "ew_plan", "Link", 150, "Extended Warranty Plan")],
	     """
		select w.name, w.customer, w.customer_mobile, w.branch, w.item_name, w.ew_plan,
		       coalesce(w.ew_expiry_date, w.brand_warranty_expiry) as expiry,
		       datediff(coalesce(w.ew_expiry_date, w.brand_warranty_expiry), curdate()) as days_left
		from `tabWarranty Registration` w
		where w.docstatus = 1 and w.status in ('In Warranty', 'In Extended Warranty')
		  {conditions}
		having days_left between 0 and 60
		order by days_left
	     """, alias="w", filters="branch"),

	spec(24, "EW Attach Rate", "A3 Retail Warranty", "Sales Invoice", SALES_ROLES,
	     [("Branch", "branch", "Link", 140, "Branch"),
	      ("Devices Sold", "devices", "Float", 120),
	      ("Plans Sold", "plans", "Float", 110),
	      ("Attach Rate %", "attach_rate", "Percent", 130),
	      ("Plan Revenue", "plan_revenue", "Currency", 130)],
	     """
		select si.branch,
		       sum(case when ifnull(i.a3_is_device, 0) = 1 then sii.qty else 0 end) as devices,
		       sum(case when ifnull(i.a3_is_ew_plan, 0) = 1 then sii.qty else 0 end) as plans,
		       sum(case when ifnull(i.a3_is_ew_plan, 0) = 1 then sii.base_net_amount else 0 end)
		           as plan_revenue
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabItem` i on i.name = sii.item_code
		where si.docstatus = 1 and si.is_return = 0 {conditions}
		group by si.branch
	     """, alias="si", date_field="si.posting_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="si", date_field="si.posting_date")
	for row in data:
		row["attach_rate"] = percent(row.get("plans"), row.get("devices"))
	return columns, data"""),

	spec(25, "Warranty Claim Cost", "A3 Retail Warranty", "Service Job Card", ACCOUNTS_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Warranty Type", "warranty_type", "Data", 170),
	      ("Claims", "claims", "Int", 90),
	      ("Parts Cost", "parts_cost", "Currency", 130),
	      ("Labour Cost", "labour_cost", "Currency", 130),
	      ("Borne by Us", "warranty_borne", "Currency", 130)],
	     """
		select jc.branch, ifnull(jc.warranty_type, 'Not Recorded') as warranty_type,
		       count(*) as claims,
		       sum(jc.parts_total) as parts_cost, sum(jc.labour_total) as labour_cost,
		       sum(jc.warranty_borne_amount) as warranty_borne
		from `tabService Job Card` jc
		where jc.docstatus = 1 and ifnull(jc.warranty_borne_amount, 0) > 0 {conditions}
		group by jc.branch, jc.warranty_type
	     """, alias="jc", date_field="jc.received_on"),

	# ---------------------------------------------------------------- inventory
	spec(26, "Branch Stock Summary", "A3 Retail Operations", "Bin", STORE_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Warehouse", "warehouse", "Link", 180, "Warehouse"),
	      ("Items", "items", "Int", 90),
	      ("Quantity", "qty", "Float", 110),
	      ("Stock Value", "stock_value", "Currency", 140)],
	     """
		select w.custom_branch as branch, b.warehouse, count(distinct b.item_code) as items,
		       sum(b.actual_qty) as qty, sum(b.stock_value) as stock_value
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		where b.actual_qty != 0 {conditions}
		group by w.custom_branch, b.warehouse
		order by stock_value desc
	     """, alias="w", branch_field="custom_branch", filters="branch"),

	spec(27, "Cross-Branch Availability", "A3 Retail Operations", "Bin", STORE_ROLES,
	     [("Item", "item_code", "Link", 180, "Item"),
	      ("Item Name", "item_name", "Data", 200),
	      ("Branch", "branch", "Link", 130, "Branch"),
	      ("Warehouse", "warehouse", "Link", 170, "Warehouse"),
	      ("Available", "actual_qty", "Float", 110),
	      ("Reserved", "reserved_qty", "Float", 110)],
	     """
		select b.item_code, i.item_name, w.custom_branch as branch, b.warehouse,
		       b.actual_qty, b.reserved_qty
		from `tabBin` b
		join `tabWarehouse` w on w.name = b.warehouse
		join `tabItem` i on i.name = b.item_code
		where b.actual_qty > 0 {conditions}
		order by b.item_code, w.custom_branch
	     """, alias="w", branch_field="custom_branch", filters="branch"),

	spec(28, "Stock Transfer Register", "A3 Retail Operations", "Stock Request", STORE_ROLES,
	     [("Request", "name", "Link", 140, "Stock Request"),
	      ("Date", "request_date", "Date", 100),
	      ("From", "source_branch", "Link", 120, "Branch"),
	      ("To", "requesting_branch", "Link", 120, "Branch"),
	      ("Status", "status", "Data", 130),
	      ("Value", "total_value", "Currency", 120),
	      ("Dispatched", "dispatched_on", "Datetime", 140),
	      ("Received", "received_on", "Datetime", 140),
	      ("Transit Days", "transit_days", "Int", 110)],
	     """
		select s.name, s.request_date, s.source_branch, s.requesting_branch, s.status,
		       s.total_value, s.dispatched_on, s.received_on, s.transit_days
		from `tabStock Request` s
		where s.docstatus = 1 {conditions}
		order by s.request_date desc
	     """, alias="s", branch_field="requesting_branch", date_field="s.request_date"),

	spec(29, "Stock Ageing and Dead Stock", "A3 Retail Operations", "Serial No", STORE_ROLES,
	     [("Item", "item_code", "Link", 180, "Item"),
	      ("Warehouse", "warehouse", "Link", 170, "Warehouse"),
	      ("Serial / IMEI", "name", "Link", 150, "Serial No"),
	      ("Received", "received_on", "Date", 110),
	      ("Age (days)", "age_days", "Int", 100),
	      ("Bucket", "bucket", "Data", 110),
	      ("Value", "purchase_rate", "Currency", 120)],
	     """
		select s.item_code, s.warehouse, s.name, date(s.creation) as received_on, s.purchase_rate,
		       datediff(curdate(), date(s.creation)) as age_days,
		       case
		         when datediff(curdate(), date(s.creation)) <= 30 then '0-30 days'
		         when datediff(curdate(), date(s.creation)) <= 60 then '31-60 days'
		         when datediff(curdate(), date(s.creation)) <= 90 then '61-90 days'
		         else '90+ days (dead)' end as bucket
		from `tabSerial No` s
		where s.status = 'Active' and s.warehouse is not null
		order by age_days desc
	     """, alias="s", filters="none"),

	spec(30, "Damage and Loss Register", "A3 Retail Operations", "Stock Damage Report",
	     ACCOUNTS_ROLES,
	     [("Report", "name", "Link", 140, "Stock Damage Report"),
	      ("Date", "report_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Damage Type", "damage_type", "Data", 140),
	      ("Responsibility", "responsibility", "Data", 140),
	      ("Loss Value", "total_value", "Currency", 120),
	      ("Recovered", "recovery_amount", "Currency", 120),
	      ("Status", "status", "Data", 120)],
	     """
		select d.name, d.report_date, d.branch, d.damage_type, d.responsibility,
		       d.total_value, d.recovery_amount, d.status
		from `tabStock Damage Report` d
		where d.docstatus = 1 {conditions}
		order by d.report_date desc
	     """, alias="d", date_field="d.report_date"),

	# ---------------------------------------------------------------------- CRM
	spec(31, "Daily Footfall Register", "A3 Retail Operations", "Branch Visit Log", SALES_ROLES,
	     [("Visit", "name", "Link", 130, "Branch Visit Log"),
	      ("Time", "visit_datetime", "Datetime", 150),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Visitor", "visitor_name", "Data", 150),
	      ("Mobile", "mobile_no", "Data", 110),
	      ("Type", "visitor_type", "Data", 130),
	      ("Purpose", "purpose", "Data", 150),
	      ("Attended By", "attended_by", "Link", 130, "Employee"),
	      ("Outcome", "outcome", "Data", 160),
	      ("Sale Value", "sale_value", "Currency", 120)],
	     """
		select v.name, v.visit_datetime, v.branch, v.visitor_name, v.mobile_no, v.visitor_type,
		       v.purpose, v.attended_by, v.outcome, v.sale_value
		from `tabBranch Visit Log` v
		where 1 = 1 {conditions}
		order by v.visit_datetime desc
	     """, alias="v", date_field="v.visit_datetime"),

	spec(32, "Footfall Conversion Analysis", "A3 Retail Operations", "Branch Visit Log",
	     SALES_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Visits", "visits", "Int", 90),
	      ("Converted", "converted", "Int", 100),
	      ("Lost", "lost", "Int", 90),
	      ("Leads", "leads", "Int", 90),
	      ("Conversion %", "conversion", "Percent", 120),
	      ("Sale Value", "sale_value", "Currency", 130),
	      ("Average Ticket", "avg_ticket", "Currency", 130)],
	     """
		select v.branch, count(*) as visits,
		       sum(case when v.outcome like 'Converted%%' then 1 else 0 end) as converted,
		       sum(case when v.outcome like 'Lost%%' then 1 else 0 end) as lost,
		       sum(case when v.lead is not null then 1 else 0 end) as leads,
		       sum(v.sale_value) as sale_value
		from `tabBranch Visit Log` v
		where 1 = 1 {conditions}
		group by v.branch
	     """, alias="v", date_field="v.visit_datetime",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="v", date_field="v.visit_datetime")
	for row in data:
		row["conversion"] = percent(row.get("converted"), row.get("visits"))
		row["avg_ticket"] = round((row.get("sale_value") or 0) / (row.get("converted") or 1), 2)
	return columns, data"""),

	spec(33, "Helpdesk SLA Compliance", "A3 Retail Operations", "Issue", CARE_ROLES,
	     [("Branch", "branch", "Link", 130, "Branch"),
	      ("Tickets", "tickets", "Int", 90),
	      ("Resolved", "resolved", "Int", 100),
	      ("SLA Failed", "failed", "Int", 100),
	      ("Compliance %", "compliance", "Percent", 120),
	      ("Average Resolution (h)", "avg_hours", "Float", 170)],
	     """
		select i.a3_branch as branch, count(*) as tickets,
		       sum(case when i.status in ('Resolved', 'Closed') then 1 else 0 end) as resolved,
		       sum(case when i.agreement_status = 'Failed' then 1 else 0 end) as failed,
		       round(avg(timestampdiff(hour, i.opening_date, i.sla_resolution_date)), 1) as avg_hours
		from `tabIssue` i
		where 1 = 1 {conditions}
		group by i.a3_branch
	     """, alias="i", branch_field="a3_branch", date_field="i.opening_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="i", branch_field="a3_branch",
	                          date_field="i.opening_date")
	for row in data:
		row["compliance"] = percent((row.get("tickets") or 0) - (row.get("failed") or 0),
		                            row.get("tickets"))
	return columns, data"""),

	spec(34, "Telecalling Productivity", "A3 Retail Communication", "Call Task",
	     ["Telecaller", "Branch Manager", "A3 Retail Admin"],
	     [("Telecaller", "assigned_to", "Link", 150, "Employee"),
	      ("Assigned", "assigned", "Int", 100),
	      ("Called", "called", "Int", 90),
	      ("Connected", "connected", "Int", 100),
	      ("Converted", "converted", "Int", 100),
	      ("Connect %", "connect_rate", "Percent", 110),
	      ("Conversion %", "conversion_rate", "Percent", 120),
	      ("Talk Time (min)", "talk_minutes", "Float", 130)],
	     """
		select c.assigned_to, count(*) as assigned,
		       sum(case when c.call_status != 'Not Called' then 1 else 0 end) as called,
		       sum(case when c.call_status = 'Connected' then 1 else 0 end) as connected,
		       sum(case when c.outcome = 'Converted' then 1 else 0 end) as converted,
		       round(sum(ifnull(c.duration_seconds, 0)) / 60, 1) as talk_minutes
		from `tabCall Task` c
		where 1 = 1 {conditions}
		group by c.assigned_to
		order by converted desc
	     """, alias="c", date_field="c.scheduled_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c", date_field="c.scheduled_date")
	for row in data:
		row["connect_rate"] = percent(row.get("connected"), row.get("called"))
		row["conversion_rate"] = percent(row.get("converted"), row.get("connected"))
	return columns, data"""),

	# ----------------------------------------------------------------------- HR
	spec(35, "Attendance Register", "A3 Retail Operations", "Attendance", HR_ROLES,
	     [("Employee", "employee", "Link", 130, "Employee"),
	      ("Name", "employee_name", "Data", 160),
	      ("Branch", "branch", "Link", 120, "Branch"),
	      ("Present", "present", "Int", 90),
	      ("Half Day", "half_day", "Int", 90),
	      ("Absent", "absent", "Int", 90),
	      ("On Leave", "on_leave", "Int", 90),
	      ("Marked Days", "marked", "Int", 110),
	      ("Attendance %", "attendance_percent", "Percent", 130)],
	     """
		select a.employee, a.employee_name, a.a3_branch as branch,
		       sum(case when a.status = 'Present' then 1 else 0 end) as present,
		       sum(case when a.status = 'Half Day' then 1 else 0 end) as half_day,
		       sum(case when a.status = 'Absent' then 1 else 0 end) as absent,
		       sum(case when a.status = 'On Leave' then 1 else 0 end) as on_leave,
		       count(*) as marked
		from `tabAttendance` a
		where a.docstatus = 1 {conditions}
		group by a.employee, a.employee_name, a.a3_branch
		order by a.employee_name
	     """, alias="a", branch_field="a3_branch", date_field="a.attendance_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="a", branch_field="a3_branch",
	                          date_field="a.attendance_date")
	for row in data:
		effective = (row.get("present") or 0) + (row.get("half_day") or 0) * 0.5
		row["attendance_percent"] = percent(effective, row.get("marked"))
	return columns, data"""),

	spec(36, "Incentive Payout Register", "A3 Retail Operations", "Incentive Calculation Run",
	     HR_ROLES + ["Accounts Manager"],
	     [("Run", "parent", "Link", 140, "Incentive Calculation Run"),
	      ("Scheme", "scheme", "Link", 170, "Employee Incentive Scheme"),
	      ("Employee", "employee", "Link", 130, "Employee"),
	      ("Name", "employee_name", "Data", 150),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Target", "target", "Float", 110),
	      ("Achieved", "achieved", "Float", 110),
	      ("Achievement %", "achievement_percent", "Percent", 130),
	      ("Base", "base_incentive", "Currency", 110),
	      ("Spiff", "spiff_amount", "Currency", 100),
	      ("Clawback", "clawback_amount", "Currency", 110),
	      ("Gates", "gates", "Data", 200),
	      ("Payout", "final_incentive", "Currency", 120)],
	     """
		select i.parent, r.scheme, i.employee, i.employee_name, i.branch, i.target, i.achieved,
		       i.achievement_percent, i.base_incentive, i.spiff_amount, i.clawback_amount,
		       i.final_incentive,
		       case when i.gates_passed = 1 then 'Pass'
		            else concat('Fail — ', ifnull(i.gate_failure_reason, '')) end as gates
		from `tabIncentive Calculation Item` i
		join `tabIncentive Calculation Run` r on r.name = i.parent
		where r.docstatus = 1 {conditions}
		order by i.parent desc, i.final_incentive desc
	     """, alias="r", date_field="r.from_date"),

	spec(37, "Asset Register by Branch", "A3 Retail Operations", "Asset",
	     ["A3 Retail Admin", "Accounts Manager"],
	     [("Asset", "name", "Link", 150, "Asset"),
	      ("Asset Name", "asset_name", "Data", 220),
	      ("Category", "asset_category", "Link", 170, "Asset Category"),
	      ("Branch", "branch", "Link", 120, "Branch"),
	      ("Custodian", "custodian", "Link", 130, "Employee"),
	      ("Since", "custody_since", "Date", 100),
	      ("Purchase Value", "gross_purchase_amount", "Currency", 130),
	      ("Condition", "condition", "Data", 120),
	      ("Calibration Due", "calibration_due", "Date", 130)],
	     """
		select a.name, a.asset_name, a.asset_category, a.a3_branch as branch,
		       a.a3_assigned_employee as custodian, a.a3_custody_since as custody_since,
		       a.gross_purchase_amount, a.a3_asset_condition as `condition`,
		       a.a3_next_calibration_date as calibration_due
		from `tabAsset` a
		where a.docstatus = 1 {conditions}
		order by a.a3_branch, a.asset_name
	     """, alias="a", branch_field="a3_branch", filters="branch"),

	# ------------------------------------------------------------------ accounts
	spec(38, "Branch Profitability Statement", "A3 Retail Operations", "GL Entry",
	     ACCOUNTS_ROLES,
	     [("Branch", "branch", "Link", 140, "Branch"),
	      ("Revenue", "revenue", "Currency", 140),
	      ("Expense", "expense", "Currency", 140),
	      ("Contribution", "contribution", "Currency", 140),
	      ("Margin %", "margin", "Percent", 110)],
	     """
		select gl.branch,
		       sum(case when acc.root_type = 'Income' then gl.credit - gl.debit else 0 end) as revenue,
		       sum(case when acc.root_type = 'Expense' then gl.debit - gl.credit else 0 end) as expense
		from `tabGL Entry` gl
		join `tabAccount` acc on acc.name = gl.account
		where gl.is_cancelled = 0 and acc.root_type in ('Income', 'Expense') {conditions}
		group by gl.branch
	     """, alias="gl", date_field="gl.posting_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="gl", date_field="gl.posting_date")
	for row in data:
		row["contribution"] = (row.get("revenue") or 0) - (row.get("expense") or 0)
		row["margin"] = percent(row["contribution"], row.get("revenue"))
	return columns, data"""),

	spec(39, "RCM Liability and ITC Register", "A3 Retail Operations", "Purchase Invoice",
	     ACCOUNTS_ROLES,
	     [("Invoice", "name", "Link", 150, "Purchase Invoice"),
	      ("Date", "posting_date", "Date", 100),
	      ("Supplier", "supplier_name", "Data", 180),
	      ("Taxable Value", "base_net_total", "Currency", 130),
	      ("RCM Tax", "rcm_tax", "Currency", 120),
	      ("Grand Total", "base_grand_total", "Currency", 130)],
	     """
		select pi.name, pi.posting_date, pi.supplier_name, pi.base_net_total, pi.base_grand_total,
		       (select ifnull(sum(t.base_tax_amount), 0) from `tabPurchase Taxes and Charges` t
		        where t.parent = pi.name and t.add_deduct_tax = 'Add') as rcm_tax
		from `tabPurchase Invoice` pi
		where pi.docstatus = 1 and ifnull(pi.is_reverse_charge, 0) = 1 {conditions}
		order by pi.posting_date desc
	     """, alias="pi", filters="period", date_field="pi.posting_date"),

	spec(40, "Margin Scheme Register", "A3 Retail Operations", "Sales Invoice", ACCOUNTS_ROLES,
	     [("Invoice", "name", "Link", 140, "Sales Invoice"),
	      ("Date", "posting_date", "Date", 100),
	      ("Branch", "branch", "Link", 110, "Branch"),
	      ("Item", "item_code", "Link", 170, "Item"),
	      ("Serial / IMEI", "serial_no", "Data", 140),
	      ("Sale Value", "amount", "Currency", 120),
	      ("Purchase Value", "purchase_value", "Currency", 130),
	      ("Margin", "margin", "Currency", 110)],
	     """
		select si.name, si.posting_date, si.branch, sii.item_code, sii.serial_no,
		       sii.base_net_amount as amount,
		       ifnull(sii.incoming_rate, 0) * sii.stock_qty as purchase_value
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabItem` i on i.name = sii.item_code
		where si.docstatus = 1 and si.is_return = 0 and ifnull(i.a3_is_margin_scheme, 0) = 1
		  {conditions}
		order by si.posting_date desc
	     """, alias="si", date_field="si.posting_date",
	     body="""	columns, data = run_query(COLUMNS, SQL, filters, alias="si", date_field="si.posting_date")
	for row in data:
		row["margin"] = (row.get("amount") or 0) - (row.get("purchase_value") or 0)
	return columns, data"""),

	spec(41, "WhatsApp Delivery Report", "A3 Retail Communication", "WhatsApp Message Log",
	     ["A3 Retail Admin", "Branch Manager"],
	     [("Stream", "stream", "Data", 130),
	      ("Template", "template", "Link", 190, "WhatsApp Template"),
	      ("Sent", "sent", "Int", 90),
	      ("Delivered", "delivered", "Int", 100),
	      ("Read", "read_count", "Int", 90),
	      ("Failed", "failed", "Int", 90),
	      ("Blocked", "blocked", "Int", 90),
	      ("Delivery %", "delivery_rate", "Percent", 110)],
	     """
		select l.stream, l.template, count(*) as sent,
		       sum(case when l.status in ('Delivered', 'Read') then 1 else 0 end) as delivered,
		       sum(case when l.status = 'Read' then 1 else 0 end) as read_count,
		       sum(case when l.status = 'Failed' then 1 else 0 end) as failed,
		       sum(case when l.status like 'Blocked%%' or l.status like 'Held%%' then 1 else 0 end)
		           as blocked
		from `tabWhatsApp Message Log` l
		where 1 = 1 {conditions}
		group by l.stream, l.template
		order by sent desc
	     """, alias="l", date_field="l.creation",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="l", date_field="l.creation")
	for row in data:
		row["delivery_rate"] = percent(row.get("delivered"), row.get("sent"))
	return columns, data"""),

	spec(42, "Courier Cost Analysis", "A3 Retail Operations", "Courier Dispatch",
	     ["A3 Retail Admin", "Branch Manager", "Store Keeper"],
	     [("Partner", "courier_partner", "Link", 160, "Courier Partner"),
	      ("Branch", "branch", "Link", 120, "Branch"),
	      ("Dispatches", "dispatches", "Int", 110),
	      ("Freight", "freight", "Currency", 120),
	      ("Total Cost", "total_cost", "Currency", 120),
	      ("Average Cost", "avg_cost", "Currency", 130),
	      ("Delayed", "delayed_count", "Int", 90),
	      ("On-time %", "on_time_rate", "Percent", 110)],
	     """
		select c.courier_partner, c.branch, count(*) as dispatches,
		       sum(c.freight_amount) as freight, sum(c.total_cost) as total_cost,
		       round(avg(c.total_cost), 2) as avg_cost,
		       sum(case when ifnull(c.delay_days, 0) > 0 then 1 else 0 end) as delayed_count
		from `tabCourier Dispatch` c
		where c.docstatus = 1 {conditions}
		group by c.courier_partner, c.branch
		order by total_cost desc
	     """, alias="c", date_field="c.dispatch_date",
	     body="""	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="c", date_field="c.dispatch_date")
	for row in data:
		row["on_time_rate"] = percent((row.get("dispatches") or 0) - (row.get("delayed_count") or 0),
		                              row.get("dispatches"))
	return columns, data"""),
]


def scrub(name: str) -> str:
	return name.lower().replace(" ", "_").replace("-", "_").replace("&", "and")


def write(path: str, content: str):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w") as handle:
		handle.write(content)


def render_columns(columns) -> str:
	lines = []
	for column in columns:
		label, fieldname, fieldtype, width = column[0], column[1], column[2], column[3]
		options = column[4] if len(column) > 4 else None
		if options:
			lines.append(f'\tcol("{label}", "{fieldname}", "{fieldtype}", {width}, "{options}"),\n')
		else:
			lines.append(f'\tcol("{label}", "{fieldname}", "{fieldtype}", {width}),\n')
	return "".join(lines)


def main():
	print(f"Step 25 — {len(REPORTS)} reports")
	for report in REPORTS:
		folder = os.path.join(APP, MODULE_DIRS[report["module"]], "report", scrub(report["title"]))
		name = scrub(report["title"])

		write(os.path.join(folder, "__init__.py"), "")

		doc = {
			"add_total_row": 0,
			"columns": [],
			"creation": "2026-08-05 09:00:00.000000",
			"disabled": 0,
			"docstatus": 0,
			"doctype": "Report",
			"filters": [],
			"idx": 0,
			"is_standard": "Yes",
			"letter_head": None,
			"modified": "2026-08-05 09:00:00.000000",
			"modified_by": "Administrator",
			"module": report["module"],
			"name": report["title"],
			"owner": "Administrator",
			"prepared_report": 0,
			"ref_doctype": report["ref_doctype"],
			"report_name": report["title"],
			"report_type": "Script Report",
			"roles": [{"role": role} for role in report["roles"]],
		}
		write(os.path.join(folder, f"{name}.json"), json.dumps(doc, indent=1) + "\n")

		template = BRANCH_FILTERS if report["filters"] in ("branch", "none") else PERIOD_FILTERS
		write(
			os.path.join(folder, f"{name}.js"),
			"// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors\n"
			+ template.format(title=report["title"], extra=report["extra_filters"]),
		)

		body = report["body"] or DEFAULT_BODY.format(
			alias=report["alias"], branch_field=report["branch_field"],
			date_field=report["date_field"],
		)
		write(
			os.path.join(folder, f"{name}.py"),
			REPORT_PY.format(
				title=report["title"],
				number=report["number"],
				columns=render_columns(report["columns"]),
				sql=report["sql"],
				body=body,
				extra_imports=report["extra_imports"],
			),
		)
		print(f"  {report['number']:>2}. {report['title']:<38} -> {MODULE_DIRS[report['module']]}")


if __name__ == "__main__":
	main()
