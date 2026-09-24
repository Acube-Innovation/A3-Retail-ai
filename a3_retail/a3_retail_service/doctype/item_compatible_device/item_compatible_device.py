# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Which phones an item fits.

One row per device. A pouch or a spare part is one thing on the shelf with one
stock count, however many handsets it suits — so compatibility is a list against
the item, never a separate item per phone.
"""

from frappe.model.document import Document


class ItemCompatibleDevice(Document):
	pass
