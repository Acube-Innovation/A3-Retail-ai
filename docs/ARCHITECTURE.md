# How A3 Retail is put together

One app, layered over ERPNext. ERPNext keeps the ledgers — customers, items,
stock, invoices, payments, accounts — and A3 Retail is the shop's own way of
working with them: screens the counter can use, documents the business needs
that ERPNext has no name for, and the rules that make a chain of branches behave
like one company.

## The tree

```
apps/a3_retail/a3_retail/
├── hooks.py                    wiring: assets, doc_events, routes, scheduler, permissions
├── modules.txt                 the seven ERP modules
├── install.py                  before_install / after_install / after_migrate
│
├── a3_retail_service/         ┐
├── a3_retail_sales/           │  the ERP layer — each module holds
├── a3_retail_finance/         │    doctype/<name>/   record types + their rules
├── a3_retail_warranty/        │    report/<name>/    query and script reports
├── a3_retail_operations/      │    page/<name>/      desk pages
├── a3_retail_communication/   │
├── a3_retail_dashboard/       ┘  74 doctypes · 42 reports · 4 desk pages
│
├── www/branch/                 the branch app — 17 pages served at /branch/*
├── templates/pages/            customer portal — /track-service, /pay/<token>
├── templates/print_formats/    25 documents over one a3_base.html
├── public/css | js/            a3_branch.css (branch app) · a3_retail.css (desk)
│
├── api/                        20 whitelisted modules — the only thing the browser calls
├── setup/                      installers: permissions, print_formats, dashboards, audit…
├── utils/ overrides/ communication/ hr/
├── patches/ + patches.txt      migrations for sites already live
├── demo/                       26 seed scripts + verify (never on a customer site)
└── tests/                      38 modules, 1012 tests
```

## The three kinds of screen

| Kind | Lives in | Served at | Looks like |
|---|---|---|---|
| Branch app — Sales POS, Service POS, Bills, EMI, Stock, Parts | `www/branch/<name>.html` + `.py` | `/branch/<name>` | its own design language, `a3_branch.css` |
| Desk page — Reception Desk, Technician Workbench, Control Tower | `<module>/page/<name>/` | `/app/<name>` | inside ERPNext's chrome, `a3_retail.css` |
| Customer portal — track a repair, pay a link | `templates/pages/` + `website_route_rules` | `/track-service`, `/pay/<token>` | the website theme |

The branch app is deliberately standalone: no `{% extends "templates/web.html" %}`,
no desk bundle, its own CSS and one small `A3` helper for calling the server. It
is the only door for shop-floor staff, whose roles have `desk_access = 0`.

## The rules that keep the layers apart

**1. A `www/` page is a shell.** It guards the session, builds a context and
renders HTML. It does not query, and it holds no business logic. Every one of the
17 is about 35 lines — see `www/branch/emi.py`.

**2. The browser only ever calls `api/*`.** One module per screen (`api/emi.py`,
`api/bills.py`, `api/stock_control.py`…). Every endpoint opens with `_me()` or
`require_permission`, and `setup/audit.py` reads the source at test time and
fails the build if one does not.

**3. `api/*` orchestrates; it never posts.** It calls the document that owns the
rule — the Sales Invoice for a sale, the Financier Settlement for its Journal
Entry, `a3_retail_service.parts` for issuing a part. Tests assert this per
module: `api/emi.py` may not construct a Payment Entry, `api/parts_desk.py` may
not write a Stock Entry.

**4. Business rules live on the doctype**, in `<module>/doctype/<name>/`, beside
its own tests.

**5. Nothing is created through the desk UI.** A doctype, custom field or client
script made in a browser is invisible to git and absent from a fresh install.
The check is `DocType where custom = 1`, and it returns nothing.

**6. Branch is the dimension everything is scoped by.** `_me()` gives the
signed-in employee's branch; list views are narrowed by the
`permission_query_conditions` in hooks.py; `stamp_cost_center` puts the branch
cost center on every posting.

## Where a new thing goes

| Adding | Goes in |
|---|---|
| A screen for branch staff | `www/branch/x.html` + `x.py`, `public/js/a3_x.js`, an entry in `_sidebar.html` |
| Its server side | `api/x.py` — whitelisted, guarded, thin |
| A new record type | `a3_retail_<module>/doctype/<name>/` + controller + test |
| A field on an ERPNext doctype | `setup/custom_fields.py` — never the UI |
| A report | `a3_retail_<module>/report/<name>/`; it appears in `/branch/reports` on its own |
| A printable document | `templates/print_formats/x.html` + a row in `setup/print_formats.py` |
| Roles and permissions | `setup/permissions.py`, the `PERMISSION_MATRIX` |
| Something existing sites need | `patches/x.py` + a line in `patches.txt` |
| Demo data | `demo/NN_x.py` + a check in `demo/verify.py` |
| Anything at all | a test in `tests/` |

## Why there are no fixtures

Every customisation is *built* by a `setup/` module on install and again on
every migrate — custom fields, print formats, letter heads, cards, charts, the
workspace, scheduled reports, roles, permissions. Exporting the same records as
fixtures would give each of them two sources that drift, and two are
tenant-shaped: letter heads are generated per Branch Profile, and Auto Email
Reports carry a site's own recipients. A fixture export from a developer's
machine would ship one shop's branches to another shop.

See `docs/DEPLOYMENT.md` for what an install actually creates.
