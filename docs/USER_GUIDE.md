# A3 Retail — User Guide

For the people who use the system every day. Each section is written for one
role: find yours, and everything you need is in that section.

Screens marked *(screenshot)* are where a picture belongs in the printed manual.

---

## 1. Reception Executive

### Taking in a repair — the 60-second intake

1. Open **Reception Desk** (`/app/a3-reception-desk`) *(screenshot)*.
2. **Customer** — type the mobile number. A known customer fills in
   automatically; a new one is created as you type the name.
3. **Device** — scan or type the IMEI. If we sold the handset, the system says so
   and shows the warranty status; you do not have to ask for the bill.
4. **Complaint** — tap the chips that match ("no charging", "screen broken"), and
   add anything the customer says in their own words.
5. **Condition** — tick the accessories handed in, photograph the device (front,
   back, screen on) and note visible damage. This is what protects the shop if
   the customer disputes a scratch later.
6. **Consent and signature** — read out the data-loss line, take the signature on
   screen, and press **Create Job Card**.

The thermal receipt prints automatically and the customer gets a WhatsApp with a
tracking link.

### Answering "is my phone ready?"

Search the mobile number in the Reception Desk header, or open the job card and
read the status. Never promise a date the job card does not show — the promised
date on screen is the one the customer received in writing.

### Handing the device back

1. Open the job card, press **Deliver**.
2. Ask for the OTP that was sent to the customer's phone; type it in.
3. Take the receiver's name, ID reference and signature.
4. Collect the balance shown as **Customer Payable** and print the delivery note.

---

## 2. Technician

### Your workbench

**Technician Workbench** (`/app/a3-technician-workbench`) shows only your jobs,
in columns by status *(screenshot)*. Drag a card to move it; the timer starts
when you begin work and pauses when you put a job on hold.

### Diagnosis and estimate

1. Open the card, write the **diagnosis** and the **root cause**.
2. Add the parts you need. If a part is not in your branch, the row tells you
   which branch has it — press **Request** and the store keeper takes over.
3. Add labour lines, then press **Create Estimate**. The customer receives a
   WhatsApp link and approves on their phone; you will see the status change.

### While you wait for a part

Put the job **On Hold — Awaiting Parts**. The TAT clock stops while it is on
hold, so a delay outside your control does not count against you.

### Finishing

Move the card to **QC Pending**. Once QC passes, the card goes to
**Ready for Delivery** and reception takes over.

---

## 3. Sales Executive

### Selling a phone

1. Open **POS**. Scan the item, then scan the IMEI — the sale will not submit
   without it.
2. Offers apply automatically. If the price looks wrong, check the offer chip on
   the line before overriding anything.
3. **Exchange** — press *Exchange*, grade the old device by answering the
   questions, and the value is deducted from the bill.
4. **EMI** — press *EMI*, pick the scheme, and collect the documents on the
   checklist. The sale cannot be submitted until the financier approves.
5. **Extended warranty** — offer the plan before printing. The attach rate is on
   your incentive.

### Checking stock in another branch

**Stock Explorer** (`/app/a3-stock-explorer`) shows every branch's stock for a
model, and turns a row into a transfer request in one click.

### Your incentive

Your branch manager runs the incentive calculation each month. Your payout
depends on the slab you reach, the spiffs on specific products, and three gates:
attendance ≥ 90%, CSAT ≥ 4.0, and returns clawed back. A gate failure means the
slab pays nothing — the spiffs still do.

---

## 4. Store Keeper

- **Stock Request** — requests from other branches land here. Approve, then
  press **Dispatch**; the stock moves to In Transit and only leaves your books
  when the receiving branch presses **Receive**.
- **Purchase Receipt** — receive against the purchase order, scan each IMEI.
- **Stock Damage Report** — photograph the damage, pick who is responsible, and
  submit. Recovery from an employee flows to payroll automatically.
- **Awaiting Parts Register** (report) — run this every morning; it is the list
  of jobs waiting on you.

---

## 5. Branch Manager

### The screen to keep open

**Service Control Tower** (`/app/a3-control-tower`) *(screenshot)*:

- the counters across the top are today's numbers, refreshed live;
- red rows in the job board are past their promised time;
- **Parts Position** tells you what to chase;
- **Technician Load** tells you who is free;
- the bottom strip compares your branch with the others.

### Approvals that wait for you

- Stock requests above the auto-approve limit
- Discounts below the minimum selling price
- Damage write-offs
- Incentive calculation runs before they post to payroll

### Month end

1. Run **Incentive Calculation Run** for each scheme, press **Calculate**, check
   the gate column, submit, then **Post to Payroll**.
2. Run **Branch Profitability Statement** and read it against last month.
3. Check **Stock Ageing and Dead Stock** and act on anything over 90 days.

---

## 6. Accounts Manager

- **GST** — invoices carry HSN codes and the correct in-state or out-of-state
  template. Reverse-charge purchases post the add/deduct pair automatically;
  reconcile with **RCM Liability and ITC Register**.
- **Margin scheme** — second-hand devices sold under Rule 32(5) appear in the
  **Margin Scheme Register**; GST applies to the margin, not the sale value.
- **EMI** — **Financier Receivable Ageing** shows what each partner owes;
  **Settlement Reconciliation** matches their payout against our expectation.
- **Branch P&L** — every posting carries a Branch dimension, so every financial
  report can be run per branch or consolidated by clearing the filter.

---

## 7. Helpdesk Agent and Telecaller

- **Issue** — every complaint, with an SLA clock. Breaches escalate on their own:
  agent → service manager → branch manager → head office.
- **Telecalling Console** — your queue for the day, with the customer's history
  beside the dial button. Record the disposition after every call; "Do Not Call"
  removes the number from every future campaign.
- **Customer Feedback** — a rating of 2 or below opens an Issue automatically and
  the branch manager is notified.

---

## 8. HR Manager

- **Attendance** — check-ins are geofenced to the branch. Staff who legitimately
  work away from the shop are marked *Exempt from Geofence* on their Employee
  record.
- **Payroll** — one Payroll Entry per company per month; salary lands in the
  branch cost centre through the employee's payroll cost centre.
- **Incentives** — Additional Salary rows created by an incentive run appear on
  the payslip for that month.
- **Assets** — an employee cannot be marked *Left* while an asset is still in
  their name. Record the return with an Asset Movement first.

---

## 9. What the customer sees

| Page | Link | What it does |
|---|---|---|
| Track Service | `/track-service` | Status timeline after an OTP check |
| Approve Estimate | `/approve-estimate/<token>` | Approve, reject or ask for a revision |
| Warranty Certificate | `/warranty/<token>` | Certificate and PDF download |
| Pay Online | `/pay/<token>` | UPI or card payment for what is due |
| Invoice | `/invoice/<token>` | Tax invoice PDF |
| Raise a Complaint | `/support` | Creates a ticket after an OTP check |
| Feedback | `/feedback/<token>` | Stars, NPS and comments |
| Offers | `/offers` | Running campaigns |
| Stores | `/stores` | Addresses, hours and directions |

Links are personal — a customer only ever sees their own document, and the token
in the link is what proves it.
