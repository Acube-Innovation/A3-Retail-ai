# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Environment repair helpers.

These fix conditions that come from a partially-provisioned site rather than
from this app, but they are shipped here so a fresh bench can be brought to a
known-good state with one documented command:

    bench --site <site> execute a3_retail.setup.repair.run

Everything is idempotent.
"""

import frappe


def run():
	install_base_fixtures()
	repair_missing_columns()
	backfill_imei_register()
	frappe.db.commit()


def backfill_imei_register(verbose: bool = False) -> int:
	"""Copy a device serial's name into its IMEI field where it is empty.

	ERPNext creates serial numbers in bulk with `frappe.db.bulk_insert`, which
	skips document hooks — so serials made by a Stock Entry or a Purchase Receipt
	never ran `overrides.serial_no.before_insert` and reached the register with no
	IMEI. Everything that looks a device IMEI up by field (reception, warranty,
	the counter) needs this filled in.
	"""
	if not frappe.db.has_column("Serial No", "a3_imei_1"):
		return 0

	rows = frappe.db.sql(
		"""
		select s.name from `tabSerial No` s
		join `tabItem` i on i.name = s.item_code
		where ifnull(s.a3_imei_1, '') = '' and ifnull(i.a3_is_device, 0) = 1
		  and s.name regexp '^[0-9]{15}$'
		""",
		pluck=True,
	)

	for name in rows:
		frappe.db.set_value("Serial No", name, "a3_imei_1", name, update_modified=False)

	if verbose and rows:
		print(f"filled the IMEI on {len(rows)} serial numbers")
	return len(rows)


def install_base_fixtures():
	"""Create the global masters Frappe/ERPNext expect (Gender, Salutation, UOM...).

	A site whose setup wizard was skipped or interrupted is missing these, which
	breaks unrelated inserts with `LinkValidationError: Could not find Gender`.
	"""
	from frappe.desk.page.setup_wizard.install_fixtures import install

	try:
		install()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: base fixture install failed")
		raise

	# ERPNext's own defaults (Item Group tree, UOMs, Warehouse Types, ...).
	try:
		from erpnext.setup.install import after_install as erpnext_after_install

		erpnext_after_install()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: erpnext fixture install failed")


def repair_missing_columns(verbose: bool = True) -> list[tuple[str, list[str]]]:
	"""Recreate DB columns for Custom Fields whose ALTER TABLE never ran.

	Symptom: `Unknown column '<fieldname>' in 'INSERT INTO'` on a doctype that
	clearly has the field in its meta. Happens when an app was installed while
	the schema sync was interrupted.
	"""
	repaired = []
	for dt in frappe.get_all("Custom Field", pluck="dt", distinct=True):
		try:
			meta = frappe.get_meta(dt)
			if meta.issingle:
				continue
			columns = {c["Field"] for c in frappe.db.sql(f"SHOW COLUMNS FROM `tab{dt}`", as_dict=True)}
		except Exception:
			continue

		missing = [
			df.fieldname
			for df in meta.fields
			if df.fieldname not in columns and df.fieldtype not in frappe.model.no_value_fields
		]
		if missing:
			frappe.db.updatedb(dt)
			repaired.append((dt, missing))
			if verbose:
				print(f"repaired {dt}: {missing}")

	if verbose:
		print(f"total doctypes repaired: {len(repaired)}")
	return repaired
