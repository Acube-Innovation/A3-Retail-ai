"""Seed 02 — Branch, Branch Profile x3, warehouses x12, POS Profiles (scope 1.1)."""

import frappe

from a3_retail.setup.accounts import ensure_branch_cost_centers
from a3_retail.utils.gst import normalize_gstin

BRANCHES = [
	{
		"branch": "Kochi",
		"branch_code": "KCH",
		"branch_type": "Sales & Service",
		"is_head_office": 1,
		"default_tat_hours": 48,
		"monthly_sales_target": 1200000,
		"monthly_service_target": 320,
		"daily_footfall_target": 70,
		"manager": "Arun Menon",
		"latitude": 9.9312,
		"longitude": 76.2673,
		"contact_no": "0484 2345678",
		"branch_email": "kochi@mobileworld.in",
	},
	{
		"branch": "Thiruvananthapuram",
		"branch_code": "TVM",
		"branch_type": "Sales & Service",
		"is_head_office": 0,
		"default_tat_hours": 48,
		"monthly_sales_target": 900000,
		"monthly_service_target": 240,
		"daily_footfall_target": 55,
		"manager": "Nikhil Das",
		"latitude": 8.5241,
		"longitude": 76.9366,
		"contact_no": "0471 2345678",
		"branch_email": "tvm@mobileworld.in",
	},
	{
		"branch": "Kozhikode",
		"branch_code": "CLT",
		"branch_type": "Sales Only",
		"is_head_office": 0,
		"default_tat_hours": 72,
		"monthly_sales_target": 750000,
		"monthly_service_target": 0,
		"daily_footfall_target": 45,
		"manager": "Fahad Rahman",
		"latitude": 11.2588,
		"longitude": 75.7804,
		"contact_no": "0495 2345678",
		"branch_email": "calicut@mobileworld.in",
	},
	{"branch": "Head Office", "skip_profile": True},
]

GSTIN = normalize_gstin("32AABCM1234K1Z5")


def run():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw("Run seed 01_company first — no default Company is set.")

	for spec in BRANCHES:
		_ensure_branch(spec["branch"])
		if spec.get("skip_profile"):
			continue
		_ensure_profile(spec, company)


def _ensure_branch(name):
	if not frappe.db.exists("Branch", name):
		doc = frappe.new_doc("Branch")
		doc.branch = name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	return name


def _ensure_profile(spec, company):
	if frappe.db.exists("Branch Profile", {"branch": spec["branch"]}):
		return

	cost_centers = ensure_branch_cost_centers(spec["branch"], company)

	profile = frappe.new_doc("Branch Profile")
	profile.branch = spec["branch"]
	profile.branch_code = spec["branch_code"]
	profile.branch_type = spec["branch_type"]
	profile.is_head_office = spec["is_head_office"]
	profile.company = company
	profile.cost_center = cost_centers["sales"]
	profile.sales_cost_center = cost_centers["sales"]
	profile.service_cost_center = cost_centers["service"]
	profile.gstin = GSTIN
	profile.contact_no = spec["contact_no"]
	profile.branch_email = spec["branch_email"]
	profile.latitude = spec["latitude"]
	profile.longitude = spec["longitude"]
	profile.default_tat_hours = spec["default_tat_hours"]
	profile.working_hours_from = "09:30:00"
	profile.working_hours_to = "20:00:00"
	profile.weekly_off = "Sunday"
	profile.daily_footfall_target = spec["daily_footfall_target"]
	profile.monthly_sales_target = spec["monthly_sales_target"]
	profile.monthly_service_target = spec["monthly_service_target"]

	# The Employee records arrive in seed 03; link the manager if already present.
	manager = frappe.db.get_value("Employee", {"employee_name": spec["manager"]}, "name")
	if manager:
		profile.branch_manager = manager

	profile.flags.ignore_permissions = True
	profile.flags.ignore_mandatory = True
	profile.insert(ignore_permissions=True)
