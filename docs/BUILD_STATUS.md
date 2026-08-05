# A3 Retail — build status

App: `a3_retail` (the scope document calls it `mobicare`; every identifier was
renamed — see *Naming map* below). Bench site: `local`.

**Steps 1–14 of 26 are complete, migrated and tested: 240 tests pass.**

```bash
bench --site local migrate
bench --site local run-tests --app a3_retail          # 240 passing
bench --site local execute a3_retail.demo.install.run # idempotent demo seed
bench --site local execute a3_retail.demo.verify.run  # 17/17 checks pass
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

## Remaining steps (15–26)

15 EMI finance · 16 Warranty · 17 Stock explorer & transfers ·
18 Damages/demurrage · 19 Courier & logistics · 20 Footfall/CRM ·
21 Telecalling · 22 Communication engine · 23 HR & incentives · 24 Print
formats · 25 Dashboards & reports · 26 Portal, payments, demo data, hardening.

Seams already in place for them: `communication/engine.py` +
`communication/dispatch.py` (step 22), `Portal OTP` and `website_route_rules`
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

8. **Store Keeper on Stock Entry** — see 5 above.

9. **Material Request has no `branch` field.** The Branch accounting dimension is
   only added to accounting doctypes, so parts requests are tied to a branch
   through the service warehouse instead. Assignments are guarded with
   `meta.has_field("branch")`.

10. **Cancelling a Device Exchange now cancels its Purchase Receipt.** The scope
    describes creating the receipt but never unwinding it; without this a
    reversed exchange left phantom used-device stock in the branch.

11. **Pricing Rule priorities must differ.** The scope gives every campaign
    priority 1. ERPNext resolves overlapping rules by priority and raises
    `MultiplePricingRuleConflict` when two of equal priority match one item, so
    the demo campaigns are seeded with distinct priorities.

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
