"""Create the Employee, User and six Branch Profiles for PhoneXpert.

Each myBillBook business is one outlet, so each becomes a Branch + Branch Profile.
Branch Profile.after_insert creates the branch warehouses, which the opening-stock
step then posts into.

    bench --site retail execute a3_retail._mbb_branches.run

Branch codes are capped at 4 alphanumeric characters by Branch Profile validation
and become part of every invoice number, so they are declared explicitly here
rather than derived.
"""

import frappe

from a3_retail.setup.accounts import ensure_branch_cost_centers

# myBillBook company_id prefix -> (Branch name, branch_code, branch_type)
# Names are made distinct because MySQL collation is case-insensitive and the
# source has both "PhoneXpert" and "PHONEXPERT".
BRANCHES = [
    ("ac5e07a5", "PhoneXpert Main",                   "PX",   "Sales & Service"),
    ("2e7704a6", "PhoneXpert Distribution",           "PXD",  "Sales Only"),
    ("356e948f", "PhoneXpert The Digital Store",      "PXDS", "Sales & Service"),
    ("21c71d2c", "PhoneXpert Assured",                "PXA",  "Sales Only"),
    ("dc468420", "PhoneXpert BoAt",                   "PXB",  "Sales Only"),
    ("8e17035d", "PhoneXpert Digital Store and Care", "PXSC", "Sales & Service"),
]

EMP = {
    "first_name": "SREEJITH",
    "user_id": "sreejithvenugopalsv@gmail.com",
    "mobile": "7907878727",
    # PLACEHOLDERS — myBillBook holds no HR data. Flagged in the run output.
    "date_of_birth": "1990-01-01",
    "date_of_joining": "2022-06-03",   # myBillBook account created_at
    "gender": "Male",
}

OWNER_ROLE = "A3 Retail Admin"   # desk access: the owner belongs in the desk


def _ensure_user():
    email = EMP["user_id"]
    if not frappe.db.exists("User", email):
        u = frappe.new_doc("User")
        u.email = email
        u.first_name = EMP["first_name"]
        u.mobile_no = EMP["mobile"]
        u.send_welcome_email = 0
        u.append("roles", {"role": OWNER_ROLE})
        u.flags.ignore_permissions = True
        u.insert(ignore_permissions=True)
        return email, True
    if OWNER_ROLE not in frappe.get_roles(email):
        u = frappe.get_doc("User", email)
        u.append("roles", {"role": OWNER_ROLE})
        u.flags.ignore_permissions = True
        u.save(ignore_permissions=True)
    return email, False


def _ensure_employee(company):
    existing = frappe.db.get_value("Employee", {"user_id": EMP["user_id"]}, "name")
    if existing:
        return existing, False
    e = frappe.new_doc("Employee")
    e.first_name = EMP["first_name"]
    e.company = company
    e.status = "Active"
    e.gender = EMP["gender"]
    e.date_of_birth = EMP["date_of_birth"]
    e.date_of_joining = EMP["date_of_joining"]
    e.user_id = EMP["user_id"]
    e.cell_number = EMP["mobile"]
    e.flags.ignore_permissions = True
    e.flags.ignore_mandatory = True
    e.insert(ignore_permissions=True)
    return e.name, True


def fix_store_warehouses():
    """Give every branch its own Store warehouse.

    Branch Profile.create_branch_warehouses only creates a warehouse for a field
    that is still blank, and `default_warehouse` arrives pre-filled with the
    company-wide `Stores - <abbr>`. Every branch therefore shared one store, and
    stamp_branch_on_linked_records then tagged that shared warehouse with
    whichever branch was saved last — so branch stock isolation was broken in
    both directions.
    """
    from a3_retail.a3_retail_operations.doctype.branch_profile.branch_profile import (
        get_or_create_branch_group,
    )

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    shared = f"Stores - {abbr}"
    parent = get_or_create_branch_group(company)
    fixed = []

    for name in frappe.get_all("Branch Profile", pluck="name"):
        bp = frappe.get_doc("Branch Profile", name)
        if bp.default_warehouse and bp.default_warehouse != shared:
            continue
        wh_name = f"{bp.branch} Store"
        full = f"{wh_name} - {abbr}"
        if not frappe.db.exists("Warehouse", full):
            w = frappe.new_doc("Warehouse")
            w.warehouse_name = wh_name
            w.parent_warehouse = parent
            w.company = company
            w.is_group = 0
            w.flags.ignore_permissions = True
            w.insert(ignore_permissions=True)
            full = w.name
        frappe.db.set_value("Branch Profile", name, "default_warehouse", full,
                            update_modified=False)
        frappe.db.set_value("Warehouse", full, "custom_branch", bp.branch,
                            update_modified=False)
        fixed.append((bp.branch_code, full))

    # The shared warehouse must not claim any branch.
    if frappe.db.exists("Warehouse", shared):
        frappe.db.set_value("Warehouse", shared, "custom_branch", None,
                            update_modified=False)

    frappe.db.commit()
    for code, wh in fixed:
        print(f"    {code:5} store -> {wh}")
    print(f"  cleared stray branch stamp on {shared}")
    return fixed


def run():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    gstin = frappe.db.get_value("Company", company, "gstin")

    user, user_new = _ensure_user()
    print(f"user     : {user} {'(created)' if user_new else '(existing)'}")

    employee, emp_new = _ensure_employee(company)
    print(f"employee : {employee} {'(created)' if emp_new else '(existing)'}")

    made_branch = made_profile = 0
    rows = []

    for cid, branch_name, code, btype in BRANCHES:
        if not frappe.db.exists("Branch", branch_name):
            br = frappe.new_doc("Branch")
            br.branch = branch_name
            br.flags.ignore_permissions = True
            br.insert(ignore_permissions=True)
            made_branch += 1

        # Employee.branch drives the branch User Permissions; put the owner on
        # the main outlet, since one employee can hold only one branch.
        if branch_name == BRANCHES[0][1]:
            frappe.db.set_value("Employee", employee, "branch", branch_name,
                                update_modified=False)

        existing = frappe.db.get_value("Branch Profile", {"branch": branch_name}, "name")
        if existing:
            rows.append((branch_name, code, existing, "existing"))
            continue

        cc = ensure_branch_cost_centers(branch_name, company)

        bp = frappe.new_doc("Branch Profile")
        bp.branch = branch_name
        bp.branch_code = code
        bp.branch_type = btype
        bp.company = company
        bp.cost_center = cc["group"] if False else cc["sales"]   # must be a leaf
        bp.sales_cost_center = cc["sales"]
        bp.service_cost_center = cc["service"]
        bp.branch_manager = employee
        bp.is_active = 1
        bp.is_head_office = 1 if branch_name == BRANCHES[0][1] else 0
        if gstin:
            bp.gstin = gstin
        bp.flags.ignore_permissions = True
        bp.insert(ignore_permissions=True)
        made_profile += 1
        rows.append((branch_name, code, bp.name, "created"))

    frappe.db.commit()

    print("\n  fixing per-branch store warehouses:")
    fix_store_warehouses()

    print("\n" + "=" * 70)
    print(f"  branches created        : {made_branch}")
    print(f"  branch profiles created : {made_profile}")
    print("\n  warehouses per branch (auto-created by Branch Profile):")
    for branch_name, code, _n, state in rows:
        prof = frappe.db.get_value(
            "Branch Profile", {"branch": branch_name},
            ["default_warehouse", "service_warehouse", "transit_warehouse"], as_dict=True)
        print(f"    {code:5} {branch_name[:34]:36} {state}")
        print(f"          store   : {prof.default_warehouse}")
        if prof.service_warehouse:
            print(f"          service : {prof.service_warehouse}")
    print("=" * 70)
    print("\nPLACEHOLDER DATA on the Employee - correct these:")
    print(f"   date_of_birth  = {EMP['date_of_birth']}   (not held by myBillBook)")
    print(f"   date_of_joining= {EMP['date_of_joining']} (myBillBook account creation date)")
    print(f"   gender         = {EMP['gender']}          (not held by myBillBook)")
