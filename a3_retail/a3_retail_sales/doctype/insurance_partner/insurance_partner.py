# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Who covers the handset — the protection plan sold with it.

Kept as a master rather than a free-text box so that "Bajaj" and "BAJAJ" do
not become two answers in a year's reporting, and as a master rather than a
fixed list because a new financier or brand programme turns up every season
and the counter should not wait for a deployment to sell it.
"""

from frappe.model.document import Document


class InsurancePartner(Document):
	pass
