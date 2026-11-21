# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Let the back-dated bills through the stock count that shut them out.

Bills for 13–18 November were keyed in on the 20th, after someone had already
run a stock count that evening. ERPNext then refuses both halves of the job,
for two different reasons, and only one of them is about stock running out:

**Handsets.** ERPNext will not post a back-dated movement of a serialised item
when a Stock Reconciliation for that item and that shelf is dated later — the
count states a quantity outright, so a sale slipped in behind it would leave
the count asserting a figure that was never true. The phones are on the shelf
and the IMEIs are free; the count alone is in the way. Where that count turned
out to record nothing — every line declaring the quantity the shelf already
had — it is cancelled here, because a count that changed no figure is holding
up the bills for nothing. A count that genuinely corrected something is left
exactly where it is and the bills behind it are named below for a person to
decide on; this patch will not quietly rewrite a real count.

**Accessories.** A handful of older bills ask for tempered glass and a speaker
from a shelf the books had standing at zero at the time, because a count in
October zeroed it and a count in November put it back. Nothing was wrong on the
shelf; the books were. So the stock each bill needs is received in the day
before that bill, and the whole of it is credited to Temporary Opening — the
same account the opening stock used, because this is the migration catching up
rather than a purchase anyone made. The later counts state absolute figures, so
they wash the correction out again: the quantity on the shelf today does not
move by a single piece.

Neither half touches a bill. No date, number, customer, item or amount changes;
submitting them stays the counter's job, and the patch finishes by naming each
one and saying whether it will now go through.

Safe to run again. Counts already cancelled are skipped, the shortfall is read
off the ledger each time rather than remembered, and a site whose bills are all
submitted gets nothing but a line saying so.
"""

import frappe
from frappe.utils import add_days, flt, get_datetime

RECEIPT_NOTE = "Stock the books were short of when {bill} was entered late"


def execute():
	drafts = _drafts_that_move_stock()
	if not drafts:
		print("  no draft bills that move stock — nothing to do")
		return

	still_blocked = _drop_counts_that_counted_nothing(drafts)
	_supply_what_the_shelf_lacked(drafts)
	_report(drafts, still_blocked)


# --------------------------------------------------------------------------
# what we are working on


def _drafts_that_move_stock():
	"""Every unsubmitted bill that would move stock, oldest first.

	Ordered by the moment it claims to have happened, not by when it was
	keyed in: the shortfall of a later bill depends on what the earlier ones
	have already taken off the shelf.
	"""
	names = frappe.db.sql("""
		select name from `tabSales Invoice`
		where docstatus = 0 and update_stock = 1
		order by timestamp(posting_date, posting_time), creation
	""", pluck=True)
	return [frappe.get_doc("Sales Invoice", n) for n in names]


def _stamp(doc):
	return get_datetime(f"{doc.posting_date} {doc.posting_time}")


def _lines(doc, serialised):
	"""The bill's lines, split by whether the item is counted piece by piece."""
	for row in doc.items:
		if not row.item_code or not row.warehouse:
			continue
		flags = frappe.get_cached_value(
			"Item", row.item_code, ["has_serial_no", "has_batch_no"], as_dict=True)
		tracked = bool(flags and (flags.has_serial_no or flags.has_batch_no))
		if tracked is serialised:
			yield row


# --------------------------------------------------------------------------
# the counts


def _drop_counts_that_counted_nothing(drafts):
	"""Cancel the later counts that recorded nothing, and name those that did.

	Only counts standing in front of a serialised line are even looked at: a
	plain item carries no serial bundle, so ERPNext's future-count rule never
	fires on it and a count in its past is none of our business.
	"""
	wanted = {}
	for doc in drafts:
		for row in _lines(doc, serialised=True):
			key = (row.item_code, row.warehouse)
			stamp = _stamp(doc)
			if key not in wanted or stamp < wanted[key][0]:
				wanted[key] = (stamp, doc.name)
	if not wanted:
		return {}

	candidates = {}
	for (item_code, warehouse), (stamp, bill) in wanted.items():
		for name in frappe.db.sql("""
			select distinct sr.name
			from `tabStock Reconciliation` sr
			join `tabStock Reconciliation Item` sri on sri.parent = sr.name
			where sr.docstatus = 1 and sri.item_code = %s and sri.warehouse = %s
			  and timestamp(sr.posting_date, sr.posting_time) > %s
		""", (item_code, warehouse, stamp), pluck=True):
			candidates.setdefault(name, []).append(bill)

	still_blocked = {}
	for name in sorted(candidates):
		changed = _what_the_count_changed(name)
		if changed:
			for bill in candidates[name]:
				still_blocked.setdefault(bill, []).append((name, changed))
			print(f"  {name} corrected {len(changed)} line(s) — left alone, "
			      f"it is a real count")
			continue
		doc = frappe.get_doc("Stock Reconciliation", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
		print(f"  {name} declared the quantity every shelf already had "
		      f"({len(doc.items)} line(s)) — cancelled, it was blocking "
		      f"{len(set(candidates[name]))} bill(s)")
	return still_blocked


def _what_the_count_changed(name):
	"""The lines where a count declared something other than what was there.

	Empty means the count moved nothing and cancelling it cannot change a
	balance. A line that names no quantity is not a change either: ERPNext
	keeps whatever the shelf held.
	"""
	doc = frappe.get_doc("Stock Reconciliation", name)
	stamp = get_datetime(f"{doc.posting_date} {doc.posting_time}")
	changed = []
	for row in doc.items:
		if row.qty is None:
			continue
		before = _balance_at(row.item_code, row.warehouse, stamp, ignore=name)
		if abs(before - flt(row.qty)) > 0.001:
			changed.append(f"{row.item_code} @ {row.warehouse}: "
			               f"{before:g} counted as {flt(row.qty):g}")
	return changed


# --------------------------------------------------------------------------
# the shelf


def _balance_at(item_code, warehouse, stamp, ignore=None):
	"""What the ledger says was on that shelf at that moment."""
	row = frappe.db.sql("""
		select qty_after_transaction from `tabStock Ledger Entry`
		where item_code = %s and warehouse = %s and is_cancelled = 0
		  and voucher_no != %s
		  and timestamp(posting_date, posting_time) <= %s
		order by timestamp(posting_date, posting_time) desc, creation desc
		limit 1
	""", (item_code, warehouse, ignore or "", stamp))
	return flt(row[0][0]) if row else 0.0


def _last_count_before(item_code, warehouse, stamp):
	"""When this shelf was last counted at or before that moment, if ever.

	A count states an absolute figure, so it is the point from which what
	earlier bills have taken stops mattering.
	"""
	row = frappe.db.sql("""
		select max(timestamp(sle.posting_date, sle.posting_time))
		from `tabStock Ledger Entry` sle
		where sle.item_code = %s and sle.warehouse = %s and sle.is_cancelled = 0
		  and sle.voucher_type = 'Stock Reconciliation'
		  and timestamp(sle.posting_date, sle.posting_time) <= %s
	""", (item_code, warehouse, stamp))
	return row[0][0] if row and row[0][0] else None


def _supply_what_the_shelf_lacked(drafts):
	"""Receive in, the day before each bill, the stock its books were short of."""
	claimed, since = {}, {}
	for doc in drafts:
		stamp = _stamp(doc)
		short = []
		for row in _lines(doc, serialised=False):
			key = (row.item_code, row.warehouse)
			count = _last_count_before(row.item_code, row.warehouse, stamp)
			if since.get(key) != count:
				# A count since the last bill re-stated the shelf outright,
				# so what those bills took is already inside the new figure.
				claimed[key], since[key] = 0.0, count
			have = _balance_at(row.item_code, row.warehouse, stamp) - claimed.get(key, 0.0)
			need = flt(row.qty) - have
			claimed[key] = claimed.get(key, 0.0) + flt(row.qty)
			if need > 0.001:
				short.append((row, need))
		if short:
			_receive(doc, short)


def _receive(doc, short):
	company = doc.company or frappe.db.get_single_value("Global Defaults", "default_company")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	entry = frappe.new_doc("Stock Entry")
	entry.company = company
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.set_posting_time = 1
	entry.posting_date = add_days(doc.posting_date, -1)
	entry.posting_time = doc.posting_time
	entry.remarks = RECEIPT_NOTE.format(bill=doc.name)
	for row, need in short:
		line = {
			"item_code": row.item_code,
			"qty": need,
			"uom": row.stock_uom or row.uom,
			"t_warehouse": row.warehouse,
			"expense_account": f"Temporary Opening - {abbr}",
			"basic_rate": _cost(row),
		}
		if row.cost_center:
			line["cost_center"] = row.cost_center
		if not line["basic_rate"]:
			line["allow_zero_valuation_rate"] = 1
		entry.append("items", line)
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	pieces = ", ".join(f"{need:g} x {row.item_code}" for row, need in short)
	print(f"  {entry.name} on {entry.posting_date}: {pieces} — "
	      f"stock {doc.name} was short of")


def _cost(row):
	"""What to value the top-up at, nearest guess first."""
	return (
		flt(frappe.db.get_value("Bin", {"item_code": row.item_code,
		                                "warehouse": row.warehouse}, "valuation_rate"))
		or flt(frappe.db.get_value("Item", row.item_code, "valuation_rate"))
		or flt(frappe.db.get_value("Item", row.item_code, "last_purchase_rate"))
		or 0.0
	)


# --------------------------------------------------------------------------
# what is left


def _report(drafts, still_blocked):
	print("\n  Draft bills, and whether they will go through now:")
	for doc in drafts:
		reasons = []
		for name, changed in still_blocked.get(doc.name, []):
			reasons.append(f"counted after it by {name} ({changed[0]})")
		for row in _lines(doc, serialised=False):
			have = _balance_at(row.item_code, row.warehouse, _stamp(doc))
			if flt(row.qty) - have > 0.001:
				reasons.append(f"{row.item_code} still {flt(row.qty) - have:g} short")
		for row in _lines(doc, serialised=True):
			for serial in _serials(row):
				for later in _moved_later_than(serial, _stamp(doc)):
					reasons.append(
						f"IMEI {serial} moves again on {later.posting_datetime} "
						f"in {later.voucher_no}, after this bill")
		verdict = "ready" if not reasons else "; ".join(reasons)
		print(f"    {doc.name} ({doc.posting_date}) — {verdict}")


def _moved_later_than(serial, stamp):
	"""Movements of this IMEI dated after the bill that wants to sell it.

	The same question ERPNext asks before it refuses: a piece recorded as
	moving later cannot also have been sold earlier, so either the bill's date
	or that movement's date is wrong, and only a person who knows which can
	say.
	"""
	return frappe.db.sql("""
		select sbb.voucher_type, sbb.voucher_no, min(sbb.posting_datetime) as posting_datetime
		from `tabSerial and Batch Bundle` sbb
		join `tabSerial and Batch Entry` sbe on sbe.parent = sbb.name
		where sbe.serial_no = %s and sbb.docstatus = 1 and sbb.is_cancelled = 0
		  and sbb.posting_datetime > %s
		group by sbb.voucher_type, sbb.voucher_no
		order by 3
	""", (serial, stamp), as_dict=True)


def _serials(row):
	if row.get("serial_no"):
		return [s.strip() for s in row.serial_no.replace(",", "\n").split("\n") if s.strip()]
	if row.get("serial_and_batch_bundle"):
		return frappe.get_all("Serial and Batch Entry",
		                      {"parent": row.serial_and_batch_bundle}, pluck="serial_no")
	return []
