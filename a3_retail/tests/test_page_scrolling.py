# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Every screen can be scrolled, except the one that is meant not to be.

Written after `pos-body` was mistaken for the Sell screen's own body class.
It is not — twenty of the twenty-three pages wear it — so pinning `.main` to
`height: 100vh; overflow: hidden` to give Sell two independently scrolling
columns froze Bills, Stock, Reports, Service POS and every other screen at one
viewport, with no way to reach what was below the fold.

A page stops scrolling when one of its outer scroll containers is both fixed to
the window's height and told to hide its overflow. So the rule is simple enough
to assert: no page-level container may be frozen unless the page asked for it
by name.
"""

import re

import frappe
from frappe.tests.utils import FrappeTestCase

# The elements the page itself scrolls in. A pinned panel inside the page is
# somebody's deliberate design; one of these is the page.
CONTAINERS = ("html", "body", ".app", ".main", ".content")

# The one screen that is meant to fill the window exactly: its catalogue and
# its bill scroll apart, so the window must not scroll as well.
ALLOWED = {"sales.html"}

FREEZING = re.compile(
	r"(?:^|[;{\s])(?:height\s*:\s*100vh|overflow\s*:\s*hidden|overflow-y\s*:\s*hidden)", re.I)


def _stylesheet() -> str:
	path = frappe.get_app_path("a3_retail", "public", "css", "a3_branch.css")
	with open(path) as handle:
		# Comments go first: a selector quoted in prose is not a rule.
		return re.sub(r"/\*.*?\*/", "", handle.read(), flags=re.S)


def _freezing_rules() -> list[tuple[str, set]]:
	"""Every rule that pins a page-level container, with the classes it needs."""
	found = []
	for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", _stylesheet()):
		if not FREEZING.search(rule.group(2)):
			continue
		for selector in (part.strip() for part in rule.group(1).split(",")):
			pieces = selector.split()
			if not pieces:
				continue
			target = pieces[-1].split(":")[0]
			if target not in CONTAINERS:
				continue
			# What the body would have to carry for this rule to reach the page.
			needed = {p.lstrip(".") for p in pieces[:-1] if p.startswith(".")}
			found.append((selector, needed))
	return found


def _pages():
	folder = frappe.get_app_path("a3_retail", "www", "retail")
	import os

	for name in sorted(os.listdir(folder)):
		if not name.endswith(".html") or name.startswith("_"):
			continue
		with open(os.path.join(folder, name)) as handle:
			text = handle.read()
		opening = re.search(r"<body([^>]*)>", text)
		if not opening:
			continue
		classes = re.search(r'class="([^"]*)"', opening.group(1))
		yield name, set(classes.group(1).split()) if classes else set()


class TestPageScrolling(FrappeTestCase):
	def test_no_screen_is_frozen_to_the_window_by_accident(self):
		rules = _freezing_rules()
		for name, classes in _pages():
			hits = [selector for selector, needed in rules if needed <= classes]
			if name in ALLOWED:
				continue
			self.assertEqual(
				hits, [],
				f"{name} cannot be scrolled — {hits} reaches it through "
				f"class=\"{' '.join(sorted(classes))}\"")

	def test_the_sell_screen_is_still_pinned_to_the_window(self):
		"""The other half of the bargain: without this the two columns go back
		to sharing one page scroll and the bill walks off the top again."""
		rules = _freezing_rules()
		pages = dict(_pages())
		self.assertIn("sales.html", pages)
		hits = [selector for selector, needed in rules if needed <= pages["sales.html"]]
		self.assertTrue(hits, "Sell should fill the window exactly")

	def test_the_class_that_pins_a_page_is_worn_by_one_page_only(self):
		"""`pos-body` is on twenty screens; whatever pins a page must not be."""
		wearers = {name for name, classes in _pages() if "pos-split" in classes}
		self.assertEqual(wearers, {"sales.html"})
