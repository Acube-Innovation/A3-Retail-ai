# Deploying A3 Retail to a new instance

A3 Retail is one Frappe app. Everything it owns — 74 doctypes, 42 reports, the
branch app at `/branch`, 25 print formats, 149 custom fields, the roles and the
whole permission matrix — is a file in this repository. Nothing lives only in a
database, which is what makes a new site reproducible.

## What the site needs first

| App | Why |
|---|---|
| `frappe` | the framework |
| `erpnext` | Customer, Item, Sales Invoice, Payment Entry, Employee, Branch, Warehouse — the ledgers this app is a layer over |
| `india-compliance` | GST accounts, HSN on Item, state codes, RCM |
| `hrms` | Attendance, Employee Checkin, Shift Type, Payroll — the attendance geofence and incentive payouts |

All four are declared in `required_apps`, so bench refuses to install A3 Retail
without them. Match the branch of erpnext to the branch of frappe (v15 with v15).

## Install

```bash
cd $BENCH
bench get-app https://github.com/frappe/hrms --branch version-15
bench get-app https://github.com/resilient-tech/india-compliance --branch version-15
bench get-app <a3_retail repo url>

bench new-site shop.example.com --db-root-password <root> --admin-password <pw>
bench --site shop.example.com install-app erpnext india_compliance hrms a3_retail
bench --site shop.example.com migrate
```

`install-app` order matters: a3_retail last, because its installer reads the
doctypes the others bring.

## What the install creates

`after_install` runs `a3_retail.setup.install_defaults.run()`, which is also
re-run by `after_migrate`, so every deploy re-asserts it. It is idempotent —
running it twice changes nothing:

| Step | Creates |
|---|---|
| `install.create_roles` | the 15 A3 roles; shop-floor roles get `desk_access = 0` |
| `setup.custom_fields` | 149 custom fields, skipping any whose doctype is absent |
| `setup.accounts` | the head-office cost center, once a Company exists |
| `setup.tax` | GST and RCM accounts, tax templates |
| `setup.helpdesk`, `setup.hr` | issue types, shift types, asset categories |
| `setup.print_formats` | 2 print styles, 25 print formats, a letter head per branch |
| `setup.dashboards` | 20 number cards, 15 charts, the A3 Retail Home workspace |
| `setup.reports` | the report register and 10 scheduled deliveries, created **disabled** |
| `setup.staff_portal` | the portal role, and closes the desk to shop-floor roles |
| `setup.permissions` | the whole role/permission matrix |

**No Company, Branch, Customer or Item is created.** A new tenant starts empty,
which is deliberate: `setup/company.py` names a demo company and is reached only
from the test bootstrap and `demo/01_company.py`, never from the install path.

There are no fixtures. Every record above is built in code, on purpose — see the
comment where the `fixtures` hook used to be in `hooks.py`.

## What a new tenant configures afterwards

In this order, because each step depends on the one above:

1. **Company** — through ERPNext's setup wizard, with the right GSTIN and fiscal
   year.
2. **Branches** — one `Branch` per shop.
3. **Branch Profile** — per branch: company, cost centers, warehouses (store,
   service bay, transit), address, GSTIN, state code. Print letter heads and the
   branch scoping both read this.
4. **Warehouses and Modes of Payment** — Cash, Card, UPI and any EMI mode a
   finance partner settles through.
5. **Employees**, each with a `branch`, then
   `bench --site <site> execute a3_retail.setup.staff_portal.provision` to turn
   them into branch-app logins.
6. **Masters as the shop needs them** — Item groups and items, Device Models,
   Service Issue Types, TAT policies, Finance Partners and EMI Schemes.

Then `bench --site <site> execute a3_retail.setup.install_defaults.run` once more
so the letter heads pick up the branches that now exist.

## Demo data

`demo/` seeds a whole fictional chain — company, branches, staff, stock, a year
of transactions. It is for sales demos and UAT, never for a customer's site:

```bash
bench --site demo.example.com execute a3_retail.demo.install.run
bench --site demo.example.com execute a3_retail.demo.verify.run
```

## Verifying a deploy

```bash
bench --site <site> execute a3_retail.setup.audit.run       # every endpoint guarded
bench --site <site> execute a3_retail.setup.permissions.run # matrix applied
bench --site <site> run-tests --app a3_retail               # 1012 tests
```

Then open `/branch/login` — it should render, and refuse any account not linked
to an active Employee with a branch.

## Upgrading an existing instance

```bash
cd $BENCH/apps/a3_retail && git pull
bench --site <site> migrate
```

`migrate` runs the patches in `patches.txt` and then `after_migrate`, which
re-asserts everything in the table above. Site data is never touched by an
upgrade — the app only adds and updates the records it owns.
