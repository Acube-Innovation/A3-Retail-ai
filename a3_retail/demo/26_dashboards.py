"""Seed 26 — dashboards, reports and the scheduled deliveries (scope 14.2).

These are configuration rather than data, so the seed simply calls the same
setup routines a fresh install runs. It exists so the demo order table in the
scope is complete and `demo.install.run` on an empty site ends with a desk that
already has its cards, charts, workspaces and report schedule.
"""

import frappe

from a3_retail.setup import dashboards, print_formats, reports


def run():
	print_formats.run()
	dashboards.run()
	reports.run()
	frappe.clear_cache()
