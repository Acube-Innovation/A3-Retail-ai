"""Sign out of the branch app — /retail/logout.

A plain link, not a fetch: the shop floor should be able to sign out even if
JavaScript never loaded.

`?to=` says where to land afterwards. That is what makes switching to the desk
possible at all — Frappe bounces a signed-in user away from /login, so the only
way to reach the desk sign-in form is to end this session on the way there.
"""

import frappe

no_cache = 1

DEFAULT_DESTINATION = "/retail?bye=1"


def get_context(context):
	destination = safe_destination(frappe.form_dict.get("to"))

	if frappe.session.user != "Guest":
		frappe.local.login_manager.logout()
		frappe.db.commit()

	frappe.local.flags.redirect_location = destination
	raise frappe.Redirect


def safe_destination(target: str | None) -> str:
	"""Only same-site paths — never let a link hand the session to another host."""
	if not target:
		return DEFAULT_DESTINATION
	if not target.startswith("/") or target.startswith("//") or "\\" in target:
		return DEFAULT_DESTINATION
	return target
