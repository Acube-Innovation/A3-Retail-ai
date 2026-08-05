"""GSTIN helpers.

The scope document's sample GSTINs are illustrative and fail the statutory check
digit, which india_compliance enforces on save. Demo seeding therefore keeps the
first 14 characters from the scope document (state code + PAN + entity code) and
recomputes the 15th so the records are actually valid.

The algorithm mirrors `india_compliance.gst_india.utils.validate_gstin_check_digit`.
"""

import re

CODE_POINTS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MOD = len(CODE_POINTS)

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def gstin_check_digit(first_fourteen: str) -> str:
	"""Return the 15th character for the first 14 characters of a GSTIN."""
	value = first_fourteen.upper()
	if len(value) != 14:
		raise ValueError("GSTIN prefix must be exactly 14 characters")

	factor = 1
	total = 0
	for char in value:
		digit = factor * CODE_POINTS.find(char)
		total += (digit // MOD) + (digit % MOD)
		factor = 2 if factor == 1 else 1

	return CODE_POINTS[(MOD - (total % MOD)) % MOD]


def normalize_gstin(gstin: str | None) -> str | None:
	"""Uppercase a GSTIN and repair its check digit. Returns None for falsy input."""
	if not gstin:
		return None

	value = re.sub(r"\s", "", str(gstin)).upper()
	if len(value) != 15:
		return value

	return value[:14] + gstin_check_digit(value[:14])


def is_valid_gstin(gstin: str | None) -> bool:
	if not gstin or len(gstin) != 15 or not GSTIN_RE.match(gstin.upper()):
		return False
	value = gstin.upper()
	return value[14] == gstin_check_digit(value[:14])


def state_code(gstin: str | None) -> str | None:
	return gstin[:2] if gstin and len(gstin) >= 2 else None
