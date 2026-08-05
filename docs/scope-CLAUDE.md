# CLAUDE.md — MobiCare ERPNext Project

You are building a **custom Frappe app named `mobicare`** on top of ERPNext v15 for a multi-branch
mobile phone retail + service chain in India.

## Golden rules — read before writing any code

1. **Never modify ERPNext or Frappe core files.** Extend only via:
   - Custom DocTypes inside the `mobicare` app
   - `Custom Field` and `Property Setter` created through **`fixtures`** in `hooks.py` (never manual-only)
   - `doc_events` hooks, `override_doctype_class`, Client Scripts shipped as fixtures
2. **Do not name any DocType `Job Card`** — that name is taken by ERPNext Manufacturing. Our doctype is
   **`Service Job Card`**. Similarly avoid: `Warranty Claim` (exists — extend it), `Branch` (exists in HRMS —
   extend it via `Branch Profile`), `Delivery Trip` (exists — use it), `Call Log` (exists — link to it).
3. **Single Company, multi-Branch.** Do NOT create one Company per branch. Branch isolation is achieved by
   Warehouse + Cost Center + Accounting Dimension + User Permission. See `00-ARCHITECTURE.md`.
4. **All money movement must go through standard ERPNext documents** (Sales Invoice, Payment Entry,
   Journal Entry, Stock Entry). Custom DocTypes orchestrate; they never post GL/SLE directly.
5. **Every custom DocType** must have: naming series, `Branch` link field, standard permission rules,
   a list-view indicator, and a `docstatus` workflow where a state machine is described.
6. **All numeric/currency fields** use `precision=2` for currency and `Float` for qty; never `Data`.
7. **Idempotent patches.** Every seeding/migration script lives in `mobicare/patches/` and must be safe to
   re-run (`if frappe.db.exists(...)` guards).
8. **Write tests.** Each module gets `test_<doctype>.py` covering the happy path + one validation failure.
9. **Commit per step.** Use the commit message given in `docs/scope/15-CLAUDE-CODE-PROMPTS.md`.
10. **Language/stack:** Python 3.11, Frappe v15 (Bootstrap 4 + Vue 3 for custom pages), MariaDB 10.6,
    Redis. Custom desk pages use Frappe's `frappe.ui.Page` + Vue 3 SFC-less components (no build step
    unless the step explicitly says to add esbuild bundles).

## Repository layout to create

```
mobicare/
├── mobicare/
│   ├── hooks.py
│   ├── modules.txt
│   ├── patches.txt
│   ├── install.py
│   ├── setup/                       # after-install setup: roles, warehouses, accounts
│   ├── mobicare_service/doctype/
│   ├── mobicare_sales/doctype/
│   ├── mobicare_finance/doctype/
│   ├── mobicare_warranty/doctype/
│   ├── mobicare_communication/doctype/
│   ├── mobicare_operations/doctype/
│   ├── mobicare_dashboard/page/
│   ├── public/js/                   # POS extensions, form scripts
│   ├── public/css/
│   ├── templates/pages/             # customer web portal
│   ├── print_format/
│   ├── report/
│   ├── patches/
│   └── api/                         # whitelisted endpoints
├── docs/scope/                      # this scope pack
└── README.md
```

## Module registration (`modules.txt`)

```
MobiCare Service
MobiCare Sales
MobiCare Finance
MobiCare Warranty
MobiCare Communication
MobiCare Operations
MobiCare Dashboard
```

## Required apps on the bench

| App | Repo | Why |
|---|---|---|
| frappe | frappe/frappe (v15) | framework |
| erpnext | frappe/erpnext (v15) | core ERP |
| hrms | frappe/hrms (v15) | attendance, payroll, travel, expense |
| india_compliance | resilient-tech/india-compliance | GST, e-Invoice, e-Way Bill, RCM |
| payments | frappe/payments | Razorpay/PayU gateway |
| mobicare | this repo | custom |

## Conventions

- **Naming series:** `<PREFIX>-{branch_code}-.YY.-.#####` — branch_code is fetched from `Branch Profile`.
- **Fieldnames:** snake_case, prefix custom fields on core doctypes with `mc_` (e.g. `mc_branch_profile`)
  to avoid collision with future ERPNext fields. Custom DocType own fields need no prefix.
- **Whitelisted APIs** live in `mobicare/api/<domain>.py`, always decorated with
  `@frappe.whitelist()` and an explicit permission check (`frappe.has_permission`).
- **Never use `ignore_permissions=True`** except in scheduler jobs, and log why in a comment.
- **Client scripts** shipped as fixtures filtered by `dt` in `hooks.py`.

## Definition of done for each step

- [ ] DocTypes created with all fields, types, options, depends_on, and mandatory flags per spec
- [ ] `bench --site <site> migrate` runs clean
- [ ] Fixtures exported (`bench --site <site> export-fixtures`)
- [ ] Demo data patch runs and creates the sample rows listed in the step
- [ ] Validation SQL from the step returns the expected counts
- [ ] Tests pass: `bench --site <site> run-tests --app mobicare`
- [ ] Committed with the specified message
