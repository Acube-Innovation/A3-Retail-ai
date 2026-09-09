"""Opening stock load: myBillBook quantities -> ERPNext, per branch warehouse.

    bench --site retail execute a3_retail._mbb_stock.merge_items   # step 1
    bench --site retail execute a3_retail._mbb_stock.run           # step 2

Deliberate exclusions, each reported in the summary:

* **SCHEMES** — manufacturer rebate records booked as items. Six rows carrying
  8,516 units each at purchase prices up to Rs 8,173, which is 88.8% of the
  Digital Store's book stock value. They are not physical inventory.
* **Negative quantities** — ERPNext cannot open a stock position below zero.
* **Items with no valuation basis** — no purchase price, MRP or selling price.

Valuation falls back purchase price -> MRP -> selling price, and the source used
is recorded per line in the CSV report.
"""

import csv
import json
import re

import frappe

DATA = "/home/acubeadmin/Projects/A3-retail/migration-data"
FALLBACK_GROUP = "Uncategorised"
UOM = "Nos"
EXCLUDE_CATEGORIES = {"SCHEMES"}

# myBillBook company_id prefix -> ERPNext Branch
BIZ = {
    "ac5e07a5": "PhoneXpert Main",
    "2e7704a6": "PhoneXpert Distribution",
    "356e948f": "PhoneXpert The Digital Store",
    "21c71d2c": "PhoneXpert Assured",
    "dc468420": "PhoneXpert BoAt",
    "8e17035d": "PhoneXpert Digital Store and Care",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _valuation(r):
    """(rate, source) — purchase price, then MRP, then selling price."""
    pp = (r.get("purchase_info") or {}).get("price_per_unit") or 0
    if pp:
        return float(pp), "purchase_price"
    if r.get("mrp"):
        return float(r["mrp"]), "mrp"
    sp = (r.get("sales_info") or {}).get("price_per_unit") or 0
    if sp:
        return float(sp), "selling_price"
    return 0.0, "none"


def _name_index():
    """Uppercased item_name -> item_code, for matching across businesses."""
    idx = {}
    for row in frappe.get_all("Item", fields=["name", "item_name"], limit_page_length=0):
        idx.setdefault(_norm(row.item_name).upper(), row.name)
    return idx


def merge_items():
    """Create Items that exist in businesses 2-6 but not yet in ERPNext."""
    idx = _name_index()
    print(f"existing items indexed: {len(idx)}")

    hsn_orig = frappe.db.get_single_value("GST Settings", "validate_hsn_code")
    frappe.db.set_single_value("GST Settings", "validate_hsn_code", 0)
    frappe.clear_document_cache("GST Settings", "GST Settings")
    frappe.db.commit()

    made = skipped = failed = 0
    made_groups = 0
    try:
        for cid, branch in BIZ.items():
            rows = json.load(open(f"{DATA}/biz_{cid}_items.json"))
            for r in rows:
                nm = _norm(r.get("name"))
                if not nm:
                    continue
                key = nm.upper()
                if key in idx:
                    skipped += 1
                    continue
                group = _norm(r.get("item_category_name")) or FALLBACK_GROUP
                frappe.db.savepoint("mbb_mi")
                try:
                    if not frappe.db.exists("Item Group", group):
                        g = frappe.new_doc("Item Group")
                        g.item_group_name = group
                        g.parent_item_group = "All Item Groups"
                        g.is_group = 0
                        g.flags.ignore_permissions = True
                        g.insert(ignore_permissions=True)
                        made_groups += 1

                    code = key[:120]
                    n = 1
                    while frappe.db.exists("Item", code):
                        n += 1
                        code = f"{key[:116]}-{n}"

                    doc = frappe.new_doc("Item")
                    doc.item_code = code
                    doc.item_name = nm[:140]
                    doc.item_group = group
                    doc.stock_uom = UOM
                    doc.is_stock_item = 1
                    doc.is_purchase_item = 1
                    doc.is_sales_item = 1
                    doc.include_item_in_manufacturing = 0
                    hsn = _norm(r.get("identification_code"))
                    if hsn and frappe.db.exists("GST HSN Code", hsn):
                        doc.gst_hsn_code = hsn
                    doc.flags.ignore_permissions = True
                    doc.insert(ignore_permissions=True)
                    idx[key] = doc.name
                    made += 1
                except Exception as e:
                    failed += 1
                    frappe.db.rollback(save_point="mbb_mi")
            frappe.db.commit()
            print(f"  {branch[:34]:36} scanned {len(rows):5}  total new so far {made}")
    finally:
        frappe.db.set_single_value("GST Settings", "validate_hsn_code", hsn_orig)
        frappe.clear_document_cache("GST Settings", "GST Settings")
        frappe.db.commit()

    print(f"\n  item groups created : {made_groups}")
    print(f"  items created       : {made}")
    print(f"  already present     : {skipped}")
    print(f"  failed              : {failed}")
    print(f"  TOTAL Item          : {frappe.db.count('Item')}")


def run(posting_date=None, batch=150):
    """Post one or more Stock Reconciliations per branch."""
    posting_date = posting_date or frappe.utils.today()
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    expense = f"Temporary Opening - {abbr}"
    if not frappe.db.exists("Account", expense):
        expense = f"Stock Adjustment - {abbr}"
    if not frappe.db.exists("Account", expense):
        frappe.throw("No Temporary Opening / Stock Adjustment account found")

    idx = _name_index()
    report, excluded = [], []
    docs_made = 0

    for cid, branch in BIZ.items():
        wh = frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")
        if not wh:
            print(f"  !! no store warehouse for {branch}, skipped")
            continue

        rows = json.load(open(f"{DATA}/biz_{cid}_items.json"))
        lines = {}
        for r in rows:
            qty = float(r.get("quantity") or 0)
            nm = _norm(r.get("name"))
            cat = (_norm(r.get("item_category_name")) or "").upper()
            code = idx.get(nm.upper())

            if qty <= 0:
                if qty < 0:
                    excluded.append((branch, nm, qty, "", "negative quantity"))
                continue
            if cat in EXCLUDE_CATEGORIES:
                excluded.append((branch, nm, qty, cat, "excluded category (not physical stock)"))
                continue
            if not code:
                excluded.append((branch, nm, qty, cat, "no matching Item"))
                continue
            rate, src = _valuation(r)
            if not rate:
                excluded.append((branch, nm, qty, cat, "no valuation basis"))
                continue

            if code in lines:      # same item twice in one business -> sum
                prev = lines[code]
                lines[code] = (prev[0] + qty, prev[1], prev[2])
            else:
                lines[code] = (qty, rate, src)

        if not lines:
            print(f"  {branch[:34]:36} nothing to post")
            continue

        items = list(lines.items())
        for i in range(0, len(items), batch):
            chunk = items[i:i + batch]
            sr = frappe.new_doc("Stock Reconciliation")
            sr.company = company
            sr.purpose = "Opening Stock"
            sr.posting_date = posting_date
            sr.set_posting_time = 1
            sr.expense_account = expense
            for code, (qty, rate, src) in chunk:
                sr.append("items", {"item_code": code, "warehouse": wh,
                                    "qty": qty, "valuation_rate": rate})
            sr.flags.ignore_permissions = True
            sr.insert(ignore_permissions=True)
            sr.submit()
            docs_made += 1
            frappe.db.commit()
            for code, (qty, rate, src) in chunk:
                report.append((branch, wh, code, qty, rate, src, sr.name))
            print(f"  {branch[:30]:32} {sr.name}  lines={len(chunk)}")

    with open(DATA + "/opening_stock_posted.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["branch", "warehouse", "item_code", "qty", "valuation_rate",
                    "valuation_source", "stock_reco"])
        w.writerows(report)
    with open(DATA + "/opening_stock_excluded.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["branch", "item_name", "qty", "category", "reason"])
        w.writerows(excluded)

    value = sum(r[3] * r[4] for r in report)
    print("\n" + "=" * 62)
    print(f"  posting date          : {posting_date}")
    print(f"  Stock Reconciliations : {docs_made}")
    print(f"  lines posted          : {len(report)}")
    print(f"  opening stock value   : {value:,.2f}")
    print(f"  lines excluded        : {len(excluded)}")
    import collections
    for reason, n in collections.Counter(e[4] for e in excluded).most_common():
        print(f"      {n:5}  {reason}")
    print("=" * 62)
