"""One-off tenant load: PhoneXpert myBillBook item masters -> ERPNext.

Not registered in patches.txt and not imported by hooks — it only runs when
called explicitly. Idempotent: item codes are derived deterministically from the
sorted source list, so a re-run skips whatever it already created.

    bench --site retail execute a3_retail._mbb_import.run

Stock quantities are deliberately NOT loaded here.
"""

import csv
import json
import re

import frappe

SCRATCH = "/home/acubeadmin/Projects/A3-retail/migration-data"
SRC = SCRATCH + "/items_clean.json"
UOM = "Nos"                      # myBillBook records everything as "PCS"
FALLBACK_GROUP = "Uncategorised"
PRICE_LIST = "Standard Selling"


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _load():
    items = json.load(open(SRC))
    items.sort(key=lambda r: (_norm(r.get("name")).upper(), r["id"]))
    return items


def _ensure_groups(items):
    made = 0
    for g in sorted({_norm(r.get("item_category_name")) or FALLBACK_GROUP for r in items}):
        if frappe.db.exists("Item Group", g):
            continue
        doc = frappe.new_doc("Item Group")
        doc.item_group_name = g
        doc.parent_item_group = "All Item Groups"
        doc.is_group = 0
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        made += 1
    frappe.db.commit()
    return made


def _plan(items):
    """Deterministic item_code per source row; duplicates get a numeric suffix."""
    seen, plan = {}, []
    for r in items:
        name = _norm(r["name"])
        base = name.upper()[:120] or "ITEM"
        seen[base] = seen.get(base, 0) + 1
        code = base if seen[base] == 1 else f"{base}-{seen[base]}"
        plan.append((code, name, r))
    return plan


def _write_reports(plan):
    with open(SCRATCH + "/item_id_map.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mybillbook_id", "erpnext_item_code", "item_name", "category",
                    "gst_pct", "tax_included", "sell_price", "mrp",
                    "qty_in_mbb", "batch_tracked"])
        for code, name, r in plan:
            si = r.get("sales_info") or {}
            w.writerow([r["id"], code, name, r.get("item_category_name") or "",
                        si.get("gst_percentage"), si.get("is_tax_included"),
                        si.get("price_per_unit"), r.get("mrp"), r.get("quantity"),
                        r.get("item_attribute") == "batch"])

    cats = {}
    for code, name, r in plan:
        g = _norm(r.get("item_category_name")) or FALLBACK_GROUP
        d = cats.setdefault(g, {"n": 0, "gst": set(), "eg": []})
        d["n"] += 1
        d["gst"].add((r.get("sales_info") or {}).get("gst_percentage"))
        if len(d["eg"]) < 3:
            d["eg"].append(name)

    with open(SCRATCH + "/hsn_worksheet.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_group", "item_count", "gst_pct_in_mybillbook",
                    "example_items", "HSN_CODE_TO_FILL"])
        for g in sorted(cats):
            d = cats[g]
            rates = sorted(d["gst"], key=lambda v: (v is None, v))
            w.writerow([g, d["n"], "/".join(str(x) for x in rates),
                        " | ".join(d["eg"]), ""])


def run():
    items = _load()
    made_groups = _ensure_groups(items)
    plan = _plan(items)

    bc_used = set()
    made_items = made_prices = skipped = failed = 0
    errors = []

    # india_compliance refuses any sales Item without an HSN code. myBillBook holds
    # almost none, and inventing them would misstate the client's GST liability, so
    # the check is suspended for the load and restored in the finally block.
    hsn_orig = frappe.db.get_single_value("GST Settings", "validate_hsn_code")
    frappe.db.set_single_value("GST Settings", "validate_hsn_code", 0)
    frappe.clear_document_cache("GST Settings", "GST Settings")
    frappe.db.commit()
    print(f"HSN validation suspended for load (was {hsn_orig})")

    try:
        for i, (code, name, r) in enumerate(plan, 1):
            # Scope the undo to this record; a bare rollback() would discard every
            # insert since the last commit.
            frappe.db.savepoint("mbb_item")
            try:
                if frappe.db.exists("Item", code):
                    skipped += 1
                else:
                    doc = frappe.new_doc("Item")
                    doc.item_code = code
                    doc.item_name = name[:140]
                    doc.item_group = _norm(r.get("item_category_name")) or FALLBACK_GROUP
                    doc.stock_uom = UOM
                    doc.is_stock_item = 1
                    doc.is_purchase_item = 1
                    doc.is_sales_item = 1
                    doc.include_item_in_manufacturing = 0
                    if r.get("minimum_quantity"):
                        doc.safety_stock = r["minimum_quantity"]
                    if r.get("description"):
                        doc.description = _norm(r["description"])[:500]

                    sku = (r.get("sku_code") or "").strip()
                    if (sku and sku not in bc_used
                            and not frappe.db.exists("Item Barcode", {"barcode": sku})):
                        doc.append("barcodes", {"barcode": sku})
                        bc_used.add(sku)

                    doc.flags.ignore_permissions = True
                    doc.insert(ignore_permissions=True)
                    made_items += 1

                rate = (r.get("sales_info") or {}).get("price_per_unit") or 0
                if rate and not frappe.db.exists(
                        "Item Price", {"item_code": code, "price_list": PRICE_LIST}):
                    ip = frappe.new_doc("Item Price")
                    ip.item_code = code
                    ip.price_list = PRICE_LIST
                    ip.price_list_rate = rate
                    ip.flags.ignore_permissions = True
                    ip.insert(ignore_permissions=True)
                    made_prices += 1

            except Exception as e:
                failed += 1
                errors.append({"code": code, "name": name, "error": str(e)[:200]})
                frappe.db.rollback(save_point="mbb_item")

            if i % 200 == 0:
                frappe.db.commit()
                print(f"  ... {i}/{len(plan)}")
    finally:
        frappe.db.set_single_value("GST Settings", "validate_hsn_code", hsn_orig)
        frappe.clear_document_cache("GST Settings", "GST Settings")
        frappe.db.commit()
        print(f"HSN validation restored to {hsn_orig}")

    _write_reports(plan)
    if errors:
        json.dump(errors, open(SCRATCH + "/import_errors.json", "w"), indent=1)

    print("\n" + "=" * 52)
    print(f"  item groups created : {made_groups}")
    print(f"  items created       : {made_items}")
    print(f"  items skipped       : {skipped}  (already existed)")
    print(f"  item prices created : {made_prices}")
    print(f"  failed              : {failed}")
    print(f"  TOTAL Item in site  : {frappe.db.count('Item')}")
    print("=" * 52)
