"""Sign out of the branch app — /branch/logout.

A plain link, not a fetch: the shop floor should be able to sign out even if
JavaScript never loaded.
"""

import frappe

no_cache = 1


def get_context(context):
	if frappe.session.user != "Guest":
		frappe.local.login_manager.logout()
		frappe.db.commit()

	frappe.local.flags.redirect_location = "/branch?bye=1"
	raise frappe.Redirect
