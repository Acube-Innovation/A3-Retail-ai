"""Restructure PhoneXpert from the six myBillBook-derived branches into the
seven branches the client actually operates.

Run in order:

    bench --site retail execute a3_retail._mbb_restructure.phase_a_stock
    bench --site retail execute a3_retail._mbb_restructure.phase_b_branches
    bench --site retail execute a3_retail._mbb_restructure.phase_c_parties
    bench --site retail execute a3_retail._mbb_restructure.phase_d_categories
    bench --site retail execute a3_retail._mbb_restructure.verify
"""

import json

import frappe

DATA = "/home/acubeadmin/Projects/A3-retail/migration-data"

# old branch -> (new branch, new code, branch_type)
RENAME = {
    "PhoneXpert Main":                   ("PhoneXpert Accessories PSLA", "ACP", "Sales Only"),
    "PhoneXpert Digital Store and Care": ("PhoneXpert Accessories UK",   "ACU", "Sales Only"),
    "PhoneXpert The Digital Store":      ("PhoneXpert Sales PSLA",       "SLP", "Sales Only"),
    "PhoneXpert Distribution":           ("PhoneXpert Distribution",     "DIST", "Sales Only"),
}

NEW_BRANCHES = [
    ("PhoneXpert Sales UK",     "SLU", "Sales Only"),
    ("PhoneXpert Services PSLA", "SVP", "Service Only"),
    ("PhoneXpert Services UK",  "SVU", "Service Only"),
]

# branches whose posted stock must be removed entirely
CLEAR_STOCK = ["PhoneXpert Main", "PhoneXpert Digital Store and Care", "PhoneXpert Assured"]

# branch to fold into Distribution, then delete
MERGE_INTO_DIST = "PhoneXpert BoAt"
DELETE_BRANCHES = ["PhoneXpert Assured", "PhoneXpert BoAt"]

# myBillBook company_id prefix -> the branch its parties belong to
PARTY_SOURCE = {
    "8e17035d": "PhoneXpert Accessories UK",   # Digital Store & Care
    "356e948f": "PhoneXpert Sales PSLA",       # The Digital store
}
DUPLICATE_TO = {"356e948f": "PhoneXpert Sales UK"}   # same parties, second copy


def _wh(branch):
    return frappe.db.get_value("Branch Profile", {"branch": branch}, "default_warehouse")


def _recos_for(warehouse):
    return frappe.db.sql_list("""
        select distinct sri.parent from `tabStock Reconciliation Item` sri
        join `tabStock Reconciliation` sr on sr.name = sri.parent
        where sri.warehouse = %s and sr.docstatus = 1
    """, warehouse)


# ---------------------------------------------------------------- phase A
def phase_a_stock():
    """Move BoAt stock into Distribution, then cancel all stock that must go."""
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    expense = f"Temporary Opening - {abbr}"
    if not frappe.db.exists("Account", expense):
        expense = f"Stock Adjustment - {abbr}"

    boat_wh = _wh(MERGE_INTO_DIST)
    dist_wh = _wh("PhoneXpert Distribution")
    print(f"BoAt warehouse : {boat_wh}")
    print(f"Dist warehouse : {dist_wh}")

    boat = frappe.db.sql("""select item_code, actual_qty, stock_value, valuation_rate
                            from `tabBin` where warehouse=%s and actual_qty<>0""",
                         boat_wh, as_dict=True)
    dist = {r["item_code"]: r for r in frappe.db.sql(
        """select item_code, actual_qty, valuation_rate from `tabBin`
           where warehouse=%s and actual_qty<>0""", dist_wh, as_dict=True)}
    print(f"BoAt lines to move: {len(boat)}  (overlapping Distribution: "
          f"{sum(1 for r in boat if r['item_code'] in dist)})")

    lines = []
    for r in boat:
        code = r["item_code"]
        bq, br = float(r["actual_qty"]), float(r["valuation_rate"] or 0)
        if code in dist:
            dq = float(dist[code]["actual_qty"]); dr = float(dist[code]["valuation_rate"] or 0)
            qty = dq + bq
            rate = ((dq * dr) + (bq * br)) / qty if qty else br      # weighted average
        else:
            qty, rate = bq, br
        if qty > 0 and rate > 0:
            lines.append((code, qty, rate))

    # 1. cancel every reco we are removing or superseding
    to_cancel = set()
    for branch in CLEAR_STOCK + [MERGE_INTO_DIST]:
        w = _wh(branch)
        if w:
            to_cancel.update(_recos_for(w))
    print(f"\ncancelling {len(to_cancel)} stock reconciliations")
    for name in sorted(to_cancel):
        doc = frappe.get_doc("Stock Reconciliation", name)
        if doc.docstatus == 1:
            doc.cancel()
        print(f"   cancelled {name}")
    frappe.db.commit()

    # 2. repost BoAt quantities into Distribution
    if lines:
        sr = frappe.new_doc("Stock Reconciliation")
        sr.company = company
        sr.purpose = "Opening Stock"
        sr.posting_date = frappe.utils.today()
        sr.set_posting_time = 1
        sr.expense_account = expense
        for code, qty, rate in lines:
            sr.append("items", {"item_code": code, "warehouse": dist_wh,
                                "qty": qty, "valuation_rate": rate})
        sr.flags.ignore_permissions = True
        sr.insert(ignore_permissions=True)
        sr.submit()
        frappe.db.commit()
        print(f"\nBoAt stock reposted into Distribution: {sr.name} ({len(lines)} lines)")

    _stock_summary()


def phase_a2_move_boat():
    """Repost BoAt's quantities into Distribution, read from the myBillBook source.

    phase_a cancelled BoAt's reconciliation before the repost succeeded, so its
    Bin rows are gone; the source file is the surviving record of those figures.
    """
    import re

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    expense = f"Temporary Opening - {abbr}"
    if not frappe.db.exists("Account", expense):
        expense = f"Stock Adjustment - {abbr}"

    dist_wh = _wh("PhoneXpert Distribution")
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip()).upper()

    idx = {}
    for row in frappe.get_all("Item", fields=["name", "item_name"], limit_page_length=0):
        idx.setdefault(norm(row.item_name), row.name)

    existing = {r["item_code"]: r for r in frappe.db.sql(
        """select item_code, actual_qty, valuation_rate from `tabBin`
           where warehouse=%s and actual_qty<>0""", dist_wh, as_dict=True)}

    src = json.load(open(f"{DATA}/biz_dc468420_items.json"))
    lines, skipped = {}, []
    for r in src:
        qty = float(r.get("quantity") or 0)
        if qty <= 0:
            continue
        if (norm(r.get("item_category_name")) or "") in {"SCHEMES"}:
            skipped.append((r.get("name"), "excluded category"))
            continue
        code = idx.get(norm(r.get("name")))
        if not code:
            skipped.append((r.get("name"), "no matching Item"))
            continue
        pp = (r.get("purchase_info") or {}).get("price_per_unit") or 0
        rate = float(pp or r.get("mrp") or (r.get("sales_info") or {}).get("price_per_unit") or 0)
        if not rate:
            skipped.append((r.get("name"), "no valuation basis"))
            continue
        lines[code] = (lines.get(code, (0, rate))[0] + qty, rate)

    merged = []
    for code, (qty, rate) in lines.items():
        if code in existing:
            dq = float(existing[code]["actual_qty"]); dr = float(existing[code]["valuation_rate"] or 0)
            total = dq + qty
            rate = ((dq * dr) + (qty * rate)) / total if total else rate
            qty = total
        merged.append((code, qty, rate))

    print(f"BoAt source rows        : {len(src)}")
    print(f"lines to post into Dist : {len(merged)}  (skipped {len(skipped)})")
    if not merged:
        return

    sr = frappe.new_doc("Stock Reconciliation")
    sr.company = company
    sr.purpose = "Opening Stock"
    sr.posting_date = frappe.utils.today()
    sr.set_posting_time = 1
    sr.expense_account = expense
    for code, qty, rate in merged:
        sr.append("items", {"item_code": code, "warehouse": dist_wh,
                            "qty": qty, "valuation_rate": rate})
    sr.flags.ignore_permissions = True
    sr.insert(ignore_permissions=True)
    sr.submit()
    frappe.db.commit()
    print(f"posted {sr.name} ({len(merged)} lines) into {dist_wh}")
    for n, why in skipped:
        print(f"   skipped: {str(n)[:44]:46} {why}")
    _stock_summary()


def _rename_children(old_branch, new_branch, abbr):
    """Rename the warehouses and cost centers whose names embed the branch name."""
    renamed = []
    for suffix in ("Store", "Service Bay", "Damaged", "Used Devices"):
        old = f"{old_branch} {suffix} - {abbr}"
        new = f"{new_branch} {suffix} - {abbr}"
        if frappe.db.exists("Warehouse", old) and not frappe.db.exists("Warehouse", new):
            frappe.rename_doc("Warehouse", old, new, force=True, merge=False)
            renamed.append(("Warehouse", new))
    for suffix in ("", " Sales", " Service"):
        old = f"{old_branch}{suffix} - {abbr}"
        new = f"{new_branch}{suffix} - {abbr}"
        if frappe.db.exists("Cost Center", old) and not frappe.db.exists("Cost Center", new):
            frappe.rename_doc("Cost Center", old, new, force=True, merge=False)
            renamed.append(("Cost Center", new))
    return renamed


def phase_b_branches():
    """Rename three branches, retype Distribution, create three, delete two."""
    from a3_retail.setup.accounts import ensure_branch_cost_centers

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    gstin = frappe.db.get_value("Company", company, "gstin")
    employee = frappe.db.get_value("Employee", {"user_id": "sreejithvenugopalsv@gmail.com"}, "name")

    # ---- renames -------------------------------------------------------
    for old, (new, code, btype) in RENAME.items():
        if old != new:
            if not frappe.db.exists("Branch", old):
                print(f"  skip rename, missing: {old}")
                continue
            if frappe.db.exists("Branch", new):
                print(f"  skip rename, target exists: {new}")
            else:
                _rename_children(old, new, abbr)
                frappe.rename_doc("Branch", old, new, force=True, merge=False)
                print(f"  renamed branch: {old}  ->  {new}")
        prof = frappe.db.get_value("Branch Profile", {"branch": new}, "name")
        if prof:
            frappe.db.set_value("Branch Profile", prof,
                                {"branch_code": code, "branch_type": btype},
                                update_modified=False)
            print(f"    {new}: code={code} type={btype}")
    frappe.db.commit()

    # ---- new branches --------------------------------------------------
    for name, code, btype in NEW_BRANCHES:
        if not frappe.db.exists("Branch", name):
            b = frappe.new_doc("Branch")
            b.branch = name
            b.flags.ignore_permissions = True
            b.insert(ignore_permissions=True)
        if frappe.db.exists("Branch Profile", {"branch": name}):
            print(f"  branch profile exists: {name}")
            continue
        cc = ensure_branch_cost_centers(name, company)
        bp = frappe.new_doc("Branch Profile")
        bp.branch = name
        bp.branch_code = code
        bp.branch_type = btype
        bp.company = company
        bp.cost_center = cc["sales"]
        bp.sales_cost_center = cc["sales"]
        bp.service_cost_center = cc["service"]
        bp.branch_manager = employee
        bp.is_active = 1
        bp.is_head_office = 0
        if gstin:
            bp.gstin = gstin
        bp.flags.ignore_permissions = True
        bp.insert(ignore_permissions=True)
        # same store-warehouse defect as before: the field arrives pre-filled
        shared = f"Stores - {abbr}"
        if not bp.default_warehouse or bp.default_warehouse == shared:
            from a3_retail.a3_retail_operations.doctype.branch_profile.branch_profile import (
                get_or_create_branch_group,
            )
            wh_name = f"{name} Store"
            full = f"{wh_name} - {abbr}"
            if not frappe.db.exists("Warehouse", full):
                w = frappe.new_doc("Warehouse")
                w.warehouse_name = wh_name
                w.parent_warehouse = get_or_create_branch_group(company)
                w.company = company
                w.is_group = 0
                w.flags.ignore_permissions = True
                w.insert(ignore_permissions=True)
                full = w.name
            frappe.db.set_value("Branch Profile", bp.name, "default_warehouse", full,
                                update_modified=False)
            frappe.db.set_value("Warehouse", full, "custom_branch", name, update_modified=False)
        print(f"  created branch: {name} ({code}, {btype})")
    frappe.db.commit()

    # ---- deletions -----------------------------------------------------
    for name in DELETE_BRANCHES:
        prof = frappe.db.get_value("Branch Profile", {"branch": name}, "name")
        if prof:
            frappe.delete_doc("Branch Profile", prof, force=1, ignore_permissions=True,
                              delete_permanently=True)
        # warehouses carry cancelled ledger history, so disable rather than delete
        for w in frappe.get_all("Warehouse", filters={"custom_branch": name}, pluck="name"):
            frappe.db.set_value("Warehouse", w, "disabled", 1, update_modified=False)
        if frappe.db.exists("Branch", name):
            try:
                frappe.delete_doc("Branch", name, force=1, ignore_permissions=True,
                                  delete_permanently=True)
                print(f"  deleted branch: {name}")
            except Exception as e:
                print(f"  could NOT delete {name}: {str(e)[:120]}")
    frappe.db.commit()

    print("\nfinal branches:")
    for r in frappe.get_all("Branch Profile",
                            fields=["branch_code", "branch", "branch_type", "default_warehouse"],
                            order_by="branch_code"):
        print(f"  {r.branch_code:5} {r.branch[:36]:38} {r.branch_type:16} {r.default_warehouse}")


def _make_contact(party_name, display_name, mobile, email):
    if not (mobile or email):
        return None
    c = frappe.new_doc("Contact")
    c.first_name = display_name[:140] or "Contact"
    c.append("links", {"link_doctype": "Customer", "link_name": party_name})
    if mobile:
        c.append("phone_nos", {"phone": mobile, "is_primary_mobile_no": 1})
    if email:
        c.append("email_ids", {"email_id": email, "is_primary": 1})
    c.flags.ignore_permissions = True
    c.flags.ignore_mandatory = True
    c.insert(ignore_permissions=True)
    return c.name


def _load_parties(cid, branch, key_suffix=""):
    """Create Customers for one myBillBook business, stamped with a branch."""
    import re
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip())

    rows = [r for r in json.load(open(f"{DATA}/biz_{cid}_parties.json"))
            if not r.get("is_deleted") and r.get("company_contact_type") != "supplier"]
    rows.sort(key=lambda r: (norm(r.get("name")).upper(), r["id"]))

    made = skipped = failed = 0
    for i, r in enumerate(rows, 1):
        key = r["id"] + key_suffix
        frappe.db.savepoint("mbb_p")
        try:
            if frappe.db.get_value("Customer", {"mbb_id": key}, "name"):
                skipped += 1
                continue
            name = norm(r.get("name")) or "UNNAMED"
            gstin = norm(r.get("gst_number"))
            doc = frappe.new_doc("Customer")
            doc.customer_name = name[:140]
            doc.customer_group = "Individual"
            doc.territory = "India"
            doc.a3_source_branch = branch
            doc.mbb_id = key
            if gstin:
                doc.gstin = gstin
                doc.gst_category = "Registered Regular"
            doc.flags.ignore_permissions = True
            doc.flags.ignore_mandatory = True
            doc.insert(ignore_permissions=True)
            made += 1

            mobile = norm(r.get("mobile_number"))
            contact = _make_contact(doc.name, name, mobile, norm(r.get("email")))
            if contact:
                frappe.db.set_value("Customer", doc.name,
                                    {"customer_primary_contact": contact, "mobile_no": mobile},
                                    update_modified=False)
        except Exception as e:
            failed += 1
            frappe.db.rollback(save_point="mbb_p")
        if i % 500 == 0:
            frappe.db.commit()
            print(f"     ... {i}/{len(rows)}")
    frappe.db.commit()
    print(f"  {branch[:34]:36} created={made:>5} skipped={skipped:>5} failed={failed}")
    return made


def phase_c_parties():
    """Stamp existing parties, import the two other branches', duplicate for Sales UK."""
    # 1. everything already loaded came from myBillBook "PhoneXpert" -> Accessories PSLA
    n = frappe.db.sql("""update `tabCustomer` set a3_source_branch=%s
                         where ifnull(a3_source_branch,'')='' and ifnull(mbb_id,'')<>''
                           and mbb_id not like '%%#%%'""",
                      "PhoneXpert Accessories PSLA")
    frappe.db.commit()
    print(f"  stamped existing customers -> PhoneXpert Accessories PSLA "
          f"({frappe.db.count('Customer', {'a3_source_branch': 'PhoneXpert Accessories PSLA'})})")

    # 2. Digital Store & Care -> Accessories UK
    _load_parties("8e17035d", "PhoneXpert Accessories UK")

    # 3. The Digital store -> Sales PSLA
    _load_parties("356e948f", "PhoneXpert Sales PSLA")

    # 4. same parties again, as separate records for Sales UK
    _load_parties("356e948f", "PhoneXpert Sales UK", key_suffix="#SLU")

    print("\ncustomers per registered branch:")
    for r in frappe.db.sql("""select ifnull(a3_source_branch,'(none)') b, count(*) n
                              from `tabCustomer` group by a3_source_branch order by n desc""",
                           as_dict=True):
        print(f"  {r['b'][:38]:40}{r['n']:>7}")
    print(f"  {'TOTAL':40}{frappe.db.count('Customer'):>7}")


# Brand detection for the Distribution branch. myBillBook lists boAt goods by
# product line rather than by brand, so the pattern matches those lines.
# Anything not matched stays in "Others" rather than being guessed at.
import re as _re

ZEB_RE = _re.compile(r"ZEBRONIC|ZEBBRONIC|(?<![A-Z])ZEB(?![A-Z])")
BOAT_RE = _re.compile(
    r"(?<![A-Z])BOAT(?![A-Z])|AIRDOPES|BASSHEAD|ROCKERZ|(?<![A-Z])ROCKER|NIRVANA"
    r"|IMMORTAL|ENIGMA|PARTYPAL|PARTY PAL|AAVANTE|(?<![A-Z])AVANTE|STONE"
    r"|(?<![A-Z])WAVE|LUNAR|(?<![A-Z])STORM|XTEND|NEWLY|ULTIMA"
)


def phase_d_categories():
    """Re-group the Distribution branch's stocked items into Zebronics / BoAt / Others."""
    import csv

    for g in ("Zebronics", "BoAt", "Others"):
        if not frappe.db.exists("Item Group", g):
            d = frappe.new_doc("Item Group")
            d.item_group_name = g
            d.parent_item_group = "All Item Groups"
            d.is_group = 0
            d.flags.ignore_permissions = True
            d.insert(ignore_permissions=True)
    frappe.db.commit()

    wh = _wh("PhoneXpert Distribution")
    codes = frappe.db.sql_list(
        "select item_code from `tabBin` where warehouse=%s and actual_qty<>0", wh)
    print(f"Distribution stocked items: {len(codes)}")

    counts = {"Zebronics": 0, "BoAt": 0, "Others": 0}
    rows = []
    for code in codes:
        item_name = frappe.db.get_value("Item", code, "item_name") or code
        up = _re.sub(r"\s+", " ", item_name.strip()).upper()
        group = "Zebronics" if ZEB_RE.search(up) else ("BoAt" if BOAT_RE.search(up) else "Others")
        old = frappe.db.get_value("Item", code, "item_group")
        if old != group:
            frappe.db.set_value("Item", code, "item_group", group, update_modified=False)
        counts[group] += 1
        rows.append((code, item_name, old, group))
    frappe.db.commit()

    with open(DATA + "/distribution_item_categories.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_code", "item_name", "old_item_group", "new_item_group"])
        w.writerows(rows)

    print(f"  Zebronics : {counts['Zebronics']}")
    print(f"  BoAt      : {counts['BoAt']}")
    print(f"  Others    : {counts['Others']}")
    print("\nreport -> distribution_item_categories.csv")


def verify():
    print("=== branches ===")
    for r in frappe.get_all("Branch Profile",
                            fields=["branch_code", "branch", "branch_type", "default_warehouse"],
                            order_by="branch_code"):
        wh = r.default_warehouse
        agg = frappe.db.sql("""select count(*) n, coalesce(sum(actual_qty),0) q,
                                      coalesce(sum(stock_value),0) v
                               from `tabBin` where warehouse=%s and actual_qty<>0""", wh)[0]
        cust = frappe.db.count("Customer", {"a3_source_branch": r.branch})
        print(f"  {r.branch_code:5} {r.branch[:30]:32} {r.branch_type:13} "
              f"items={int(agg[0]):>4} qty={float(agg[1]):>9,.0f} val={float(agg[2]):>14,.2f} "
              f"parties={cust:>5}")
    print(f"\n  total customers : {frappe.db.count('Customer')}")
    print(f"  total suppliers : {frappe.db.count('Supplier')}")
    print(f"  total items     : {frappe.db.count('Item')}")


def _stock_summary():
    rows = frappe.db.sql("""
        select bp.branch b, coalesce(count(bn.name),0) items,
               coalesce(sum(bn.actual_qty),0) qty, coalesce(sum(bn.stock_value),0) val
        from `tabBranch Profile` bp
        left join `tabBin` bn on bn.warehouse=bp.default_warehouse and bn.actual_qty<>0
        group by bp.branch order by bp.branch
    """, as_dict=True)
    print(f"\n{'branch':38}{'items':>7}{'qty':>10}{'value':>16}")
    for r in rows:
        print(f"{r['b'][:36]:38}{int(r['items']):>7}{float(r['qty']):>10,.0f}{float(r['val']):>16,.2f}")
