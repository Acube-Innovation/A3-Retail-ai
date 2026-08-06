# A3 Retail — Administrator Guide

Everything an administrator needs after go-live: building a site, backups,
credentials, the GST routine and what to do when something breaks.

---

## 1. Building a site from scratch

```bash
# 1. Create the site and install the apps, in this order
bench new-site a3.local --db-name a3_retail
bench --site a3.local install-app erpnext
bench --site a3.local install-app hrms
bench --site a3.local install-app india_compliance
bench --site a3.local install-app a3_retail

# 2. Apply schema and the app's own configuration
bench --site a3.local migrate

# 3. Load the demo dataset (skip on a live tenant)
bench --site a3.local execute a3_retail.demo.install.run

# 4. Prove it
bench --site a3.local execute a3_retail.demo.install.verify
bench --site a3.local run-tests --app a3_retail
```

`install-app` creates the company, the branches, the roles and the permission
matrix; `migrate` is safe to re-run and re-applies every default. Nothing in
steps 1–2 is manual.

### What each command leaves behind

| Command | Creates |
|---|---|
| `install-app a3_retail` | 15 roles, 7 modules, A3 Retail Settings |
| `migrate` | custom fields, GST templates, HRMS config, print formats, letter heads, cards, charts, workspaces, report schedule |
| `demo.install.run` | 26 seed scripts — masters, then transactions, then dashboards |
| `demo.install.verify` | 33 checks; every one must pass before a hand-over |
| `demo.install.wipe` | removes demo *transactions* (developer mode only) |

---

## 2. Backup and restore

```bash
# Nightly, with files
bench --site a3.local backup --with-files

# Off-site copy (configure once in site_config.json)
bench --site a3.local set-config backup_limit 7
```

Restore:

```bash
bench --site a3.local --force restore /path/to/database.sql.gz \
	--with-public-files /path/to/files.tar \
	--with-private-files /path/to/private-files.tar
bench --site a3.local migrate
```

Always `migrate` after a restore — the backup carries the schema of the day it
was taken, not of the code you are running now.

**Keep the encryption key.** `site_config.json → encryption_key` decrypts every
stored password *and* signs the customer portal links. Losing it invalidates both.

---

## 3. Two front doors

| Who | Where | Account type |
|---|---|---|
| Branch staff — managers, technicians, reception, sales, store, telecalling | `/branch/login` | **Website User** — `/app` is refused |
| Head office — admin, accounts, HR, audit | `/app` (ERPNext desk) | System User |

Which door an account gets is decided by one thing: whether any role it holds has
**desk access**. `a3_retail/install.py` ships the shop-floor roles with
`desk_access = 0` and the head-office roles with `desk_access = 1`, and every
migrate re-applies that. Give a branch user a desk role and Frappe promotes them
back to a System User on the next save — that is the switch to watch.

```bash
# Turn branch employees into portal accounts (idempotent)
bench --site a3.local execute a3_retail.setup.staff_portal.provision

# Demo or UAT only — sets one password for every account it provisions
bench --site a3.local console
>>> from a3_retail.setup import staff_portal
>>> staff_portal.provision(password="branch@123")

# Put one account back in the desk
>>> staff_portal.revoke("arun@mobileworld.in")
```

Head-office employees are skipped automatically, and so is anyone holding
System Manager, A3 Retail Admin, Accounts Manager, HR Manager or Auditor.

The branch app is a **standalone front end**, not an ERPNext website page: the
documents under `a3_retail/www/branch/` extend nothing, load only
`assets/a3_retail/css/a3_branch.css` and `a3_branch.js`, and talk to ERPNext
purely through `/api/method/a3_retail.api.staff.*`. Swapping it for a separate
React or Next.js build later means pointing that build at the same endpoints —
nothing else in the app has to change.

**Consequence to plan for:** the desk pages built for the shop floor — Reception
Desk, Technician Workbench, Stock Explorer, Control Tower — are desk pages, so
branch staff can no longer open them. They are reachable by head-office accounts;
the branch app is where the equivalent screens belong.

## 4. Credentials and integrations

### WhatsApp (Meta Cloud API)

1. **A3 Retail Settings → Communication**: turn on *Enable WhatsApp*.
2. **WhatsApp Sender Profile** — one per stream (Sales, Service, EMI, Warranty,
   Helpdesk, Marketing). Each carries its own `phone_number_id` and access token.
3. Templates must be approved in Meta Business Manager under the same names as
   the **WhatsApp Template** records.
4. Webhook: `https://<site>/api/method/a3_retail.api.whatsapp.webhook`, with the
   verify token from A3 Retail Settings.
5. **Communication Rules ship inactive.** Turn them on one stream at a time and
   watch **WhatsApp Delivery Report** for two days before enabling Marketing.

Marketing messages respect the customer opt-in flag, quiet hours and a daily cap;
Utility messages (job card created, ready for delivery, invoice) always go out.

### Razorpay

1. **A3 Retail Settings → Portal**: set *Razorpay Key ID*, *Razorpay Webhook
   Secret*, the UPI VPA, and turn on *Enable Online Payment*.
2. Configure the webhook in the Razorpay dashboard to
   `https://<site>/api/method/a3_retail.api.payments.razorpay_webhook` for
   `payment.captured` and `payment.failed`.
3. A captured payment creates a Payment Entry and allocates it to the invoice.
   Anything the gateway reports but we cannot match appears in
   `a3_retail.api.payments.unmatched_transactions` — check it weekly.

### Email

Set up an outgoing Email Account per branch if the shop wants replies to land in
the branch inbox; otherwise one account for the company is enough. The ten
scheduled reports are created **disabled** — enable them once the recipient lists
are right.

---

## 5. The monthly GST routine

| Day | Task | Where |
|---|---|---|
| 1st | Freeze the previous month's postings | Accounts Settings → *Books closed until* |
| 2nd | Reconcile sales | **Branch Sales Register**, **IMEI Sales Register** |
| 3rd | Reverse-charge review | **RCM Liability and ITC Register** |
| 4th | Margin-scheme devices | **Margin Scheme Register** |
| 5th | File GSTR-1 | india_compliance → GSTR-1 |
| 10th | Reconcile GSTR-2B, then file 3B | india_compliance → GSTR-3B |
| 12th | EMI settlements | **Settlement Reconciliation** |
| 15th | Incentives and payroll | **Incentive Payout Register**, Payroll Entry |

Reverse charge posts an add/deduct pair on the same purchase invoice, so the
liability and the input credit both appear and net to zero in the P&L.

---

## 6. Scheduled jobs

| When | What |
|---|---|
| Hourly | delayed job cards, courier delays, SLA escalation, message retries, quiet-hours release |
| Daily | warranty states, auto-close delivered jobs, expire estimates, campaign statuses, EMI nudges, renewal reminders, storage charges, absent marking, OTP cleanup |
| Weekly | OEM return ageing, stuck transfers, dead-stock ToDos, calibration reminders |

Check they are running with `bench --site a3.local doctor`. A stopped scheduler
is the usual reason "reminders stopped working".

---

## 7. Health checks

```bash
# Everything the app promises, verified against live data
bench --site a3.local execute a3_retail.demo.install.verify

# Every report executes and none is slower than three seconds
bench --site a3.local execute a3_retail.setup.reports.smoke_test

# Every print format renders (needs `bench serve` running for the PDF pass)
bench --site a3.local execute a3_retail.setup.print_formats.smoke_test

# Every whitelisted endpoint checks a permission
bench --site a3.local execute a3_retail.setup.audit.run
```

---

## 8. Common problems

| Symptom | Cause | Fix |
|---|---|---|
| "IMEI is not valid" on a genuine device | The IMEI fails its Luhn check digit | Re-scan; if the print on the box really is wrong, tick *Override IMEI Check* (Admin only) |
| A branch user sees another branch's data | Employee has no branch, or a head-office role | Set Employee → Branch, then `bench execute a3_retail.overrides.employee.resync_all` |
| WhatsApp messages queue but never send | Sender profile inactive or token expired | Check **WhatsApp Message Log** → error column |
| Payment received but the invoice is still open | Webhook not reaching us | Check the Razorpay dashboard's webhook log, then `unmatched_transactions` |
| Reports empty for a branch manager | User Permission missing | Same fix as the branch-data problem above |
| A print format renders blank | The document has no data for that layout | Check the format is for the right doctype in the Print settings |
| PDF download fails on a fresh bench | wkhtmltopdf cannot fetch the stylesheet | Ensure the web server is running and `host_name` resolves |

---

## 9. Where things live

| Concern | Path |
|---|---|
| App configuration on every migrate | `a3_retail/setup/install_defaults.py` |
| Branch staff app | `a3_retail/www/branch/`, `a3_retail/api/staff.py` |
| Who gets the desk | `a3_retail/install.py` (`A3_ROLES`), `setup/staff_portal.py` |
| Roles and the permission matrix | `a3_retail/setup/permissions.py` |
| Print templates | `a3_retail/templates/print_formats/` |
| Portal pages | `a3_retail/templates/pages/` |
| Reports | `<module>/report/<name>/` |
| Demo dataset | `a3_retail/demo/NN_topic.py` |
| Deviations from the specification | `docs/BUILD_STATUS.md` |
