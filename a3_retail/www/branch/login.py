"""Branch app sign-in — /branch/login.

The form posts to this page and the session is opened server-side, so signing in
never depends on JavaScript, a fetch polyfill or a CSRF header. A shop-floor app
has to work on whatever browser is on the counter.
"""

import frappe
from frappe import _
from frappe.utils import cint

no_cache = 1

MAX_ATTEMPTS_PER_IP = 20
ATTEMPT_WINDOW_SECONDS = 900


def get_context(context):
	from a3_retail.setup.staff_portal import HOME_PAGE, current_employee

	context.no_cache = 1
	context.app_name = "A3 Retail"
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or "A3 Retail"
	context.home_page = HOME_PAGE
	context.error = None
	context.username = ""

	# Already signed in as branch staff? Go straight in.
	if frappe.session.user != "Guest" and current_employee():
		frappe.local.flags.redirect_location = HOME_PAGE
		raise frappe.Redirect

	# Signed in as somebody who does not belong here — say so rather than failing
	# silently when they type their own credentials over the top.
	context.other_session = (
		frappe.session.user if frappe.session.user != "Guest" else ""
	)

	if frappe.local.request.method == "POST":
		_sign_in(context)

	return context


def _sign_in(context):
	username = (frappe.form_dict.get("usr") or "").strip()
	password = frappe.form_dict.get("pwd") or ""
	context.username = username

	if not username or not password:
		context.error = _("Enter your email and password.")
		return

	if _too_many_attempts():
		context.error = _("Too many attempts. Wait a few minutes and try again.")
		return

	try:
		frappe.local.login_manager.authenticate(user=username, pwd=password)
		frappe.local.login_manager.post_login()
	except frappe.AuthenticationError:
		_record_attempt()
		context.error = _("That email and password do not match.")
		return
	except frappe.SecurityException:
		context.error = _("This account is locked. Ask your branch manager.")
		return

	frappe.local.flags.redirect_location = _destination()
	raise frappe.Redirect


def _destination() -> str:
	"""Branch staff land in the app; anyone else goes where they belong."""
	from a3_retail.setup.staff_portal import HOME_PAGE, current_employee

	if current_employee():
		return HOME_PAGE
	if frappe.db.get_value("User", frappe.session.user, "user_type") == "System User":
		return "/app"
	return "/branch"


def _attempt_key() -> str:
	return f"a3_branch_login:{getattr(frappe.local, 'request_ip', 'unknown')}"


def _too_many_attempts() -> bool:
	return cint(frappe.cache().get_value(_attempt_key())) >= MAX_ATTEMPTS_PER_IP


def _record_attempt():
	key = _attempt_key()
	frappe.cache().set_value(
		key, cint(frappe.cache().get_value(key)) + 1, expires_in_sec=ATTEMPT_WINDOW_SECONDS
	)
