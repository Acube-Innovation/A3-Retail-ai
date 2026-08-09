# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Nine role workspaces become one: A3 Retail Home.

Sites installed before this carry A3 Service, A3 Sales, A3 Branch Manager, A3
Inventory, A3 Finance, A3 HR, A3 Customer Care and A3 Management. Everything
they held is now a section on A3 Retail Home, so they are rebuilt into the one
page and then removed.
"""

import frappe

from a3_retail.setup import dashboards


def execute():
	if not frappe.db.exists("Workspace", dashboards.WORKSPACE):
		# A fresh site gets the workspace from the installer instead.
		dashboards.ensure_number_cards()
		dashboards.ensure_dashboard_charts()

	dashboards.ensure_workspaces()
	removed = dashboards.retire_workspaces()

	if removed:
		print(f"A3 Retail Home now carries: {', '.join(removed)}")
