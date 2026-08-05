"""Demo dataset seeding (scope doc 14).

Every script is idempotent and guarded with `frappe.db.exists`. Dates are always
computed relative to today so the demo looks current whenever it is installed.
Run with:  bench --site <site> execute a3_retail.demo.install.run
"""
