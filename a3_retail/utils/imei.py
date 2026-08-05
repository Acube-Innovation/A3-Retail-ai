"""IMEI helpers — normalisation, Luhn validation and formatting.

An IMEI is 15 digits: 14 digits of TAC + serial, plus a Luhn check digit.
Some refurbished / grey stock carries non-standard IMEIs, so the check can be
bypassed by roles listed in A3 Retail Settings.allow_imei_override_roles.
"""

import re

import frappe
from frappe import _

IMEI_LENGTH = 15


def normalize_imei(imei: str | None) -> str:
	"""Strip everything that is not a digit. Returns '' for falsy input."""
	if not imei:
		return ""
	return re.sub(r"\D", "", str(imei))


def luhn_check_digit(payload: str) -> int:
	"""Return the Luhn check digit for a numeric payload (without check digit)."""
	total = 0
	# Double every second digit counting from the right of the payload.
	for index, char in enumerate(reversed(payload)):
		digit = int(char)
		if index % 2 == 0:
			digit *= 2
			if digit > 9:
				digit -= 9
		total += digit
	return (10 - (total % 10)) % 10


def validate_imei(imei: str | None) -> bool:
	"""True when `imei` is 15 digits and the Luhn check digit matches."""
	value = normalize_imei(imei)
	if len(value) != IMEI_LENGTH or not value.isdigit():
		return False
	return luhn_check_digit(value[:-1]) == int(value[-1])


def is_luhn_enforced() -> bool:
	"""Master switch from A3 Retail Settings; defaults to enforced."""
	if not frappe.db.exists("DocType", "A3 Retail Settings"):
		return True
	return bool(frappe.db.get_single_value("A3 Retail Settings", "enforce_luhn_check"))


def can_override_imei(user: str | None = None) -> bool:
	"""True when the user holds one of the override roles configured in settings."""
	# Demo seeding and data migrations set this flag: the scope document's own
	# sample IMEIs are illustrative numbers that do not satisfy Luhn, and the
	# spec explicitly allows an override for refurb/grey stock.
	if frappe.flags.get("a3_bypass_imei_check"):
		return True

	user = user or frappe.session.user
	if user == "Administrator":
		return True

	override_roles = {"System Manager", "A3 Retail Admin"}
	if frappe.db.exists("DocType", "A3 Retail Settings"):
		settings = frappe.get_cached_doc("A3 Retail Settings")
		for row in settings.get("allow_imei_override_roles") or []:
			if row.get("role"):
				override_roles.add(row.role)

	return bool(override_roles & set(frappe.get_roles(user)))


def enforce_imei(imei: str | None, fieldlabel: str = "IMEI", user: str | None = None) -> str:
	"""Validate and return a normalised IMEI, throwing unless the user may override."""
	value = normalize_imei(imei)
	if not value:
		return value

	if validate_imei(value):
		return value

	if not is_luhn_enforced() or can_override_imei(user):
		return value

	frappe.throw(
		_("{0} {1} is not a valid 15-digit IMEI (Luhn check failed).").format(fieldlabel, value),
		title=_("Invalid IMEI"),
	)


def format_imei(imei: str | None) -> str:
	"""Group an IMEI as 2-6-6-1 for printing: 35-391210-456789-1."""
	value = normalize_imei(imei)
	if len(value) != IMEI_LENGTH:
		return value
	return f"{value[:2]}-{value[2:8]}-{value[8:14]}-{value[14]}"
