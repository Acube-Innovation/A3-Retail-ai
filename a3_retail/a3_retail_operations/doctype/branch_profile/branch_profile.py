# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Profile — the operational master for a branch (scope 1.1).

One Company, many branches (ADR-01). A branch is the tuple of
Branch + Cost Center + warehouse group + POS Profile, and this document is where
all of that is declared so every other module can resolve defaults from it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time

WAREHOUSE_SUFFIXES = {
	"default_warehouse": "Store",
	"service_warehouse": "Service Bay",
	"damaged_warehouse": "Damaged",
	"used_device_warehouse": "Used Devices",
}

# Branch types that do not repair devices do not need a service bay.
SERVICE_TYPES = ("Service Only", "Sales & Service")


class BranchProfile(Document):
	def validate(self):
		self.set_state_code()
		self.validate_branch_code()
		self.validate_cost_center()
		self.validate_warehouses()
		self.validate_working_hours()

	def after_insert(self):
		self.create_branch_warehouses()

	def on_update(self):
		self.stamp_branch_on_linked_records()

	# ------------------------------------------------------------------ validate
	def set_state_code(self):
		"""GST state code is the first two digits of the GSTIN."""
		gstin = (self.gstin or "").strip().upper()
		if gstin:
			self.gstin = gstin
			if len(gstin) != 15:
				frappe.throw(_("GSTIN must be 15 characters."))
			if not gstin[:2].isdigit():
				frappe.throw(_("GSTIN must start with a two-digit state code."))
			self.state_code = gstin[:2]
		else:
			self.state_code = None

	def validate_branch_code(self):
		code = (self.branch_code or "").strip().upper()
		if not code:
			frappe.throw(_("Branch Code is required."))
		if not code.isalnum() or len(code) > 4:
			frappe.throw(_("Branch Code must be up to 4 alphanumeric characters, e.g. KCH."))
		self.branch_code = code

	def validate_cost_center(self):
		if not self.cost_center:
			return
		cc_company, is_group = frappe.db.get_value("Cost Center", self.cost_center, ["company", "is_group"])
		if cc_company != self.company:
			frappe.throw(
				_("Cost Center {0} belongs to {1}, not {2}.").format(self.cost_center, cc_company, self.company)
			)
		if is_group:
			frappe.throw(_("Cost Center {0} is a group. Pick a leaf cost center.").format(self.cost_center))

	def validate_warehouses(self):
		"""Stock can only be posted against leaf warehouses of the same company."""
		for fieldname in (*WAREHOUSE_SUFFIXES, "transit_warehouse"):
			warehouse = self.get(fieldname)
			if not warehouse:
				continue
			company, is_group = frappe.db.get_value("Warehouse", warehouse, ["company", "is_group"])
			if is_group:
				frappe.throw(
					_("{0}: {1} is a warehouse group. Pick a leaf warehouse.").format(
						_(self.meta.get_label(fieldname)), warehouse
					)
				)
			if company != self.company:
				frappe.throw(
					_("{0}: {1} belongs to company {2}.").format(
						_(self.meta.get_label(fieldname)), warehouse, company
					)
				)

	def validate_working_hours(self):
		# Time fields come back from the DB as timedelta ("9:30:00", no leading
		# zero), so they must be normalised before comparing — a string compare
		# would rank "20:00:00" before "9:30:00".
		if self.working_hours_from and self.working_hours_to:
			if get_time(self.working_hours_to) <= get_time(self.working_hours_from):
				frappe.throw(_("Working Hours To must be later than Working Hours From."))

	# --------------------------------------------------------------- automation
	def create_branch_warehouses(self):
		"""Create the four branch warehouses that were left blank (scope 1.1)."""
		parent = get_or_create_branch_group(self.company)
		abbr = frappe.get_cached_value("Company", self.company, "abbr")

		for fieldname, suffix in WAREHOUSE_SUFFIXES.items():
			if self.get(fieldname):
				continue
			if fieldname == "service_warehouse" and self.branch_type not in SERVICE_TYPES:
				continue

			warehouse_name = f"{self.branch} {suffix}"
			full_name = f"{warehouse_name} - {abbr}"
			if not frappe.db.exists("Warehouse", full_name):
				warehouse = frappe.new_doc("Warehouse")
				warehouse.warehouse_name = warehouse_name
				warehouse.parent_warehouse = parent
				warehouse.company = self.company
				warehouse.is_group = 0
				warehouse.flags.ignore_permissions = True
				warehouse.insert(ignore_permissions=True)
				full_name = warehouse.name

			self.db_set(fieldname, full_name, update_modified=False)

		if not self.transit_warehouse:
			self.db_set("transit_warehouse", get_or_create_transit_warehouse(self.company), update_modified=False)

	def stamp_branch_on_linked_records(self):
		"""Keep `custom_branch` on Warehouse / Cost Center in step with this profile.

		The Stock Availability Explorer groups Bin rows by `Warehouse.custom_branch`,
		so this back-reference is what makes cross-branch availability possible.
		"""
		warehouses = [self.get(fn) for fn in (*WAREHOUSE_SUFFIXES,) if self.get(fn)]
		for warehouse in warehouses:
			if frappe.db.get_value("Warehouse", warehouse, "custom_branch") != self.branch:
				frappe.db.set_value("Warehouse", warehouse, "custom_branch", self.branch, update_modified=False)

		for cost_center in (self.cost_center, self.sales_cost_center, self.service_cost_center):
			if cost_center and frappe.db.get_value("Cost Center", cost_center, "custom_branch") != self.branch:
				frappe.db.set_value("Cost Center", cost_center, "custom_branch", self.branch, update_modified=False)

		if self.pos_profile and frappe.db.has_column("POS Profile", "custom_branch"):
			frappe.db.set_value("POS Profile", self.pos_profile, "custom_branch", self.branch, update_modified=False)


def get_or_create_branch_group(company: str) -> str:
	"""`Branches - <ABBR>` group under the company's root warehouse."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"Branches - {abbr}"
	if frappe.db.exists("Warehouse", name):
		return name

	root = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ""}, "name")
	group = frappe.new_doc("Warehouse")
	group.warehouse_name = "Branches"
	group.company = company
	group.is_group = 1
	group.parent_warehouse = root
	group.flags.ignore_permissions = True
	group.insert(ignore_permissions=True)
	return group.name


def get_or_create_transit_warehouse(company: str) -> str:
	"""Company-level in-transit warehouse used by inter-branch transfers (scope 6.2)."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"Goods In Transit - {abbr}"
	if frappe.db.exists("Warehouse", name):
		if not frappe.db.get_value("Warehouse", name, "warehouse_type"):
			frappe.db.set_value("Warehouse", name, "warehouse_type", "Transit")
		return name

	root = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ""}, "name")
	warehouse = frappe.new_doc("Warehouse")
	warehouse.warehouse_name = "Goods In Transit"
	warehouse.company = company
	warehouse.is_group = 0
	warehouse.parent_warehouse = root
	warehouse.warehouse_type = "Transit"
	warehouse.flags.ignore_permissions = True
	warehouse.insert(ignore_permissions=True)
	return warehouse.name


@frappe.whitelist()
def get_branch_defaults(branch: str) -> dict:
	"""Defaults for a branch, used by custom pages and client scripts."""
	from a3_retail.api import require_permission

	require_permission("Branch Profile", "read")
	name = frappe.db.get_value("Branch Profile", {"branch": branch}, "name")
	if not name:
		return {}

	profile = frappe.get_cached_doc("Branch Profile", name)
	return {
		"branch": profile.branch,
		"branch_code": profile.branch_code,
		"company": profile.company,
		"cost_center": profile.cost_center,
		"default_warehouse": profile.default_warehouse,
		"service_warehouse": profile.service_warehouse,
		"pos_profile": profile.pos_profile,
		"price_list": profile.default_price_list,
		"default_tat_hours": profile.default_tat_hours,
		"letter_head": profile.letter_head,
	}
