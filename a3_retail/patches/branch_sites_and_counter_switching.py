# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Say which counters stand in the same shop, and let their staff move between.

PhoneXpert runs two tills at UK — sales on one side, accessories on the other —
and often one person working both. Until now each had its own login and the
only way across was to sign out and sign in again, which is half a minute at a
time, dozens of times a day, with a customer waiting through every one of them.

Two small things make it work, and both are on records the shop can edit
afterwards without anybody's help:

  * `Branch Profile.site` groups counters by the address they stand at. The
    name before "Sales" or "Accessories" is the address, so the site is read
    from the branch's own name rather than typed in.
  * `Employee.a3_can_switch_counter` says this person may work the others at
    their site. Set here for the tills at a site that has more than one
    counter; everybody else is untouched and sees exactly their own branch, as
    before.

Nothing about permissions changes. A person switched to another counter is
subject to that counter's rules in the ordinary way, and a branch outside
their own site is not offered at all.
"""

import frappe
from frappe.utils import cint

# One definition of how a branch name comes apart, on the doctype that now
# fills `site` in for itself when a new branch is made.
from a3_retail.a3_retail_operations.doctype.branch_profile.branch_profile import (  # noqa: E402
	site_of as _site_of_branch,
)


def execute():
	if not frappe.db.has_column("Branch Profile", "site"):
		# The doctype change has not landed on this site yet.
		return

	named = _name_the_sites()
	granted = _grant_the_shared_sites()

	frappe.db.commit()
	print(f"  {named} branch(es) given a site")
	print(f"  {granted} till(s) may now work the other counter at their site")


def _name_the_sites() -> int:
	"""Read each branch's site out of its own name."""
	changed = 0
	for row in frappe.get_all("Branch Profile", fields=["name", "branch", "site"]):
		if (row.site or "").strip():
			continue
		site = _site_of(row.branch)
		if not site:
			continue
		frappe.db.set_value("Branch Profile", row.name, "site", site,
		                    update_modified=False)
		changed += 1
	return changed


def _site_of(branch: str) -> str | None:
	"""The address part of a branch name — what is left after the counter.

	"PhoneXpert Sales UK" and "PhoneXpert Accessories UK" are both UK;
	"PhoneXpert Distribution" is its own place and keeps its whole name.
	"""
	return _site_of_branch(branch)


def _grant_the_shared_sites() -> int:
	"""Tick the flag for staff at a site that has more than one counter.

	Only where there is somewhere to switch *to*: a lone branch gains nothing
	from the setting and the picker would show one option.
	"""
	if not frappe.db.has_column("Employee", "a3_can_switch_counter"):
		return 0

	sites: dict[str, set] = {}
	for row in frappe.get_all("Branch Profile",
	                          filters={"is_active": 1}, fields=["branch", "site"]):
		if row.site:
			sites.setdefault(row.site, set()).add(row.branch)

	shared = {branch for branches in sites.values() if len(branches) > 1
	          for branch in branches}
	if not shared:
		return 0

	granted = 0
	for employee in frappe.get_all(
			"Employee",
			filters={"branch": ["in", sorted(shared)], "status": "Active"},
			fields=["name", "a3_can_switch_counter"]):
		if cint(employee.a3_can_switch_counter):
			continue
		frappe.db.set_value("Employee", employee.name, "a3_can_switch_counter", 1,
		                    update_modified=False)
		granted += 1
	return granted
