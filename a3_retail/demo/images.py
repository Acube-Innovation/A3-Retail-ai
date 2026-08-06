# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Catalogue artwork for the demo dataset.

A counter screen is read at arm's length and at speed, and a wall of grey
initials is slower to scan than a wall of pictures. Real shops load supplier
photographs; a demo site has none, so this ships a small set of flat drawings
and hangs the right one on each item.

Nothing here overwrites an image that is already set — the moment a shop
uploads its own photograph, this stops having an opinion about that item.

    bench --site <site> execute a3_retail.demo.images.run
"""

import os

import frappe

FOLDER = "/assets/a3_retail/images/catalogue"
PHOTOS = FOLDER + "/photos"

# Real photographs, where a real photograph of that thing reads at thumbnail
# size. Matched on the item's own name so a shop that renames "Redmi Note 13"
# to "Redmi Note 13 Pro" keeps its picture. Credits and licences are in
# public/images/catalogue/CREDITS.md.
PHOTO_RULES = [
	(("iphone", "apl-15"), "iphone-15-black"),
	(("galaxy a", "galaxy s", "sam-a"), "samsung-phone"),
	(("redmi note", "xia-n"), "redmi-phone"),
	(("vivo",), "vivo-phone"),
	(("tab ", "tablet", "tab-"), "tablet"),
	(("watch",), "apple-watch-se"),
	(("buds", "earbud", "airdopes"), "earbuds"),
	(("headphone", "headset", "rockerz"), "headphones"),
	(("charger", "adapter"), "charger"),
	(("tempered glass", "screen guard", "screen protector"), "tempered-glass"),
]

# A photograph of a whole handset is the wrong picture for the display that
# came out of one, and no photograph of an hour's labour exists. Those groups
# keep the drawings, which say what the line is at a glance.
PHOTO_GROUPS = {"mobile phones", "tablets", "smart wearables", "accessories", "used devices"}

# Checked in name order, first match wins. The device colours are handled
# separately because a handset's picture follows its colour, not its words.
KEYWORDS = [
	(("tempered glass", "screen guard", "screen protector"), "tempered-glass"),
	(("power bank", "powerbank"), "powerbank"),
	(("headphone", "headset", "rockerz"), "headphones"),
	(("buds", "earbud", "airdopes", "airpod"), "earbuds"),
	(("charger", "adapter"), "charger"),
	(("cable", "konnect", "type c", "type-c"), "cable"),
	(("speaker",), "speaker"),
	(("battery",), "battery"),
	(("power ic", "board level", "motherboard", "chip"), "chip"),
	(("display assembly", "display", "lcd"), "tempered-glass"),
	(("watch", "band"), "watch"),
	(("tab ", "tablet", "ipad"), "tablet"),
	(("sim", "recharge", "plan"), "sim"),
]

COLOURS = [
	("black", "phone-black"),
	("blue", "phone-blue"),
	("pink", "phone-pink"),
	("green", "phone-green"),
	("white", "phone-white"),
	("silver", "phone-silver"),
	("gold", "phone-gold"),
	("grey", "phone-grey"),
	("gray", "phone-grey"),
]

# Handsets that name no colour still need a face. Spread them so a shelf of
# them does not come out as one long row of the same picture.
UNNAMED_COLOURS = ["phone-grey", "phone-blue", "phone-black", "phone-green", "phone-silver"]


def photo(item: dict) -> str | None:
	"""The photograph for this item, if one of ours shows what it is."""
	name = f"{item.get('item_name') or ''} {item.get('item_code') or ''}".lower()
	group = (item.get("item_group") or "").lower()
	if item.get("is_fixed_asset") or item.get("a3_is_ew_plan") or group not in PHOTO_GROUPS:
		return None
	for words, art in PHOTO_RULES:
		if any(word in name for word in words):
			return art
	return None


def pick(item: dict) -> str:
	"""The drawing that best fits this item."""
	name = f"{item.get('item_name') or ''} {item.get('item_code') or ''}".lower()
	group = (item.get("item_group") or "").lower()

	if item.get("a3_is_ew_plan") or "warranty" in group or "protection plan" in name:
		return "plan"

	# The shop's own scooter and its microscope are Items too, and never appear
	# at the counter — a plain box is the honest picture for them.
	if item.get("is_fixed_asset"):
		return "box"

	if item.get("a3_is_device") or group in ("mobile phones", "used devices"):
		if "tab" in group or "tablet" in name:
			return "tablet"
		if "watch" in group or "watch" in name or "wearable" in group:
			return "watch"
		for word, art in COLOURS:
			if word in name:
				return art
		return UNNAMED_COLOURS[sum(map(ord, item["name"])) % len(UNNAMED_COLOURS)]

	# A labour line or a diagnostic fee is work, not a thing on a shelf — decide
	# that before the keyword table, which would otherwise read "Diagnostic
	# Charge" as a board-level part.
	if not item.get("is_stock_item") or "service" in group:
		return "service"

	for words, art in KEYWORDS:
		if any(word in name for word in words):
			return art

	return "box"


def run(overwrite: bool = False, verbose: bool = True) -> int:
	"""Hang a picture on every demo item that has none. Idempotent."""
	root = frappe.get_app_path("a3_retail", "public", "images", "catalogue")
	available = {f[:-4] for f in os.listdir(root) if f.endswith(".svg")}
	photos = {f[:-4] for f in os.listdir(os.path.join(root, "photos")) if f.endswith(".jpg")}

	items = frappe.get_all(
		"Item",
		fields=["name", "item_code", "item_name", "item_group", "image", "is_stock_item",
		        "is_fixed_asset", "a3_is_device", "a3_is_ew_plan"],
	)

	painted = 0
	for item in items:
		if item.image and not overwrite:
			continue
		shot = photo(item)
		if shot and shot in photos:
			url = f"{PHOTOS}/{shot}.jpg"
		else:
			art = pick(item)
			url = f"{FOLDER}/{art if art in available else 'box'}.svg"

		frappe.db.set_value("Item", item.name, "image", url, update_modified=False)
		painted += 1

	frappe.db.commit()
	if verbose:
		print(f"catalogue artwork: {painted} items")
	return painted
