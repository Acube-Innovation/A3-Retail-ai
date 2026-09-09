"""Reconcile the myBillBook load against source, and rebuild the report CSVs.

The loader wrote its balance report from only the records it created in that
run, so a resumed load produced a partial file. This rebuilds every report from
the source data joined to the database, independent of how many runs it took.

    bench --site retail execute a3_retail._mbb_reconcile.run
"""

import csv
import json

import frappe

DATA = "/home/acubeadmin/Projects/A3-retail/migration-data"


def run():
    parties = [r for r in json.load(open(DATA + "/parties_raw.json")) if not r.get("is_deleted")]
    items = json.load(open(DATA + "/items_clean.json"))

    # ---------------------------------------------------------------- parties
    missing, balances = [], []
    for r in parties:
        dt = "Supplier" if r.get("company_contact_type") == "supplier" else "Customer"
        name = frappe.db.get_value(dt, {"mbb_id": r["id"]}, "name")
        if not name:
            missing.append((r["id"], dt, (r.get("name") or "").strip()))
            continue
        bal = float(r.get("balance") or 0)
        if bal:
            balances.append((r["id"], dt, name, (r.get("name") or "").strip(),
                             (r.get("mobile_number") or "").strip(), bal))

    with open(DATA + "/party_opening_balances.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mybillbook_id", "doctype", "erpnext_name", "party_name",
                    "mobile", "balance_in_mybillbook"])
        w.writerows(sorted(balances, key=lambda x: -abs(x[5])))

    recv = sum(b[5] for b in balances if b[5] > 0)
    pay = sum(b[5] for b in balances if b[5] < 0)

    # ------------------------------------------------------------------ items
    item_missing = []
    for r in items:
        if not frappe.db.exists("Item Price", {"item_code": None}):
            pass
    mapped = frappe.db.count("Item")

    print("=" * 58)
    print("PARTIES")
    print(f"  source (live)        : {len(parties)}")
    print(f"  in ERPNext           : {len(parties) - len(missing)}")
    print(f"  MISSING              : {len(missing)}")
    print(f"  Customer rows        : {frappe.db.count('Customer')}")
    print(f"  Supplier rows        : {frappe.db.count('Supplier')}")
    print(f"  Contact rows         : {frappe.db.count('Contact')}")
    print(f"  Address rows         : {frappe.db.count('Address')}")
    print("\nBALANCES (recorded, NOT posted)")
    print(f"  parties w/ balance   : {len(balances)}")
    print(f"  receivable total     : {recv:,.2f}   (myBillBook 'To Collect' 39,385.00)")
    print(f"  payable total        : {abs(pay):,.2f}   (myBillBook 'To Pay'    12,981.00)")
    print(f"  match receivable     : {abs(recv - 39385.0) < 0.01}")
    print(f"  match payable        : {abs(abs(pay) - 12981.0) < 0.01}")
    print("\nITEMS")
    print(f"  source               : {len(items)}")
    print(f"  Item rows            : {mapped}")
    print(f"  Item Price rows      : {frappe.db.count('Item Price')}")
    print(f"  items without HSN    : "
          f"{frappe.db.sql('select count(*) from `tabItem` where gst_hsn_code is null')[0][0]}")
    print("=" * 58)

    if missing:
        with open(DATA + "/party_missing.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["mybillbook_id", "doctype", "party_name"])
            w.writerows(missing)
        print(f"\n{len(missing)} missing parties written to party_missing.csv")
