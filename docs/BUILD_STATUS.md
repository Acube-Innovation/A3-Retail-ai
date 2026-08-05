# A3 Retail — build status

App: `a3_retail` (the scope document calls it `mobicare`; every identifier was
renamed — see *Naming map* below). Bench site: `local`.

**Steps 1–24 of 26 are complete, migrated and tested: 604 tests pass.**

```bash
bench --site local migrate
bench --site local run-tests --app a3_retail          # 604 passing
bench --site local execute a3_retail.demo.install.run # idempotent demo seed
bench --site local execute a3_retail.demo.install.verify  # 26/26 checks pass
```

## Naming map (scope document → this app)

| Scope document | This app |
|---|---|
| app `mobicare` | `a3_retail` |
| modules `MobiCare *` | `A3 Retail *` (7 modules) |
| custom field prefix `mc_` | `a3_` |
| `MobiCare Settings` | `A3 Retail Settings` |
| role `MobiCare Admin` | `A3 Retail Admin` |
| realtime event `mobicare_dashboard_update` | `a3_retail_dashboard_update` |
| site `mobicare.local` | `local` |

Desk page routes are prefixed `a3-` (`a3-reception-desk`) to avoid collisions.

## Completed steps

| # | Step | Key artefacts |
|---|---|---|
| 1 | App scaffold | 7 modules, `utils/` (branch, imei, naming, permissions, gst), `api/`, `A3 Retail Settings`, roles created in `before_install` |
| 2 | Branch model | `Branch Profile` + auto-created warehouses, cost-center tree, Branch accounting dimension |
| 3 | Security | 15 roles, data-driven permission matrix (`setup/permissions.py`), Employee→User Permission sync, branch query conditions |
| 4 | Masters | Custom fields on Item/Serial No/Customer/Supplier, `Device Model`, IMEI register, `api.customer.get_or_create` |
| 5 | Accounts & GST | CoA additions, in/out-state GST templates, **RCM add/deduct pair**, modes of payment, TDS categories, margin scheme (Rule 32(5)) |
| 6 | Service masters | `Service Issue Type`, `Service TAT Policy`, `Technician Profile`, working-hours TAT engine (`a3_retail_service/tat.py`) |
| 7 | Job card | `Service Job Card` + 5 children, 18-state machine (`state.py`), totals, delay scheduler, list indicators |
| 8 | Estimate | `Service Estimate` + children, hashed single-use portal token, `/approve-estimate/<token>`, OTP store, revisions, Sales Order on approval |
| 9 | Money & delivery | Advance Payment Entry, service Sales Invoice (update_stock from Service Bay), OTP-verified delivery, refunds |
| 10 | Reception Desk | `/app/a3-reception-desk` — 6-step intake, scanner + camera, client-side image compression, signature pad, live rail |
| 11 | Workbench & parts | `/app/a3-technician-workbench` kanban with work timer; parts request -> Stock Request / Material Request, TAT pause and auto-resume, issue/return Stock Entries |
| 12 | POS & selling guards | `pos_extension.js` (P1–P9, patches `cur_pos` without forking POS), device-serial guard, min-price guard, sales-person rule, serial stamping on submit |
| 13 | Seasonal offers | `Seasonal Offer Campaign` -> standard Pricing Rules per branch warehouse, budget cap with auto-pause, approval flow, daily activate/expire |
| 14 | Device exchange | Grading engine, used Item + Serial No with the original IMEI, Purchase Receipt into Used Devices, margin-scheme resale, Exchange Adjustment payment |
| 15 | EMI finance | `Finance Partner`, `EMI Scheme`, `EMI Document Type`, `EMI Application` with document checklist, subvention posting, financier settlement |
| 16 | Warranty | `Warranty Registration`, extended-warranty plans with deferred revenue, `Warranty Claim`, `OEM Warranty Return`, renewal reminders |
| 17 | Stock & transfers | Cross-branch Stock Explorer page, `Stock Request` with in-transit (Add to Transit / End Transit) legs, approval limits |
| 18 | Damages & demurrage | `Stock Damage Report` with recovery routing, `Demurrage Charge` storage billing, dead-stock rules and provisioning |
| 19 | Courier & logistics | `Courier Partner`, `Courier Rate Card`, zone derivation from pincode, `Courier Dispatch`, delivery trips, delay scan |
| 20 | Footfall & CRM | `Branch Visit Log` with conversion linking, Lead capture, `Customer Feedback` (NPS), helpdesk SLA tiers and escalation ladder |
| 21 | Telecalling | `Telecalling Campaign` list generation, `Call Task`, `Call Disposition`, DNC handling, calling console API |
| 22 | Communication | Stream-separated senders, `WhatsApp Template`/`Communication Rule`/`Message Log`, `doc_events["*"]` dispatcher, opt-in + quiet-hours compliance, Meta Cloud provider |
| 23 | HR, incentives, assets | HRMS configuration (`setup/hr.py`), branch geofence on Employee Checkin, `Employee Incentive Scheme` + `Incentive Calculation Run` engine, Post to Payroll, asset custody and exit clearance |
| 24 | Print | `templates/print_formats/` base + thermal macro libraries, 2 print styles, branch letter heads with `before_print` selection, 24 print formats, QR/UPI/IRN helpers (`utils/qr.py`, `print_helpers.py`), PDF smoke test |

## Remaining steps (25–26)

25 Dashboards, control tower & reports · 26 Portal, payments, demo data,
UAT hardening.

Seams already in place for them: `Portal OTP` and `website_route_rules`
(step 26), `setup/permissions.py` `PERMISSION_MATRIX` and
`utils/permissions.py` `BRANCH_SCOPED_DOCTYPES` (append new doctypes),
`demo/install.py` (drop in `NN_topic.py`), `demo/verify.py` (`@check`).

## How to continue

DocTypes are generated, not hand-written, so the JSON stays consistent:

```bash
# scripts/gen_stepNN.py describes fields; run it with the bench python
/home/user/A3-Retail/env/bin/python apps/a3_retail/scripts/gen_step07.py
bench --site local migrate
```

`scripts/dtgen.py` exposes `DT`, `f`, `sb`, `cb` and writes JSON + controller +
client script + test stub. Controllers passed as `None` are never overwritten.

## Deviations from the scope document (and why)

These are places where the specification is internally inconsistent or conflicts
with how ERPNext v15 actually behaves. Each was resolved deliberately.

1. **Demo IMEIs fail the Luhn check.** Step 1's acceptance asserts
   `validate_imei("353912104567891") is True`, but that number's correct check
   digit is 5, not 1 — and most demo IMEIs in the pack are likewise invalid
   (`356938035643809` is the only valid one). Luhn is implemented correctly;
   demo seeding sets `frappe.flags.a3_bypass_imei_check`, and per-record
   override uses the `a3_imei_override` checkbox the scope itself describes.

2. **Demo GSTINs fail the statutory check digit**, which india_compliance
   enforces on save. `utils/gst.py` recomputes the 15th character, keeping the
   state code and PAN from the document (`32AABCM1234K1Z5` → `32AABCM1234K1ZV`).

3. **HSN codes.** The scope quotes 4-digit chapter headings (`8517`);
   india_compliance requires 6 or 8 digits, so the full tariff items are used
   (`85171300`, `84713010`, …).

4. **Accounting Dimension Detail is keyed by company, not doctype.** The scope
   lists per-doctype "mandatory for" rows; ERPNext throws *"Company added more
   than once"*. One row per company is created, and per-doctype coverage is
   enforced by `overrides/transactions.stamp_branch`.

5. **Store Keeper on Stock Entry.** The 13.2 matrix shows "–", contradicting the
   Stock Request row and the role description. Granted `CRUDS` — a store keeper
   who cannot post a transfer cannot do the job.

6. **RCM accounts.** india_compliance ships `Input Tax CGST RCM` /
   `Output Tax CGST RCM` under *Duties and Taxes*. Those are reused when present
   so its GST reports pick up the postings, rather than creating a parallel set.

7. **Warehouse count.** Step 2 expects 12 branch warehouses; the scope's own
   warehouse tree lists 10. Kozhikode is "Sales Only" so it gets no Service Bay
   — 11 leaf warehouses result.

8. **Material Request has no `branch` field.** The Branch accounting dimension is
   only added to accounting doctypes, so parts requests are tied to a branch
   through the service warehouse instead. Assignments are guarded with
   `meta.has_field("branch")`.

9. **Cancelling a Device Exchange now cancels its Purchase Receipt.** The scope
    describes creating the receipt but never unwinding it; without this a
    reversed exchange left phantom used-device stock in the branch.

10. **Pricing Rule priorities must differ.** The scope gives every campaign
    priority 1. ERPNext resolves overlapping rules by priority and raises
    `MultiplePricingRuleConflict` when two of equal priority match one item, so
    the demo campaigns are seeded with distinct priorities.

11. **Slabs sometimes band the count, not the percentage.** Scope 10.2's July
    table pays Sajeer the 40–59 rate on 55 jobs against a 60-job target — i.e.
    the slab is matched on the raw metric even though a target exists, while the
    sales scheme matches on achievement %. Neither can be inferred, so
    `Employee Incentive Scheme.slab_basis` makes the choice explicit.

12. **Per-employee incentive targets.** The same table gives Vipin ₹6,00,000 and
    Rafeeq ₹4,00,000 under one scheme whose headline target is ₹6,00,000.
    `Incentive Employee.monthly_target` carries the override.

13. **Two demo schemes pay a bonus no product spiff can express** — "₹150 if the
    EMI application is approved within 24 hours" (scheme 4) and "₹2,000 if the
    branch EW attach rate ≥ 25%" (scheme 3). `Incentive Product Spiff` is
    item/brand/group-based, so a `bonus_rule` / `bonus_value` /
    `bonus_threshold_percent` block was added to the scheme and its result is
    reported in the row's spiff column, which is where the July table puts it.
    EMI Application dates approvals rather than timestamping them, so "within 24
    hours" is read as *approved the same or next day*.

14. **A metric the scope's own list omits.** Scheme 5 pays per telecalling
    conversion; `metric` had no such option, so `Telecalling Conversions` was
    added alongside the ten listed.

15. **Demo attendance percentages are quantised.** July 2026 gives 25 marked
    days, so attendance moves in 2% steps (a half day is worth 1%). Sajeer 89 →
    88, Rijo 97 → 96 and Sneha 95 → 96; every gate outcome in the table is
    unchanged, including Sajeer failing the 90% gate with a zero payout.

16. **Back-dated job cards are imported, not walked.** Reproducing the July
    technician run needs 189 delivered repairs. Walking each through eight
    status hops would make the seed unusable, so `frappe.flags.a3_import_history`
    lets the state machine accept the state a historical document ended in — the
    same treatment ERPNext gives opening entries. `on_status_changed` now keeps a
    timestamp the document already carries instead of stamping `now`.

17. **PDF rendering needs the web server.** wkhtmltopdf fetches the site
    stylesheet over HTTP, so `setup.print_formats.smoke_test()` exits with
    `ConnectionRefusedError` on a bench with nothing serving. The sweep reports
    that as "no server" rather than a format failure, and the test suite renders
    HTML (all 24) rather than PDF so it stays fast and self-contained:

    ```bash
    bench serve --port 8000 &
    bench --site local execute a3_retail.setup.print_formats.smoke_test
    ```

## Testing notes

Two classes of test-isolation bug were found and fixed; both are worth knowing
about before adding tests:

- **Scheduler helpers must not commit.** `frappe.db.commit()` inside a scheduler
  function defeats `FrappeTestCase`'s per-test rollback and leaks fixtures into
  the site, which then surfaces as unrelated failures elsewhere. Use
  `a3_retail.utils.commit_if_not_testing()`.
- **Stock-moving tests need unique serials.** Submitting a Purchase Receipt makes
  ERPNext commit while reposting stock, so tests that share one IMEI become
  order-dependent. `tests/test_exchange.py` generates a fresh Luhn-valid IMEI per
  test — copy that pattern.

## Environment repairs applied to this site

The bench site had never completed the ERPNext setup wizard. Both fixes are
shipped as reproducible app code, not manual steps:

- `setup/company.py` — runs the wizard for the demo tenant (Mobile World Retail
  Pvt Ltd / MWR, FY 2026-27, Standard with Numbers CoA).
- `setup/repair.py` — installs missing base fixtures (Gender, Salutation…) and
  recreates DB columns for Custom Fields whose `ALTER TABLE` never ran
  (11 doctypes were affected, including `Contact.is_billing_contact`).

Leftover `_Test Fiscal Year *` records from an earlier run were re-created after
the real fiscal year was given a company, so ERPNext's own test fixtures still
resolve.
