import frappe

def run():
    rows = frappe.get_all("Account", filters={"account_name": ["like", "%CGST%"]},
                          fields=["name","root_type","account_type","parent_account"])
    for r in rows: print(r)
