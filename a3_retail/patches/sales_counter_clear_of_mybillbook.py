# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Move the sales counter clear of the numbers myBillBook has issued.

PhoneXpert are billing in both books while the cutover runs, and both books
bill under one GSTIN. `mbb_series_counters` set the counter once, to the 2064
myBillBook had reached on 5 November; myBillBook has gone on issuing numbers
since, and ERPNext has issued 2065 upward against the same series. Any number
both books have used is two different tax invoices with one number, which is
the shop's problem at return time, not ERPNext's.

So this lifts the counter clear: the next ERPNext bill takes a number above
anything myBillBook can have reached, and the two books stop overlapping from
here on.

What this does **not** do is repair the overlap already made. Numbers both
books have issued are printed for someone to compare against myBillBook's own
register; nothing on a bill already written is changed by this patch.

Two guards, because a counter is easy to get wrong in the dangerous direction:

* **It only ever rises.** A stale number, or a re-run on a site that has gone
  further, leaves the counter alone rather than walking it back over bills
  that exist.
* **It never lands under this site's own highest bill.** Even if the number
  below is wrong, the counter cannot be set somewhere that would reissue a
  number ERPNext has already given a customer.

When myBillBook moves again, update LAST_ISSUED and re-run — delete this
patch's row from the Patch Log first, since Frappe runs a patch once per site.
"""

import frappe

from a3_retail.utils.mbb_series import FY

# The last number myBillBook had issued on each series. Read it off
# myBillBook's own register, not from here.
#   ("PT", "SL") is sales at PhoneXpert The Digital store -> Sales PSLA + UK
#   ("PD", "SL") is sales at Digital Store & Care        -> Accessories UK
LAST_ISSUED: dict[tuple[str, str], int | None] = {
	("PT", "SL"): 2135,
	("PD", "SL"): 5442,
}

# Clearing today's number is not enough: myBillBook is still live, so the
# counter has to clear whatever it reaches before the shop stops billing
# there. Over 1 Oct - 21 Nov 2026 myBillBook issued 230 PT sales bills and
# 1150 PD ones, about 2.5 and 12.5 a day, so these are roughly six weeks and
# one month of cover. Cut them to nil if ERPNext is going live the same day.
HEADROOM: dict[tuple[str, str], int] = {
	("PT", "SL"): 100,
	("PD", "SL"): 400,
}


def execute():
	wanted = {k: v for k, v in LAST_ISSUED.items() if v}
	if not wanted:
		print("  no myBillBook numbers given — counter left alone. Put the last "
		      "number myBillBook issued into LAST_ISSUED and re-run.")
		return

	for (prefix, code), last in wanted.items():
		_lift(prefix, code, int(last), HEADROOM.get((prefix, code), 0))


def _lift(prefix: str, code: str, last: int, headroom: int):
	series = f"{prefix}/{code}/{FY}/"
	target = last + headroom
	ours = _highest_here(series)
	if ours > target:
		# Our own book has gone further than the number given. Trust the
		# documents in front of us over a figure typed in from elsewhere.
		print(f"  {series}: this site has already issued {ours}, past the "
		      f"{last} given — counter held at {ours}")
		target = ours

	current = _counter(series)
	if current is None:
		frappe.db.sql("insert into tabSeries (name, current) values (%s, %s)",
		              (series, target))
		print(f"  {series}: started at {target}, next bill is {target + 1}")
	elif current < target:
		frappe.db.sql("update tabSeries set current = %s where name = %s",
		              (target, series))
		print(f"  {series}: lifted {current} -> {target}, next bill is {target + 1}")
	else:
		print(f"  {series}: already at {current}, above {target} — left alone")

	_name_the_overlap(prefix, code, last)


def _counter(series: str):
	row = frappe.db.sql("select current from tabSeries where name = %s", series)
	return int(row[0][0] or 0) if row else None


def _highest_here(series: str) -> int:
	"""The largest number this site has actually put on a bill in that series."""
	numbers = [
		int(tail) for (tail,) in frappe.db.sql("""
			select substring(name, %s) from `tabSales Invoice` where name like %s
		""", (len(series) + 1, series + "%"))
		if str(tail).isdigit()
	]
	return max(numbers) if numbers else 0


def _name_the_overlap(prefix: str, code: str, last: int):
	"""Bills here carrying a number myBillBook may also have issued.

	Said out loud rather than fixed: two tax invoices sharing a number is a
	matter for whoever reconciles the registers, and the bills themselves are
	already with customers.
	"""
	series = f"{prefix}/{code}/{FY}/"
	clashes = [
		name for name in frappe.db.sql_list("""
			select name from `tabSales Invoice`
			where name like %s and docstatus < 2 order by name
		""", (series + "%",))
		if name[len(series):].isdigit() and int(name[len(series):]) <= last
	]
	if clashes:
		print(f"  {series}: {len(clashes)} bill(s) here carry a number myBillBook "
		      f"may also have used — {clashes[0]} to {clashes[-1]}. Compare them "
		      f"against myBillBook's register; this patch changes none of them.")
