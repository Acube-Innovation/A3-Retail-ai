"""Set the branch-app password for the PhoneXpert owner account and verify it."""

import frappe
from frappe.utils.password import check_password, update_password

USER = "sreejithvenugopalsv@gmail.com"


def run(password=None):
    if not password:
        frappe.throw("password is required")

    if not frappe.db.exists("User", USER):
        frappe.throw(f"No such user: {USER}")

    update_password(USER, password)
    frappe.db.set_value("User", USER, {"enabled": 1}, update_modified=False)
    frappe.db.commit()

    # Prove it rather than assume it.
    try:
        who = check_password(USER, password)
        ok = who == USER
    except frappe.AuthenticationError:
        ok = False

    doc = frappe.db.get_value(
        "User", USER, ["enabled", "user_type", "login_after", "last_login"], as_dict=True
    )
    emp = frappe.db.get_value(
        "Employee", {"user_id": USER}, ["name", "status", "branch"], as_dict=True
    )

    print(f"user            : {USER}")
    print(f"password set    : {'VERIFIED' if ok else 'FAILED VERIFICATION'}")
    print(f"enabled         : {doc.enabled}")
    print(f"user_type       : {doc.user_type}")
    print(f"employee        : {dict(emp) if emp else 'NONE'}")
