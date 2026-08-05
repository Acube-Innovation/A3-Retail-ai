# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Demo dataset runner (scope 14.2).

Seed scripts live beside this file, named `NN_topic.py`, and are executed in
numeric order. The numeric prefix matches the seed-order table in the scope
document, so they are loaded by path rather than imported by name (a module
cannot start with a digit).

    bench --site <site> execute a3_retail.demo.install.run
    bench --site <site> execute a3_retail.demo.install.wipe     # dev only
    bench --site <site> execute a3_retail.demo.install.verify
"""

import importlib.util
import os
import re
import time

import frappe

SEED_PATTERN = re.compile(r"^(\d{2})_([a-z0-9_]+)\.py$")


def _seed_scripts() -> list[tuple[str, str, str]]:
	"""[(order, name, path)] sorted by the numeric prefix."""
	folder = os.path.dirname(os.path.abspath(__file__))
	scripts = []
	for filename in os.listdir(folder):
		match = SEED_PATTERN.match(filename)
		if match:
			scripts.append((match.group(1), match.group(2), os.path.join(folder, filename)))
	return sorted(scripts, key=lambda row: row[0])


def _load(path: str, name: str):
	spec = importlib.util.spec_from_file_location(f"a3_retail.demo.seed_{name}", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def run(only: str | None = None, verbose: bool = True):
	"""Run every seed script in order. Safe to re-run — each script is idempotent."""
	# The scope document's sample IMEIs are illustrative and do not satisfy Luhn,
	# so demo seeding uses the documented override path (scope 1.2).
	frappe.flags.a3_bypass_imei_check = True
	frappe.flags.in_demo_install = True

	scripts = _seed_scripts()
	if only:
		scripts = [s for s in scripts if s[0] == only or s[1] == only]
		if not scripts:
			frappe.throw(f"No demo seed script matches {only!r}")

	results = []
	for order, name, path in scripts:
		started = time.time()
		module = _load(path, name)
		if not hasattr(module, "run"):
			continue
		try:
			module.run()
			frappe.db.commit()
			status = "ok"
		except Exception:
			frappe.db.rollback()
			status = "FAILED"
			frappe.log_error(frappe.get_traceback(), f"A3 demo seed {order}_{name}")
			if verbose:
				print(f"  {order}_{name}: FAILED\n{frappe.get_traceback()}")
		elapsed = time.time() - started
		results.append((f"{order}_{name}", status, round(elapsed, 2)))
		if verbose and status == "ok":
			print(f"  {order}_{name}: ok ({elapsed:.2f}s)")

	settings = frappe.get_single("A3 Retail Settings")
	settings.demo_data_installed = 1
	settings.demo_data_installed_on = frappe.utils.now()
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.flags.a3_bypass_imei_check = False
	frappe.flags.in_demo_install = False

	failed = [r for r in results if r[1] != "ok"]
	if verbose:
		print(f"\n{len(results) - len(failed)}/{len(results)} demo scripts succeeded")
	return results


def wipe():
	"""Delete demo transactions. Refuses to run outside developer mode."""
	if not frappe.conf.get("developer_mode"):
		frappe.throw("demo.wipe is only allowed with developer_mode = 1")

	from a3_retail.demo import wipe as wipe_module

	wipe_module.run()


def verify():
	from a3_retail.demo import verify as verify_module

	return verify_module.run()
