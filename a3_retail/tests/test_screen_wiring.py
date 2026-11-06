# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""A button on a branch screen must reach something that exists.

Twice now a working screen has shipped with a dead button: the Scheme button on
debit notes called a `setKind` nobody had written, and Import Items called an
`openImport` that a refactor two commits earlier had deleted along with the
dialog it opened. Both failed the same way — silently, in the browser, with the
button doing nothing at all and the server never hearing about it. Python tests
could not see either one because neither screen's Python was wrong.

So the wiring is read here instead: every handler a button dispatches to is
looked up in the scope that would be live when it is pressed.
"""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

# `a3_retail.js` is the desk's, not the branch app's, and leans on Frappe's
# globals rather than the shared file below.
SHARED = "a3_branch.js"
DESK = "a3_retail.js"

# A screen hands a button its work one of two ways.
DISPATCH = re.compile(r'===\s*"[^"]*"\s*\)\s*return\s+([A-Za-z_$][\w$]*)\s*\(')
HANDLER = re.compile(r'addEventListener\(\s*"click"\s*,\s*(?:\(\)|\w+)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(')

# Called like a function, defined by the language.
BUILT_IN = {"Number", "String", "Boolean", "Array", "Object", "Math", "JSON",
            "Date", "Promise", "Error", "RegExp", "Map", "Set", "parseInt",
            "parseFloat", "isNaN", "fetch", "setTimeout", "clearTimeout",
            "setInterval", "confirm", "alert", "encodeURIComponent",
            "decodeURIComponent", "requestAnimationFrame", "getComputedStyle"}


def _js(name: str) -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", name), encoding="utf-8").read()


def _screens() -> list[str]:
	folder = frappe.get_app_path("a3_retail", "public", "js")
	return sorted(f for f in os.listdir(folder)
	              if f.startswith("a3_") and f.endswith(".js") and f != DESK)


def _names_in_scope(source: str) -> set:
	"""Everything the file could call by a bare name: declarations and parameters."""
	names = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", source))
	names |= set(re.findall(r"\b(?:let|const|var)\s+([A-Za-z_$][\w$]*)", source))
	names |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*(?:=|:)\s*(?:async\s*)?(?:function|\()", source))
	# A callback handed in as an argument is in scope inside its own function.
	for params in re.findall(r"\bfunction\s*[\w$]*\s*\(([^)]*)\)", source):
		for param in params.split(","):
			bare = param.split("=")[0].strip().lstrip(".")
			if re.fullmatch(r"[A-Za-z_$][\w$]*", bare or ""):
				names.add(bare)
	return names


class TestEveryButtonReachesItsWork(FrappeTestCase):
	def test_no_screen_dispatches_to_a_handler_that_was_never_written(self):
		shared = _names_in_scope(_js(SHARED))
		dead = {}
		for screen in _screens():
			source = _js(screen)
			scope = _names_in_scope(source) | shared | BUILT_IN
			called = set(DISPATCH.findall(source)) | set(HANDLER.findall(source))
			missing = sorted(name for name in called if name not in scope)
			if missing:
				dead[screen] = missing
		self.assertEqual(dead, {}, f"buttons that do nothing when pressed: {dead}")

	def test_the_sweep_is_actually_looking_at_something(self):
		"""A guard that matches nothing passes forever. The stock screen is the
		busiest in the app; if the patterns stop matching there, they have
		drifted and this file needs rewriting rather than deleting."""
		source = _js("a3_stock.js")
		found = set(DISPATCH.findall(source)) | set(HANDLER.findall(source))
		self.assertGreater(len(found), 15, "the dispatch patterns no longer match the screens")
		self.assertIn("openImport", found, "Import Items is dispatched from a button")
