# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""A link to one printed document that WhatsApp can fetch for itself.

WhatsApp does not take a file upload alongside a template message. It is given
a URL and fetches the document from Meta's servers — no session, no cookies, no
login. So a customer's invoice has to be reachable from the open internet, and
nothing else must be.

Frappe already has this: `Document Share Key` is a per-document key with an
expiry, `validate_print_permission` accepts it in place of a session, and
`frappe.utils.print_format.download_pdf` is a guest endpoint that honours it.
An earlier draft of this module signed its own links and served its own PDF,
which meant a hand-written HMAC, a hand-written constant-time compare and a
guest endpoint of our own to keep right. All of that is Frappe's job and it
already does it, so this is now only the two decisions that are ours:

- **Which documents may ever be shared**, and as which print format. `SHAREABLE`
  is the whole list. Without it, a share key is a key to anything.
- **For how long.** Long enough that a customer can open it next week, short
  enough that a forwarded link stops working.

`link_for()` is the one place a shareable link is built, so there is one answer
to both questions rather than one per screen.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_url, quote

# doctype -> the one print format it may be shared as. A key is scoped to a
# document, not to a format, so this is what stops an invoice link being bent
# into printing something else about the same invoice.
SHAREABLE = {
	"Sales Invoice": "Retail Tax Invoice",
	"Service Job Card": "Job Card Acknowledgement",
}

DEFAULT_TTL_DAYS = 30


def link_for(doctype: str, name: str, ttl_days: int | None = None) -> str:
	"""A full https link to this document's PDF, good for `ttl_days`.

	Built on `get_url()`, which answers with the site's `host_name` — the link
	is read by Meta rather than by the counter, and a localhost URL is fetched
	by nobody.
	"""
	print_format = SHAREABLE.get(doctype)
	if not print_format:
		frappe.throw(_("{0} is not a document that can be shared.").format(_(doctype)))
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} no longer exists.").format(_(doctype), name))

	days = cint(ttl_days) or DEFAULT_TTL_DAYS
	doc = frappe.get_doc(doctype, name)
	key = doc.get_document_share_key(expires_on=add_to_date(None, days=days, as_string=True))

	return (f"{get_url().rstrip('/')}/api/method/frappe.utils.print_format.download_pdf"
	        f"?doctype={quote(doctype)}&name={quote(name)}"
	        f"&format={quote(print_format)}&key={quote(key)}")
