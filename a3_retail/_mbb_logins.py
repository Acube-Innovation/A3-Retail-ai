"""Build the branch-login credential sheet for handover.

    bench --site retail execute a3_retail._mbb_logins.run

Contains plaintext passwords, so it is written outside the repository.
"""

import os

import frappe

# Passwords as set during this migration.
OWNER = "sreejithvenugopalsv@gmail.com"
OWNER_PASSWORD = "PhoneXpert@1910"
STAFF_PASSWORD = "PhoneXpert@2026"

OUT_DIRS = [
    os.path.expanduser("~/Desktop"),
    "/home/acubeadmin/Projects/A3-retail/migration-data",
]
FILENAME = "PhoneXpert-Branch-Logins.xlsx"


def _rows():
    rows = []
    for e in frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["is", "set"]},
        fields=["employee_name", "branch", "user_id", "designation", "cell_number"],
        order_by="branch, employee_name",
    ):
        user_type = frappe.db.get_value("User", e.user_id, "user_type")
        roles = sorted(
            set(frappe.get_roles(e.user_id))
            - {"All", "Guest", "A3 Branch Staff", "Desk User", "Employee",
               "Employee Self Service"}
        )
        is_owner = e.user_id == OWNER
        rows.append({
            "branch": e.branch or "",
            "name": e.employee_name,
            "username": e.user_id,
            "password": OWNER_PASSWORD if is_owner else STAFF_PASSWORD,
            "role": "A3 Retail Admin (all branches)" if is_owner else (roles[0] if roles else ""),
            "access": "Desk /app + branch app" if user_type == "System User"
                      else "Branch app /retail only",
            "phone": e.cell_number or "",
        })
    rows.sort(key=lambda r: (r["access"].startswith("Branch"), r["branch"], r["name"]))
    return rows


def run():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    rows = _rows()
    wb = Workbook()
    ws = wb.active
    ws.title = "Branch Logins"

    ws["A1"] = "PhoneXpert — Branch App Logins"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = ("Sign in at /retail/login  ·  passwords below are TEMPORARY and "
                "must be changed before go-live")
    ws["A2"].font = Font(size=10, italic=True, color="9C4221")
    ws.append([])

    headers = ["Branch", "Name", "Username (email)", "Password", "Role", "Access", "Phone"]
    ws.append(headers)
    head_row = ws.max_row
    fill = PatternFill("solid", fgColor="1F3A34")
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=head_row, column=col)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(vertical="center")

    for r in rows:
        ws.append([r["branch"], r["name"], r["username"], r["password"],
                   r["role"], r["access"], r["phone"]])

    widths = [34, 24, 34, 20, 30, 26, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    ws.auto_filter.ref = (f"A{head_row}:"
                          f"{get_column_letter(len(headers))}{ws.max_row}")

    written = []
    for d in OUT_DIRS:
        if not os.path.isdir(d):
            continue
        path = os.path.join(d, FILENAME)
        wb.save(path)
        written.append(path)

    print(f"rows: {len(rows)}")
    for r in rows:
        print(f"  {r['branch'][:30]:32}{r['name'][:20]:22}{r['username'][:32]:34}{r['password']}")
    print("\nwritten to:")
    for p in written:
        print("  ", p, f"({os.path.getsize(p)} bytes)")
