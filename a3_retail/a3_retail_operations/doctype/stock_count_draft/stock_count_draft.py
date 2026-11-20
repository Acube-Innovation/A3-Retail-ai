# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""A stock count that has been put aside half-finished.

A count of four thousand accessories is not done in one sitting. The counter
needs to walk away from the screen, keep counting, and come back to what they
had — and nothing must reach the ledger until they say the count is finished.

This is not a second stock system. It holds the lines and nothing else; when
the count is submitted, a real Stock Reconciliation is posted and this is
marked Posted.

**Why not simply hold a draft Stock Reconciliation.** ERPNext validates one on
every save: a row whose counted quantity matches what the system already holds
is *removed* from the document, and if every row matches it refuses to save at
all. Both are right for a finished count and wrong for a half-finished one —
scan five of an accessory the system also thinks there are five of, hold the
count, and that line would be gone when you came back to it, with nothing said.
"""

import json

import frappe
from frappe.model.document import Document


class StockCountDraft(Document):
	def validate(self):
		# Stored as text, so it is worth knowing early that it is readable.
		if self.lines:
			try:
				json.loads(self.lines)
			except ValueError:
				frappe.throw(frappe._("The held count could not be read."))

	def rows(self) -> list[dict]:
		try:
			return json.loads(self.lines or "[]")
		except ValueError:
			return []
