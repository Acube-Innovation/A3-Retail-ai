"""Build tool: emit Frappe v15 DocType JSON + controller scaffolding for a3_retail.

Not shipped with the app — this lives in the scratchpad and is executed with the
bench python so the generated JSON always matches what `bench migrate` expects.
"""

import json
import os
import re

APP = "/home/user/A3-Retail/a3_retail/apps/a3_retail/a3_retail"
STAMP = "2026-08-05 09:00:00.000000"

MODULE_DIRS = {
    "A3 Retail Service": "a3_retail_service",
    "A3 Retail Sales": "a3_retail_sales",
    "A3 Retail Finance": "a3_retail_finance",
    "A3 Retail Warranty": "a3_retail_warranty",
    "A3 Retail Communication": "a3_retail_communication",
    "A3 Retail Operations": "a3_retail_operations",
    "A3 Retail Dashboard": "a3_retail_dashboard",
}

PERM_FLAGS = {
    "C": ["create"],
    "R": ["read"],
    "U": ["write"],
    "D": ["delete"],
    "S": ["submit", "cancel", "amend"],
}


def scrub(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def camel(name: str) -> str:
    return "".join(p for p in re.split(r"[\s_-]+", name) if p)


def f(fieldname, fieldtype="Data", label=None, options=None, **kw):
    """One DocField. Unknown kwargs are passed straight into the JSON."""
    d = {"fieldname": fieldname, "fieldtype": fieldtype}
    if label is not None:
        d["label"] = label
    elif fieldtype not in ("Section Break", "Column Break", "Tab Break"):
        d["label"] = fieldname.replace("_", " ").title()
    if options is not None:
        d["options"] = options
    d.update(kw)
    return d


def sb(fieldname, label=None, **kw):
    return f(fieldname, "Section Break", label, **kw)


def cb(fieldname=None, **kw):
    cb.counter = getattr(cb, "counter", 0) + 1
    return f(fieldname or f"col_break_{cb.counter}", "Column Break", None, **kw)


def perms(spec):
    """[('Role', 'CRUDS'), ...] -> permission rows. 'R@1' sets permlevel 1."""
    rows = []
    for role, flags in spec:
        permlevel = 0
        if "@" in flags:
            flags, level = flags.split("@")
            permlevel = int(level)
        row = {
            "role": role,
            "permlevel": permlevel,
            "read": 0, "write": 0, "create": 0, "delete": 0,
            "submit": 0, "cancel": 0, "amend": 0,
            "report": 1, "export": 1, "print": 1, "email": 1, "share": 1,
        }
        for ch in flags.upper():
            for key in PERM_FLAGS.get(ch, []):
                row[key] = 1
        if permlevel:
            for key in ("report", "export", "print", "email", "share"):
                row[key] = 0
        rows.append(row)
    return rows


DEFAULT_PERMS = [("System Manager", "CRUDS"), ("A3 Retail Admin", "CRUDS")]


class DT:
    def __init__(self, name, module, fields, perms_spec=None, **opts):
        self.name = name
        self.module = module
        self.fields = fields
        self.perms_spec = perms_spec if perms_spec is not None else DEFAULT_PERMS
        self.opts = opts

    def to_json(self):
        istable = self.opts.get("istable", 0)
        doc = {
            "actions": [],
            "allow_rename": self.opts.get("allow_rename", 1),
            "creation": STAMP,
            "doctype": "DocType",
            "editable_grid": 1,
            "engine": "InnoDB",
            "field_order": [fd["fieldname"] for fd in self.fields],
            "fields": self.fields,
            "index_web_pages_for_search": 1,
            "links": self.opts.get("links", []),
            "modified": STAMP,
            "modified_by": "Administrator",
            "module": self.module,
            "name": self.name,
            "owner": "Administrator",
            "permissions": [] if istable else perms(self.perms_spec),
            "sort_field": self.opts.get("sort_field", "creation"),
            "sort_order": self.opts.get("sort_order", "DESC"),
            "states": [],
        }
        passthrough = (
            "autoname", "naming_rule", "is_submittable", "istable", "issingle",
            "title_field", "search_fields", "track_changes", "track_seen",
            "quick_entry", "show_name_in_global_search", "editable_grid",
            "allow_import", "allow_copy", "max_attachments", "image_field",
            "default_print_format", "description", "document_type", "icon",
            "is_tree", "nsm_parent_field", "translated_doctype", "hide_toolbar",
            "allow_events_in_timeline", "make_attachments_public", "grid_page_length",
            "row_format", "protect_attached_files", "force_re_route_to_default_view",
            "is_calendar_and_gantt", "email_append_to", "sender_field", "subject_field",
        )
        for key in passthrough:
            if key in self.opts:
                doc[key] = self.opts[key]
        if not istable and "naming_rule" not in doc and "autoname" in doc:
            auto = doc["autoname"]
            if auto.startswith("field:"):
                doc["naming_rule"] = "By fieldname"
            elif auto == "prompt":
                doc["naming_rule"] = "Set by user"
            elif "#" in auto:
                doc["naming_rule"] = "Expression"
            elif auto.startswith("naming_series"):
                doc["naming_rule"] = "By \"Naming Series\" field"
        return doc

    @property
    def path(self):
        return os.path.join(APP, MODULE_DIRS[self.module], "doctype", scrub(self.name))

    def write(self, controller: str | None = None, client: str | None = None, test: str | None = None):
        folder = self.path
        os.makedirs(folder, exist_ok=True)
        s = scrub(self.name)

        init = os.path.join(folder, "__init__.py")
        if not os.path.exists(init):
            open(init, "w").close()

        with open(os.path.join(folder, f"{s}.json"), "w") as fh:
            json.dump(self.to_json(), fh, indent=1, sort_keys=False)
            fh.write("\n")

        py = os.path.join(folder, f"{s}.py")
        if controller is not None:
            open(py, "w").write(controller)
        elif not os.path.exists(py):
            open(py, "w").write(default_controller(self.name, self.opts.get("istable", 0)))

        if not self.opts.get("istable"):
            js = os.path.join(folder, f"{s}.js")
            if client is not None:
                open(js, "w").write(client)
            elif not os.path.exists(js):
                open(js, "w").write(default_client(self.name))

            tf = os.path.join(folder, f"test_{s}.py")
            if test is not None:
                open(tf, "w").write(test)
            elif not os.path.exists(tf):
                open(tf, "w").write(default_test(self.name))

        print(f"  {self.name:<38} -> {os.path.relpath(folder, APP)}")
        return self


def default_controller(name, istable=0):
    base = "Document"
    return f'''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import {base}


class {camel(name)}({base}):
	pass
'''


def default_client(name):
    return f'''// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("{name}", {{
	refresh(frm) {{}},
}});
'''


def default_test(name):
    return f'''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase


class Test{camel(name)}(FrappeTestCase):
	def test_doctype_exists(self):
		import frappe

		self.assertTrue(frappe.db.exists("DocType", "{name}"))
'''


def write_all(*doctypes):
    for dt in doctypes:
        dt.write()
