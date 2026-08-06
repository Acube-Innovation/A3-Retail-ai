# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Security audit for the whitelisted surface (scope step 26).

`frappe.whitelist()` only proves the caller is logged in. Every endpoint this app
exposes must therefore do one of three things: check a permission itself, be a
document method (where Frappe has already checked write access on the document),
or be a guest endpoint that validates a signed token or a verified OTP.

    bench --site <site> execute a3_retail.setup.audit.run

The audit reads the source rather than the runtime, so it catches an endpoint
added without a check even when no test exercises it.
"""

import ast
import os

import frappe

APP = "a3_retail"

# Anything that proves the caller is allowed to be here.
GUARDS = {
	"require_permission",
	"require_role",
	"require_branch_access",
	"has_permission",
	"verify_session_token",
	"verify_token",
	"verify",
	"verify_signature",
	"resolve_token",
	"check_permission",
	"only_for",
	# The branch portal's own gate: refuses a guest, and refuses anyone whose
	# account is not linked to an active Employee (api/staff.py).
	"_me",
}

# Guest endpoints that are safe without a document permission, with the reason.
DOCUMENTED_EXCEPTIONS = {
	"a3_retail.api.portal.request_otp": "rate-limited OTP issue; no data returned",
	"a3_retail.api.portal.verify_otp": "OTP check itself",
	"a3_retail.api.portal.active_offers": "public marketing list (scope 13.1)",
	"a3_retail.api.portal.store_locator": "public branch list (scope 13.1)",
	"a3_retail.api.whatsapp.webhook": "provider callback, verified by token",
	"a3_retail.api.payments.razorpay_webhook": "gateway callback, verified by HMAC",
}


def run(verbose: bool = True) -> dict:
	findings = []
	whitelisted = 0

	for path in _python_files():
		module = _module_name(path)
		tree = ast.parse(open(path).read(), filename=path)

		for node in ast.walk(tree):
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			if not _is_whitelisted(node):
				continue

			whitelisted += 1
			qualified = f"{module}.{node.name}"

			if qualified in DOCUMENTED_EXCEPTIONS:
				continue
			if _is_document_method(node, tree):
				continue
			if _has_guard(node):
				continue

			findings.append(
				{
					"method": qualified,
					"line": node.lineno,
					"guest": _allows_guest(node),
					"file": os.path.relpath(path, frappe.get_app_path(APP)),
				}
			)

	if verbose:
		print(f"\nWhitelisted methods: {whitelisted}")
		print(f"Documented exceptions: {len(DOCUMENTED_EXCEPTIONS)}")
		if findings:
			print(f"\nUnguarded ({len(findings)}):")
			for finding in findings:
				flag = " [GUEST]" if finding["guest"] else ""
				print(f"  {finding['method']}{flag}  {finding['file']}:{finding['line']}")
		else:
			print("\nEvery whitelisted method checks a permission, a token or an OTP.")

	return {"whitelisted": whitelisted, "unguarded": findings}


def _python_files() -> list[str]:
	root = frappe.get_app_path(APP)
	files = []
	for folder, _dirs, names in os.walk(root):
		if "node_modules" in folder or "__pycache__" in folder:
			continue
		files.extend(os.path.join(folder, name) for name in names if name.endswith(".py"))
	return sorted(files)


def _module_name(path: str) -> str:
	relative = os.path.relpath(path, os.path.dirname(frappe.get_app_path(APP)))
	return relative[:-3].replace(os.sep, ".").removesuffix(".__init__")


def _is_whitelisted(node) -> bool:
	return any(_decorator_name(d) == "whitelist" for d in node.decorator_list)


def _allows_guest(node) -> bool:
	for decorator in node.decorator_list:
		if _decorator_name(decorator) != "whitelist" or not isinstance(decorator, ast.Call):
			continue
		for keyword in decorator.keywords:
			if keyword.arg == "allow_guest" and getattr(keyword.value, "value", False):
				return True
	return False


def _decorator_name(decorator) -> str:
	target = decorator.func if isinstance(decorator, ast.Call) else decorator
	if isinstance(target, ast.Attribute):
		return target.attr
	if isinstance(target, ast.Name):
		return target.id
	return ""


def _is_document_method(node, tree) -> bool:
	"""A method on a Document subclass — Frappe checks access before calling it."""
	for parent in ast.walk(tree):
		if isinstance(parent, ast.ClassDef) and node in parent.body:
			return True
	return False


def _has_guard(node) -> bool:
	for child in ast.walk(node):
		if isinstance(child, ast.Call):
			name = _decorator_name(child)
			if name in GUARDS:
				return True
		if isinstance(child, ast.Attribute) and child.attr in GUARDS:
			return True
		if isinstance(child, ast.Name) and child.id in GUARDS:
			return True
	return False


def ignore_permissions_audit(verbose: bool = True) -> list[dict]:
	"""Where the app bypasses permissions, and whether the file says why.

	`ignore_permissions=True` is legitimate in setup code, demo seeds and
	system-initiated writes; it is a smell inside a whitelisted endpoint.
	"""
	allowed_prefixes = ("setup", "demo", "patches", "tests", "overrides", "communication")
	findings = []

	for path in _python_files():
		relative = os.path.relpath(path, frappe.get_app_path(APP))
		if relative.startswith(allowed_prefixes):
			continue

		source = open(path).read()
		if "ignore_permissions" not in source:
			continue

		tree = ast.parse(source, filename=path)
		for node in ast.walk(tree):
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_whitelisted(node):
				if f"{_module_name(path)}.{node.name}" in DOCUMENTED_EXCEPTIONS:
					continue
				segment = ast.get_source_segment(source, node) or ""
				if "ignore_permissions" in segment and not _has_guard(node):
					findings.append({"method": node.name, "file": relative, "line": node.lineno})

	if verbose:
		if findings:
			print(f"\nignore_permissions inside unguarded endpoints ({len(findings)}):")
			for finding in findings:
				print(f"  {finding['file']}:{finding['line']}  {finding['method']}")
		else:
			print("\nNo whitelisted endpoint bypasses permissions without a guard.")

	return findings
