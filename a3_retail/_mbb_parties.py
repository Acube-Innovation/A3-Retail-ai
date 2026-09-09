"""One-off tenant load: PhoneXpert myBillBook parties -> ERPNext Customer / Supplier.

Not registered in patches.txt and not imported by hooks — runs only when called:

    bench --site retail execute a3_retail._mbb_parties.run

Idempotent via a `mbb_id` custom field holding the myBillBook UUID, so a re-run
skips anything already loaded and a later delta sync can find its own records.

Opening balances are NOT posted here — they are written to a CSV for the
cutover step, because posting them needs a cutover date and an account decision.
"""

import csv
import json
import re

import frappe

"""Source and report directory.

Deliberately NOT the session scratchpad — that is wiped at session boundaries
and took the first copy of this data with it.
"""
SCRATCH = "/home/acubeadmin/Projects/A3-retail/migration-data"
SRC = SCRATCH + "/parties_raw.json"

CUSTOMER_GROUP = "Individual"
TERRITORY = "India"
SUPPLIER_GROUP = "Local"
COUNTRY = "India"


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _ensure_custom_field():
    """A stable handle on the source record, so re-runs and deltas are safe."""
    for dt in ("Customer", "Supplier"):
        if frappe.db.exists("Custom Field", {"dt": dt, "fieldname": "mbb_id"}):
            continue
        cf = frappe.new_doc("Custom Field")
        cf.dt = dt
        cf.fieldname = "mbb_id"
        cf.label = "myBillBook ID"
        cf.fieldtype = "Data"
        cf.read_only = 1
        cf.hidden = 1
        cf.no_copy = 1
        cf.insert(ignore_permissions=True)
    frappe.db.commit()


def _ensure_naming():
    """5,812 walk-ins include 723 repeated names; docname cannot be the name.

    `set_single_value` alone is not enough — ERPNext reads this through the
    document cache, so it must be cleared or the change is invisible to the very
    inserts it is meant to govern.
    """
    changed = []
    for single, field, want in (
        ("Selling Settings", "cust_master_name", "Naming Series"),
        ("Buying Settings", "supp_master_name", "Naming Series"),
    ):
        # Customer.autoname reads frappe.defaults.get_global_default(), not the
        # Settings row. Saving the doc is what syncs the two — set_single_value
        # updates the row and leaves autoname still seeing the old value.
        doc = frappe.get_single(single)
        if doc.get(field) != want:
            doc.set(field, want)
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)
            changed.append(f"{single}.{field} -> {want}")
        frappe.db.set_default(field, want)

    frappe.db.commit()
    frappe.clear_cache()

    got = frappe.defaults.get_global_default("cust_master_name")
    if got != "Naming Series":
        frappe.throw(f"cust_master_name global default is {got!r}; "
                     "refusing to load with name-as-docname")
    return changed


def reset():
    """Delete everything this loader created. For re-running a trial cleanly."""
    n = 0
    for dt in ("Customer", "Supplier"):
        for row in frappe.get_all(dt, filters={"mbb_id": ["is", "set"]}, pluck="name"):
            for link_dt in ("Contact", "Address"):
                for ln in frappe.get_all(
                    "Dynamic Link",
                    filters={"link_doctype": dt, "link_name": row, "parenttype": link_dt},
                    pluck="parent",
                ):
                    frappe.delete_doc(link_dt, ln, force=1, ignore_permissions=True,
                                      ignore_missing=True, delete_permanently=True)
            if dt == "Customer":
                frappe.db.set_value(dt, row, "customer_primary_contact", None,
                                    update_modified=False)
            frappe.delete_doc(dt, row, force=1, ignore_permissions=True,
                              ignore_missing=True, delete_permanently=True)
            n += 1
    frappe.db.commit()
    print(f"deleted {n} parties loaded from myBillBook")
    print("Customer:", frappe.db.count("Customer"), " Supplier:", frappe.db.count("Supplier"),
          " Contact:", frappe.db.count("Contact"))


def _gst_category(gstin):
    return "Registered Regular" if gstin else "Unregistered"


def _make_contact(party_type, party_name, display_name, mobile, email):
    if not (mobile or email):
        return None
    c = frappe.new_doc("Contact")
    c.first_name = display_name[:140] or "Contact"
    c.append("links", {"link_doctype": party_type, "link_name": party_name})
    if mobile:
        c.append("phone_nos", {"phone": mobile, "is_primary_mobile_no": 1})
    if email:
        c.append("email_ids", {"email_id": email, "is_primary": 1})
    c.flags.ignore_permissions = True
    c.flags.ignore_mandatory = True
    c.insert(ignore_permissions=True)
    return c.name


def _make_address(party_type, party_name, display_name, addr):
    street = _norm(addr.get("street_address"))
    city = _norm(addr.get("city"))
    state = _norm(addr.get("state"))
    if not (street or city):
        return None
    # india_compliance rejects an Indian Address without a state, and myBillBook
    # holds a state for only 2 of the 8 parties that have any address at all.
    # Skip rather than invent one — the address is reported for manual entry.
    if not state:
        return "SKIPPED_NO_STATE"
    a = frappe.new_doc("Address")
    a.address_title = display_name[:100] or "Address"
    a.address_type = "Billing"
    a.address_line1 = street or city
    a.city = city or "-"
    a.state = state
    a.pincode = str(addr.get("pincode") or "") or None
    a.country = COUNTRY
    a.append("links", {"link_doctype": party_type, "link_name": party_name})
    a.flags.ignore_permissions = True
    a.flags.ignore_mandatory = True
    a.insert(ignore_permissions=True)
    return a.name


def run(limit=None):
    parties = [r for r in json.load(open(SRC)) if not r.get("is_deleted")]
    parties.sort(key=lambda r: (_norm(r.get("name")).upper(), r["id"]))
    if limit:
        parties = parties[: int(limit)]

    _ensure_custom_field()
    naming_changed = _ensure_naming()
    for c in naming_changed:
        print(f"naming changed: {c}")

    made_cust = made_supp = made_contact = made_addr = skipped = failed = 0
    errors, mapping, balances = [], [], []

    for i, r in enumerate(parties, 1):
        mbb_id = r["id"]
        name = _norm(r.get("name")) or "UNNAMED"
        is_supplier = (r.get("company_contact_type") == "supplier")
        dt = "Supplier" if is_supplier else "Customer"

        # A bare frappe.db.rollback() discards the WHOLE uncommitted transaction,
        # so one bad record used to destroy every insert since the last commit.
        # A savepoint scopes the undo to this record alone.
        frappe.db.savepoint("mbb_party")
        try:
            existing = frappe.db.get_value(dt, {"mbb_id": mbb_id}, "name")
            if existing:
                skipped += 1
                mapping.append((mbb_id, dt, existing, name))
                continue

            gstin = _norm(r.get("gst_number"))
            mobile = _norm(r.get("mobile_number"))
            email = _norm(r.get("email"))

            if is_supplier:
                doc = frappe.new_doc("Supplier")
                doc.supplier_name = name[:140]
                doc.supplier_group = SUPPLIER_GROUP
                doc.country = COUNTRY
            else:
                doc = frappe.new_doc("Customer")
                doc.customer_name = name[:140]
                doc.customer_group = CUSTOMER_GROUP
                doc.territory = TERRITORY
                if r.get("credit_period"):
                    doc.payment_terms = None       # term templates not set up yet
            if gstin:
                doc.gstin = gstin
                doc.gst_category = _gst_category(gstin)
            doc.mbb_id = mbb_id
            doc.flags.ignore_permissions = True
            doc.flags.ignore_mandatory = True
            doc.insert(ignore_permissions=True)

            if is_supplier:
                made_supp += 1
            else:
                made_cust += 1
            mapping.append((mbb_id, dt, doc.name, name))

            contact = _make_contact(dt, doc.name, name, mobile, email)
            if contact:
                made_contact += 1
                if not is_supplier:
                    frappe.db.set_value("Customer", doc.name,
                                        "customer_primary_contact", contact,
                                        update_modified=False)
                    frappe.db.set_value("Customer", doc.name, "mobile_no", mobile,
                                        update_modified=False)

            addr = _make_address(dt, doc.name, name, r.get("billing_address") or {})
            if addr == "SKIPPED_NO_STATE":
                errors.append({"mbb_id": mbb_id, "name": name, "type": dt,
                               "error": "address skipped - no state in myBillBook"})
            elif addr:
                made_addr += 1

            bal = float(r.get("balance") or 0)
            if bal:
                balances.append((mbb_id, dt, doc.name, name, mobile, bal))

        except Exception as e:
            failed += 1
            errors.append({"mbb_id": mbb_id, "name": name, "type": dt, "error": str(e)[:200]})
            frappe.db.rollback(save_point="mbb_party")

        if i % 250 == 0:
            frappe.db.commit()
            print(f"  ... {i}/{len(parties)}  cust={made_cust} supp={made_supp} fail={failed}")

    frappe.db.commit()

    with open(SCRATCH + "/party_id_map.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mybillbook_id", "doctype", "erpnext_name", "party_name"])
        w.writerows(mapping)

    with open(SCRATCH + "/party_opening_balances.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mybillbook_id", "doctype", "erpnext_name", "party_name",
                    "mobile", "balance_in_mybillbook"])
        w.writerows(balances)

    if errors:
        json.dump(errors, open(SCRATCH + "/party_import_errors.json", "w"), indent=1)

    print("\n" + "=" * 56)
    print(f"  customers created : {made_cust}")
    print(f"  suppliers created : {made_supp}")
    print(f"  contacts created  : {made_contact}")
    print(f"  addresses created : {made_addr}")
    print(f"  skipped (existing): {skipped}")
    print(f"  failed            : {failed}")
    print(f"  balances recorded : {len(balances)} (NOT posted)")
    print(f"  TOTAL Customer    : {frappe.db.count('Customer')}")
    print(f"  TOTAL Supplier    : {frappe.db.count('Supplier')}")
    print("=" * 56)
