# A3 Retail

A Frappe/ERPNext v15 app: mobile retail and service chain management for a
multi-branch shop in Kerala. One app, seven modules. ERPNext keeps the ledgers;
this is the shop's way of working with them.

Read `docs/ARCHITECTURE.md` before adding anything structural, and
`docs/DEPLOYMENT.md` before touching the install path.

## The rules

1. **A `www/` page is a shell.** Guard the session, build a context, render HTML
   — no queries, no business logic. Every one of the 17 is ~35 lines; copy
   `www/branch/emi.py`.
2. **The browser only calls `api/*`.** Every whitelisted endpoint opens with
   `_me()` or `require_permission`. `setup/audit.py` reads the source at test
   time and fails the build otherwise.
3. **`api/*` orchestrates; the doctype posts.** Call the document that owns the
   rule — Sales Invoice, Financier Settlement, `a3_retail_service.parts`. Never
   write a GL or stock ledger entry by hand, and never build a second invoice,
   payment or stock system.
4. **Never create anything through the desk UI.** Doctypes go in
   `<module>/doctype/`, fields on ERPNext doctypes go in
   `setup/custom_fields.py`, permissions in `setup/permissions.py`. A record made
   in a browser is invisible to git and missing from a fresh install.
5. **Branch scopes everything.** `_me()` gives the employee's branch; refuse
   another branch's document by name.
6. **Messages are for the person at the counter.** Say what is wrong and what to
   do about it — never a field name, a rule number or an exception class.

## Working here

- Tests: `bench --site local run-tests --app a3_retail` (1012, all passing).
  Every change gets one; put doctype tests beside the doctype and page/API tests
  in `tests/test_<thing>.py`.
- Migrations for live sites: `patches/x.py` + a line in `patches.txt`.
- Demo data lives in `demo/` and never runs on a customer's site.
- The branch app's design language is `public/css/a3_branch.css` — reuse
  `.svc-panel`, `.ctile`, `.pill`, `.bill-table`, `.modal`, `.toast`. Desk pages
  use `public/css/a3_retail.css` instead; the two are separate on purpose.
- After changing branch CSS or JS, nothing else is needed: `asset_version()`
  busts the cache from file mtimes.

## Layout

```
a3_retail_*/        seven ERP modules — doctype/, report/, page/
www/branch/         the branch app (/branch/*)
api/                whitelisted endpoints, one module per screen
setup/              installers, re-run on every migrate
templates/          print formats and portal pages
public/css | js/    a3_branch.css (branch) · a3_retail.css (desk)
patches/ demo/ tests/ utils/ overrides/
```
