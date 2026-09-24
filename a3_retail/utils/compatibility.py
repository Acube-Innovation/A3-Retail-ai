# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Which handsets an item fits.

A pouch or a spare part is one thing on the shelf with one stock count, however
many phones it suits. So the handsets are a list against the item
(`Item.a3_compatible_devices`), never an item per phone — that would split the
stock and leave every copy wrong.

`Item.a3_device_model` is the opposite relationship and must not be confused
with this one: that is the phone an item *is*, for handsets being sold.
"""

import re

import frappe
from frappe import _

SEPARATORS = re.compile(r"\s*[/\\|,]\s*|\s+OR\s+", re.I)


def normalise(name: str) -> str:
	return re.sub(r"\s+", " ", (name or "").strip()).upper()


def split_models(text: str) -> list[str]:
	"""'SAM A50 / A50S \\ A30S' -> ['SAM A50', 'A50S', 'A30S']."""
	return [normalise(part) for part in SEPARATORS.split(text or "") if normalise(part)]


def ensure_device_model(model_name: str, brand: str | None = None) -> str | None:
	"""Find a Device Model by name, or create it so nobody is blocked mid-repair.

	Device Model requires a Brand, so the brand is created too when it is new.
	A technician holding a phone the shop has never serviced should be able to
	record the fit there and then, not file a request for master data.
	"""
	model_name = normalise(model_name)
	if not model_name:
		return None

	existing = frappe.db.get_value("Device Model", {"model_name": model_name}, "name")
	if existing:
		return existing
	if frappe.db.exists("Device Model", model_name):
		return model_name

	brand = (brand or "").strip() or _guess_brand(model_name) or "Generic"
	if not frappe.db.exists("Brand", brand):
		doc = frappe.new_doc("Brand")
		doc.brand = brand
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	model = frappe.new_doc("Device Model")
	model.model_name = model_name
	model.brand = brand
	model.device_type = "Mobile"
	model.is_active = 1
	model.flags.ignore_permissions = True
	model.flags.ignore_mandatory = True
	model.insert(ignore_permissions=True)
	return model.name


# The shop writes models with the brand baked into the string ("SAM A50",
# "REDMI NOTE 10"), so the brand is usually already in front of us.
BRAND_HINTS = (
	("SAMSUNG", "Samsung"), ("SAM ", "Samsung"), ("SAN ", "Samsung"),
	("REDMI", "Xiaomi"), ("POCO", "Xiaomi"), ("MI ", "Xiaomi"), ("XIAOMI", "Xiaomi"),
	("VIVO", "Vivo"), ("OPPO", "Oppo"), ("OPO", "Oppo"),
	("REALME", "Realme"), ("ONE PLUS", "OnePlus"), ("ONEPLUS", "OnePlus"),
	("MOTO", "Motorola"), ("NOKIA", "Nokia"), ("HONOR", "Honor"),
	("APPLE", "Apple"), ("IPHONE", "Apple"), ("TECNO", "Tecno"), ("INFINIX", "Infinix"),
)


def _guess_brand(model_name: str) -> str | None:
	upper = normalise(model_name)
	for hint, brand in BRAND_HINTS:
		if upper.startswith(hint) or hint.strip() in upper:
			return brand
	return None


def fits(item_code: str, device_model: str) -> bool:
	"""Is this handset already listed against the item?

	An item with no list at all fits everything — a screwdriver or a generic
	charger is not phone-specific, and should never raise a mismatch.
	"""
	if not item_code or not device_model:
		return True
	rows = frappe.get_all("Item Compatible Device",
	                      filters={"parent": item_code, "parenttype": "Item"},
	                      pluck="device_model")
	if not rows:
		return True
	if device_model in rows:
		return True
	# The caller may hold the shop's spelling rather than the record name.
	resolved = frappe.db.get_value("Device Model", {"model_name": normalise(device_model)}, "name")
	return bool(resolved and resolved in rows)


def resolve_model(device_model: str) -> str | None:
	"""Accept a Device Model name or the shop's own spelling, return the record.

	Device Model names itself from brand and model ("Xiaomi REDMI NOTE 10"), but
	a technician types "REDMI NOTE 10". Both have to land on the same record or
	the list fills with references that point nowhere.
	"""
	if not device_model:
		return None
	if frappe.db.exists("Device Model", device_model):
		return device_model
	match = frappe.db.get_value("Device Model", {"model_name": normalise(device_model)}, "name")
	return match or ensure_device_model(device_model)


def add_compatible(item_code: str, device_model: str, source: str | None = None) -> bool:
	"""Record that this item fits this handset. Returns False if already listed."""
	if not item_code or not device_model:
		return False
	device_model = resolve_model(device_model)
	if not device_model:
		return False
	if frappe.db.exists("Item Compatible Device",
	                    {"parent": item_code, "parenttype": "Item",
	                     "device_model": device_model}):
		return False

	# The row is inserted against the parent rather than appended through it.
	# Re-saving the Item would run every validation it carries — including
	# india_compliance's HSN check — and refuse a technician who is only
	# recording that a part fits a handset. Compatibility is not a tax question.
	last = frappe.db.sql(
		"""select ifnull(max(idx), 0) from `tabItem Compatible Device`
		   where parent = %s and parenttype = 'Item'""", item_code)[0][0]

	row = frappe.new_doc("Item Compatible Device")
	row.parent = item_code
	row.parenttype = "Item"
	row.parentfield = "a3_compatible_devices"
	row.idx = (last or 0) + 1
	row.device_model = device_model
	row.brand = frappe.db.get_value("Device Model", device_model, "brand")
	row.source = source
	row.flags.ignore_permissions = True
	row.insert(ignore_permissions=True)
	return True


def devices_for(item_code: str) -> list[dict]:
	"""The handsets an item fits, for a screen to show."""
	return frappe.get_all(
		"Item Compatible Device",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["device_model", "brand", "source"],
		order_by="device_model",
	)


def items_for(device_model: str, item_group: str | None = None) -> list[str]:
	"""Which items fit a handset — the question a counter actually asks."""
	device_model = (frappe.db.exists("Device Model", device_model) and device_model) or \
		frappe.db.get_value("Device Model", {"model_name": normalise(device_model)}, "name")
	if not device_model:
		return []
	filters = {"device_model": device_model, "parenttype": "Item"}
	codes = frappe.get_all("Item Compatible Device", filters=filters, pluck="parent")
	if not codes:
		return []
	conditions = {"name": ["in", codes], "disabled": 0}
	if item_group:
		conditions["item_group"] = item_group
	return frappe.get_all("Item", filters=conditions, pluck="name")


def search_clause(alias: str = "i") -> str:
	"""SQL that lets a catalogue search match on the phones an item fits.

	The counter types the handset, not the part number — "A50", not
	"SPR-DSP-A50". Without this the compatibility list is invisible to the one
	search that needs it.
	"""
	return (f"exists (select 1 from `tabItem Compatible Device` icd "
	        f"where icd.parent = {alias}.name and icd.parenttype = 'Item' "
	        f"and icd.device_model like %(query)s)")
