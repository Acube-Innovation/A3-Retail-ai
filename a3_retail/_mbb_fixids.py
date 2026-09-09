"""Post-restructure cleanup.

1. Branch Profile autonames from `field:branch`, but renaming the Branch only
   updated the link — the profile documents kept their old IDs.
2. Branch Profile.on_update stamps `custom_branch` onto its warehouses, and the
   company-wide `Stores - <abbr>` was picked up again while the new branches were
   created, so it claims a branch it does not belong to.
3. Cost centers survive their deleted branches.
"""

import frappe

RENAME_PROFILES = {
    "PhoneXpert Main": "PhoneXpert Accessories PSLA",
    "PhoneXpert Digital Store and Care": "PhoneXpert Accessories UK",
    "PhoneXpert The Digital Store": "PhoneXpert Sales PSLA",
}
DEAD_BRANCHES = ["PhoneXpert Assured", "PhoneXpert BoAt"]


def run():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")

    # --- 1. Branch Profile IDs -------------------------------------------
    print("Branch Profile IDs:")
    for old, new in RENAME_PROFILES.items():
        if not frappe.db.exists("Branch Profile", old):
            print(f"   skip (absent): {old}")
            continue
        if frappe.db.exists("Branch Profile", new):
            print(f"   skip (target exists): {new}")
            continue
        frappe.rename_doc("Branch Profile", old, new, force=True, merge=False)
        print(f"   {old}  ->  {new}")
    frappe.db.commit()

    # --- 2. stray branch stamp on the shared warehouse -------------------
    shared = f"Stores - {abbr}"
    if frappe.db.exists("Warehouse", shared):
        cur = frappe.db.get_value("Warehouse", shared, "custom_branch")
        if cur:
            frappe.db.set_value("Warehouse", shared, "custom_branch", None,
                                update_modified=False)
            print(f"\ncleared stray branch stamp on {shared} (was {cur})")

    # --- 3. leftovers from deleted branches ------------------------------
    print("\nleftovers from deleted branches:")
    for branch in DEAD_BRANCHES:
        for cc in frappe.get_all("Cost Center",
                                 filters={"name": ["like", f"{branch}%"]}, pluck="name"):
            gl = frappe.db.count("GL Entry", {"cost_center": cc})
            if gl:
                print(f"   kept {cc} ({gl} GL entries)")
                continue
            try:
                frappe.delete_doc("Cost Center", cc, force=1, ignore_permissions=True,
                                  delete_permanently=True)
                print(f"   deleted cost center {cc}")
            except Exception as e:
                print(f"   could not delete {cc}: {str(e)[:90]}")
        for wh in frappe.get_all("Warehouse",
                                 filters={"name": ["like", f"{branch}%"]}, pluck="name"):
            sle = frappe.db.count("Stock Ledger Entry", {"warehouse": wh})
            if sle:
                frappe.db.set_value("Warehouse", wh, "disabled", 1, update_modified=False)
                print(f"   kept+disabled {wh} ({sle} ledger entries)")
                continue
            try:
                frappe.delete_doc("Warehouse", wh, force=1, ignore_permissions=True,
                                  delete_permanently=True)
                print(f"   deleted warehouse {wh}")
            except Exception as e:
                print(f"   could not delete {wh}: {str(e)[:90]}")
    frappe.db.commit()

    # --- report -----------------------------------------------------------
    print("\n=== final ===")
    for r in frappe.get_all("Branch Profile",
                            fields=["name", "branch", "branch_code", "default_warehouse",
                                    "cost_center"],
                            order_by="branch_code"):
        ok = "OK " if r.name == r.branch else "BAD"
        print(f"  [{ok}] {r.branch_code:5} ID={r.name[:30]:32} wh={str(r.default_warehouse)[:34]}")
    print("\nBranch docs:", frappe.get_all("Branch", pluck="name", order_by="name"))
