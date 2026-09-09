"""One-off tenant load: remaining myBillBook masters -> ERPNext.

Covers what the item and party loaders did not: bank / cash accounts, party
categories, and a report of the myBillBook user list.

    bench --site retail execute a3_retail._mbb_masters.run

Transactions are never touched. Account balances are RECORDED, not posted —
posting them needs the cutover date and is part of the opening-balance step.
"""

import csv
import json
import re

import frappe

DATA = "/home/acubeadmin/Projects/A3-retail/migration-data"
SRC = DATA + "/masters_raw.json"

# IFSC prefix -> bank name. Only used when myBillBook holds no bank_name.
IFSC_BANKS = {
    "FDRL": "Federal Bank", "SBIN": "State Bank of India", "HDFC": "HDFC Bank",
    "ICIC": "ICICI Bank", "UTIB": "Axis Bank", "PUNB": "Punjab National Bank",
    "CNRB": "Canara Bank", "IOBA": "Indian Overseas Bank", "UBIN": "Union Bank of India",
    "KKBK": "Kotak Mahindra Bank", "IDIB": "Indian Bank", "BARB": "Bank of Baroda",
    "SIBL": "South Indian Bank", "CSBK": "CSB Bank", "ESFB": "Equitas Small Finance Bank",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _derive_bank_name(acc):
    """Best available bank name, with the source of the guess reported."""
    if _norm(acc.get("bank_name")):
        return _norm(acc["bank_name"]), "bank_name"
    ifsc = _norm(acc.get("ifsc_code")).upper()
    if len(ifsc) >= 4 and ifsc[:4] in IFSC_BANKS:
        return IFSC_BANKS[ifsc[:4]], f"ifsc:{ifsc[:4]}"
    branch = _norm(acc.get("branch_name"))
    if branch:
        return _norm(branch.split(",")[0]), "branch_name"

    # Last resort: recognise a bank inside the alias. Without this, an alias like
    # "SBI CURRENT ACCOUNT" becomes a Bank of that name — an account, not a bank.
    alias = _norm(acc.get("alias_name"))
    upper = alias.upper()
    for kw, full in (
        ("SBI", "State Bank of India"), ("STATE BANK", "State Bank of India"),
        ("HDFC", "HDFC Bank"), ("ICICI", "ICICI Bank"), ("AXIS", "Axis Bank"),
        ("FEDERAL", "Federal Bank"), ("CANARA", "Canara Bank"),
        ("SOUTH INDIAN", "South Indian Bank"), ("KOTAK", "Kotak Mahindra Bank"),
        ("UNION", "Union Bank of India"), ("PNB", "Punjab National Bank"),
    ):
        if kw in upper:
            return full, f"alias-keyword:{kw}"
    return "Unknown Bank", "fallback"


def _bank_parent(company, abbr):
    """The Bank Accounts group in the chart of accounts."""
    for candidate in (f"Bank Accounts - {abbr}", f"Bank - {abbr}"):
        if frappe.db.exists("Account", candidate):
            return candidate
    found = frappe.db.get_value(
        "Account",
        {"company": company, "is_group": 1, "account_name": ["like", "%Bank%"]},
        "name",
    )
    if found:
        return found
    return frappe.db.get_value(
        "Account", {"company": company, "is_group": 1, "account_name": ["like", "%Current Asset%"]},
        "name",
    )


def run():
    data = json.load(open(SRC))
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    abbr = frappe.get_cached_value("Company", company, "abbr")
    parent = _bank_parent(company, abbr)
    if not parent:
        frappe.throw("Could not locate a Bank Accounts group in the chart of accounts")
    print(f"company={company} abbr={abbr} parent_account={parent}")

    made_bank = made_acct = made_ba = made_grp = 0
    report = []

    # ------------------------------------------------------------ bank accounts
    for acc in data.get("bank_accounts", {}).get("accounts", []):
        if not acc.get("active"):
            continue
        alias = _norm(acc.get("alias_name")) or "Bank Account"
        bank_name, how = _derive_bank_name(acc)
        acct_no = _norm(acc.get("account_number"))
        balance = float(acc.get("current_balance") or 0)

        if not frappe.db.exists("Bank", bank_name):
            d = frappe.new_doc("Bank")
            d.bank_name = bank_name
            d.flags.ignore_permissions = True
            d.insert(ignore_permissions=True)
            made_bank += 1

        # GL account
        gl_name = alias if not alias.isdigit() else f"{bank_name} {alias[-4:]}"
        gl_full = f"{gl_name} - {abbr}"
        if not frappe.db.exists("Account", gl_full):
            a = frappe.new_doc("Account")
            a.account_name = gl_name
            a.parent_account = parent
            a.company = company
            a.is_group = 0
            a.account_type = "Bank"
            a.account_currency = "INR"
            a.flags.ignore_permissions = True
            a.insert(ignore_permissions=True)
            gl_full = a.name
            made_acct += 1

        # Bank Account master
        ba_title = gl_name
        if not frappe.db.exists("Bank Account", {"account_name": ba_title, "bank": bank_name}):
            ba = frappe.new_doc("Bank Account")
            ba.account_name = ba_title
            ba.bank = bank_name
            ba.company = company
            ba.account = gl_full
            ba.is_company_account = 1
            if acct_no:
                ba.bank_account_no = acct_no
            if _norm(acc.get("ifsc_code")):
                ba.branch_code = _norm(acc["ifsc_code"])
            if _norm(acc.get("branch_name")):
                ba.branch_name = _norm(acc["branch_name"])
            ba.flags.ignore_permissions = True
            ba.flags.ignore_mandatory = True
            ba.insert(ignore_permissions=True)
            made_ba += 1

        report.append({
            "mbb_id": acc.get("id"), "alias": alias, "bank": bank_name,
            "bank_name_source": how, "account_no": acct_no,
            "ifsc": _norm(acc.get("ifsc_code")), "gl_account": gl_full,
            "balance_in_mybillbook": balance,
            "opening_date": acc.get("opening_date"),
        })

    # ------------------------------------------------------------ cash in hand
    cash_bal = float(data.get("cash_n_bank", {}).get("cash_balance") or 0) \
        if isinstance(data.get("cash_n_bank"), dict) else 0.0
    if cash_bal:
        report.append({
            "mbb_id": "", "alias": "Cash in Hand", "bank": "", "bank_name_source": "",
            "account_no": "", "ifsc": "", "gl_account": f"Cash - {abbr}",
            "balance_in_mybillbook": cash_bal, "opening_date": "",
        })

    # -------------------------------------------------------- party categories
    cats = data.get("party_categories", {}).get("ledger_categories", [])
    for c in cats:
        nm = _norm(c.get("ledger_category_name"))
        if not nm or frappe.db.exists("Customer Group", nm):
            continue
        g = frappe.new_doc("Customer Group")
        g.customer_group_name = nm
        g.parent_customer_group = "All Customer Groups"
        g.is_group = 0
        g.flags.ignore_permissions = True
        g.insert(ignore_permissions=True)
        made_grp += 1

    frappe.db.commit()

    # ------------------------------------------------------------ reports out
    with open(DATA + "/bank_opening_balances.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mybillbook_id", "alias", "bank", "bank_name_source", "account_no",
                    "ifsc", "erpnext_gl_account", "balance_in_mybillbook", "opening_date"])
        for r in report:
            w.writerow([r["mbb_id"], r["alias"], r["bank"], r["bank_name_source"],
                        r["account_no"], r["ifsc"], r["gl_account"],
                        r["balance_in_mybillbook"], r["opening_date"]])

    users = data.get("users") or []
    if isinstance(users, dict):
        users = next((v for v in users.values() if isinstance(v, list)), [])
    with open(DATA + "/mybillbook_users.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_name", "role", "mobile_number", "email", "permission_count"])
        for u in users:
            w.writerow([u.get("user_name"), u.get("role"), u.get("mobile_number"),
                        u.get("email"), len(u.get("permissions") or [])])

    total = sum(r["balance_in_mybillbook"] for r in report)
    print("\n" + "=" * 56)
    print(f"  banks created        : {made_bank}")
    print(f"  GL accounts created  : {made_acct}")
    print(f"  Bank Accounts created: {made_ba}")
    print(f"  customer groups      : {made_grp}")
    print(f"  users reported       : {len(users)}  (NOT created)")
    print(f"\n  cash + bank recorded : {total:,.2f}  (NOT posted)")
    for r in report:
        print(f"     {r['alias'][:28]:30} {r['balance_in_mybillbook']:>14,.2f}  -> {r['gl_account']}")
    print("=" * 56)
