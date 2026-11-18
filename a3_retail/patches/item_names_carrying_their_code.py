# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Take the item's own code back out of its name.

The shop's filing writes the code into the name as well as into the code:
`T150` is called `TEMPERED - 150  T150`. Every screen that shows the name then
reads as the same thing listed twice, which is what the counter reported as a
duplicate item — there was only ever one record behind it.

The sell screen already stops printing the repeated code, but that only hides
it. The name itself is what is wrong, and it is the name that goes onto a bill,
into a report and out to a customer.

Only a code that looks like a code is taken off. `CURVED GLASS` is an item code
here too, and its name — `PREMIUM FULL GLUE CURVED GLASS` — genuinely ends with
those words: trimming that would leave `PREMIUM FULL GLUE`, which is not the
thing on the shelf. So a code is only stripped when it carries a digit and has
no spaces in it, which is what `T150` and `PT450` look like and what an English
phrase does not.
"""

import collections
import re

import frappe

# Separators that join a code onto the end of a name. A name that genuinely
# ends in a word keeps it.
TRAILING = re.compile(r"[\s·,\-–—]+$")
# A code rather than a word: no spaces, and at least one digit.
LOOKS_LIKE_A_CODE = re.compile(r"^(?=\S*\d)\S+$")


def execute():
	fixed, looked = [], 0
	for row in frappe.get_all("Item", fields=["name", "item_name"]):
		looked += 1
		trimmed = _without_the_code(row.name, row.item_name)
		if not trimmed:
			continue
		frappe.db.set_value("Item", row.name, "item_name", trimmed,
		                    update_modified=False)
		fixed.append((row.name, row.item_name, trimmed))

	frappe.db.commit()
	print(f"  looked at {looked} item(s); {len(fixed)} carried their own code")
	for code, was, now in sorted(fixed):
		print(f"      {code}: {was!r} -> {now!r}")

	_report_the_real_duplicates()


def _report_the_real_duplicates():
	"""Name the items that genuinely are two records, and change nothing.

	Taking the code off a name fixes one record that *read* as two. It does
	nothing for the other kind, which came over from myBillBook: two separate
	items whose codes differ only by a space or by case — `T200` and `T 200`,
	`IPHONE 16 128GB` and `I PHONE 16 128GB`, `KEYCHAIN LIGHT` and
	`KEY CHAIN LIGHT`. Each is a real Item with its own stock, its own history
	and possibly its own submitted bills.

	Merging them is not a patch's decision. It moves stock, it rewrites what a
	customer was sold, and where both sides hold stock somebody has to count
	the shelf and say which is which. So this lists them for the shop and
	leaves them alone.
	"""
	by_shape = collections.defaultdict(list)
	for row in frappe.get_all("Item", fields=["name", "item_name", "disabled"]):
		by_shape["".join(row.name.split()).upper()].append(row)

	pairs = [rows for rows in by_shape.values() if len(rows) > 1]
	if not pairs:
		return

	print(f"\n  {len(pairs)} item(s) exist twice over, differing only by a space "
	      "or by case. Nothing here is merged — each is a real record with its "
	      "own stock and its own history, and which one survives is the shop's "
	      "call:")
	for rows in sorted(pairs, key=lambda rows: rows[0].name):
		for row in sorted(rows, key=lambda r: r.name):
			held = frappe.db.sql("""select ifnull(sum(actual_qty), 0)
			                        from `tabBin` where item_code = %s""",
			                     row.name)[0][0] or 0
			note = " (disabled)" if row.disabled else ""
			print(f"      {row.name!r} — {held:g} on hand{note}")
		print()


def _without_the_code(code: str, item_name: str) -> str | None:
	"""The name with a trailing copy of `code` removed, or None to leave it."""
	name = (item_name or "").strip()
	code = (code or "").strip()
	if not name or not code or not LOOKS_LIKE_A_CODE.match(code):
		return None
	if len(name) <= len(code) or not name.lower().endswith(code.lower()):
		return None

	trimmed = TRAILING.sub("", name[: -len(code)])
	# Never leave an item nameless, and never report a change that is not one.
	if not trimmed or trimmed == name:
		return None
	return trimmed
