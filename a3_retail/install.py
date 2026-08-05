# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Install-time hooks.

`before_install` runs *before* the DocType sync, which is the only safe place to
create the Roles that our DocType permission rows link to — a missing Role makes
`sync_for()` fail with a link validation error on a fresh site.
"""

import frappe

# Roles from scope 13.2. "System Manager" ships with Frappe and is not recreated.
A3_ROLES = [
	{"role_name": "A3 Retail Admin", "desk_access": 1},
	{"role_name": "Branch Manager", "desk_access": 1},
	{"role_name": "Service Manager", "desk_access": 1},
	{"role_name": "Sales Executive", "desk_access": 1},
	{"role_name": "Reception Executive", "desk_access": 1},
	{"role_name": "Technician", "desk_access": 1},
	{"role_name": "Store Keeper", "desk_access": 1},
	{"role_name": "EMI Coordinator", "desk_access": 1},
	{"role_name": "Accounts Manager", "desk_access": 1},
	{"role_name": "Accounts Executive", "desk_access": 1},
	{"role_name": "HR Manager", "desk_access": 1},
	{"role_name": "Telecaller", "desk_access": 1},
	{"role_name": "Helpdesk Agent", "desk_access": 1},
	{"role_name": "Auditor", "desk_access": 1},
]


def create_roles():
	"""Idempotently create the A3 Retail roles."""
	for role in A3_ROLES:
		if frappe.db.exists("Role", role["role_name"]):
			continue
		doc = frappe.new_doc("Role")
		doc.update(role)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def before_install():
	create_roles()
	frappe.db.commit()


def after_install():
	from a3_retail.setup.install_defaults import run as install_defaults

	create_roles()
	install_defaults()
	frappe.db.commit()


def after_migrate():
	"""Keep roles and defaults in sync on every `bench migrate`."""
	from a3_retail.setup.install_defaults import run as install_defaults

	create_roles()
	install_defaults()


def before_tests():
	"""Prepare the site for `bench run-tests --app a3_retail`.

	`skip_test_records` stops Frappe from auto-creating ERPNext's `_Test *`
	dependency records for every link field it finds on our doctypes. Those
	records predate india_compliance and are rejected by its GST validation
	("GST Rate cannot be zero for Taxable"), which would fail the suite before a
	single assertion runs. Our tests build the fixtures they need instead.
	"""
	from a3_retail.setup.company import run as setup_company
	from a3_retail.setup.install_defaults import run as install_defaults

	frappe.flags.skip_test_records = True

	create_roles()
	setup_company()
	install_defaults()
	frappe.db.commit()
