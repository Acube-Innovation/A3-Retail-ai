"""Create the PhoneXpert branch staff: User + Employee, branch-scoped, portal-only.

    bench --site retail execute a3_retail._mbb_staff.run

Every account is provisioned as a Website User, so /app is refused and the branch
app at /retail is the only way in. Each Employee carries a branch, which is what
`_me()` reads and what drives the branch User Permissions.

`gender` is mandatory on Employee but was not supplied for anyone. It is set to
"Prefer not to say" rather than inferred from a name or from an emergency
contact's relationship — see NEEDS_CORRECTION in the run output.
"""

import frappe

TEMP_PASSWORD = "PhoneXpert@2026"

# role per branch, from the branch type
ROLE_BY_BRANCH = {
    "PhoneXpert Accessories PSLA": "Sales Executive",
    "PhoneXpert Accessories UK": "Sales Executive",
    "PhoneXpert Sales PSLA": "Sales Executive",
    "PhoneXpert Sales UK": "Sales Executive",
    "PhoneXpert Services PSLA": "Technician",
    "PhoneXpert Services UK": "Technician",
    "PhoneXpert Distribution": "Store Keeper",
}

PLACEHOLDER_GENDER = "Prefer not to say"

# (branch, full_name, dob, doj, phone, email, pan, education, marital,
#  emergency_phone, emergency_name, emergency_relation, blood_group)
STAFF = [
    ("PhoneXpert Accessories PSLA", "Nithin S L", "2002-07-04", "2022-05-01",
     "9562933768", "kannansl318@gmail.com", "BKYPL1786P", "+2", "Married",
     "8075656179", "Sruthi", "Wife", "A+"),
    ("PhoneXpert Accessories PSLA", "Ashik S", "2004-10-19", "2025-08-07",
     "8072498023", "gkerala7@gmail.com", "", "BSc Radiology", "Single",
     "9486920873", "Vinesh S", "Brother", "O+"),
    ("PhoneXpert Accessories PSLA", "Sujith R", "1995-09-13", "2022-01-01",
     "9605609983", "sujithmanikumar007@gmail.com", "KDDPS1156K", "+2 & ITI (Welder)",
     "Single", "9656860782", "Ravi Kumar D L", "Father", "A-"),

    ("PhoneXpert Sales PSLA", "Arun S", "2001-06-21", "2024-10-26",
     "9995346539", "asb4arunsb@gmail.com", "FMEPA2556Q", "Plus Two", "Married",
     "6238365246", "Krishna", "Wife", "A+"),
    ("PhoneXpert Sales PSLA", "Abish Dev A", "1998-03-03", "2025-06-23",
     "9567686258", "abishdeva@gmail.com", "EGIPA0962B",
     "BE Electronics and Communication Engineering", "Single",
     "9447437508", "Arul", "Father", "A+"),
    ("PhoneXpert Sales PSLA", "Prince L S", "1999-09-11", "2026-03-04",
     "7907756243", "princels2018@gmail.com", "NKSPS2742J", "BA English Literature",
     "Married", "8594071304", "Dhanya S", "Wife", "O+"),

    ("PhoneXpert Accessories UK", "Muhammed Farook N", "2003-06-26", "2023-11-02",
     "7994629851", "farooknoushad22@gmail.com", "DKAPN5280E", "Diploma", "Single",
     "8943510549", "Rasheeda", "Mother", "B+"),

    ("PhoneXpert Sales UK", "Jijo", "2002-06-04", "2025-08-16",
     "7356835689", "jjijo849@gmail.com", "DWHPG4582B", "ITI", "Single",
     "9961602240", "Jijin", "Brother", "B+"),
    ("PhoneXpert Sales UK", "Soujith S S", "2001-11-19", "2022-05-12",
     "9995071348", "soujith2001@gmail.com", "STVPS0869D", "+2", "Single",
     "9809567992", "Sourav S S", "Brother", ""),

    ("PhoneXpert Services UK", "Akhil Raj", "1995-02-26", "2022-05-02",
     "9746225420", "akhilanu820@gmail.com", "DCEPA9733F", "Degree", "Single",
     "7025077108", "Aju", "Brother", "A+"),

    ("PhoneXpert Distribution", "Abhijith S U", "2003-05-15", "2023-06-23",
     "8129457480", "abhi808911@gmail.com", "AQRPU0371P", "+2", "Married",
     "8089118398", "Pooja", "Wife", ""),

    ("PhoneXpert Services PSLA", "Sarang P", "2004-08-12", "2026-08-10",
     "8590180895", "sarang.p.543@gmail.com", "", "", "Single",
     "9633639803", "Anitha Kumari", "Mother", "A+"),
]

NEEDS_CORRECTION = [
    ("ALL 12", "gender", "set to 'Prefer not to say' — not supplied, and not inferred"),
    ("Sujith R", "date_of_joining", "was blank; placeholder 2022-01-01"),
    ("Soujith S S", "date_of_birth", "source read '19/11/200'; assumed 2001 from the email address"),
    ("Soujith S S", "date_of_joining", "source read 'may12'; placeholder 2022-05-12"),
    ("Nithin S L", "date_of_joining", "source read 'May 2022' with no day; used the 1st"),
    ("Abish Dev A", "marital_status", "source read 'NILL'; recorded as Single"),
    ("Ashik S, Sarang P", "pan_number", "not supplied"),
    ("Soujith S S, Abhijith S U", "blood_group", "not supplied"),
    ("Sarang P", "education", "not supplied"),
]


def run():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    made_user = made_emp = skipped = failed = 0
    errors = []

    for (branch, full_name, dob, doj, phone, email, pan, education, marital,
         em_phone, em_name, em_rel, blood) in STAFF:

        role = ROLE_BY_BRANCH[branch]
        frappe.db.savepoint("mbb_staff")
        try:
            # ---- User -------------------------------------------------
            if not frappe.db.exists("User", email):
                parts = full_name.split()
                u = frappe.new_doc("User")
                u.email = email
                u.first_name = parts[0]
                if len(parts) > 1:
                    u.last_name = " ".join(parts[1:])
                u.mobile_no = phone
                u.send_welcome_email = 0
                u.new_password = TEMP_PASSWORD
                u.append("roles", {"role": role})
                u.flags.ignore_permissions = True
                u.insert(ignore_permissions=True)
                made_user += 1
            elif role not in frappe.get_roles(email):
                doc = frappe.get_doc("User", email)
                doc.append("roles", {"role": role})
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)

            # ---- Employee ---------------------------------------------
            if frappe.db.exists("Employee", {"user_id": email}):
                skipped += 1
                continue

            parts = full_name.split()
            e = frappe.new_doc("Employee")
            e.first_name = parts[0]
            if len(parts) > 1:
                e.last_name = " ".join(parts[1:])
            e.employee_name = full_name
            e.company = company
            e.status = "Active"
            e.gender = PLACEHOLDER_GENDER
            e.date_of_birth = dob
            e.date_of_joining = doj
            e.branch = branch
            e.user_id = email
            e.cell_number = phone
            e.personal_email = email
            if pan:
                e.pan_number = pan
            if marital:
                e.marital_status = marital
            if blood:
                e.blood_group = blood
            if em_name:
                e.person_to_be_contacted = em_name
            if em_phone:
                e.emergency_phone_number = em_phone
            if em_rel:
                e.relation = em_rel
            if education:
                e.append("education", {"school_univ": education, "qualification": education})
            e.flags.ignore_permissions = True
            e.flags.ignore_mandatory = True
            e.insert(ignore_permissions=True)
            made_emp += 1
            print(f"  {branch[:30]:32} {full_name[:22]:24} {e.name}  role={role}")

        except Exception as ex:
            failed += 1
            errors.append((full_name, str(ex)[:180]))
            frappe.db.rollback(save_point="mbb_staff")

    frappe.db.commit()

    # ---- turn them into branch-app (Website User) accounts -------------
    from a3_retail.setup import staff_portal
    staff_portal.provision(verbose=False)
    frappe.db.commit()

    print("\n" + "=" * 66)
    print(f"  users created     : {made_user}")
    print(f"  employees created : {made_emp}")
    print(f"  skipped           : {skipped}")
    print(f"  failed            : {failed}")
    for n, e in errors:
        print(f"     FAILED {n}: {e}")
    print(f"\n  temporary password for all: {TEMP_PASSWORD}")
    print("=" * 66)
    print("\nNEEDS CORRECTION — assumptions made from incomplete source data:")
    for who, field, why in NEEDS_CORRECTION:
        print(f"   {who[:26]:28}{field:18}{why}")
