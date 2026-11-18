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
