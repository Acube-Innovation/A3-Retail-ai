import sys

sys.path.insert(0, "/tmp/claude-1000/-home-user-A3-Retail-a3-retail/332d05bc-10e8-4f51-862d-398a6e39c87f/scratchpad")
from dtgen import DT, cb, f, sb, write_all

OPS = "A3 Retail Operations"

DAYS = "\n".join(["", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])

fields = [
    f("branch", "Link", "Branch", "Branch", reqd=1, unique=1, in_list_view=1, in_standard_filter=1),
    f("branch_code", "Data", "Branch Code", reqd=1, unique=1, in_list_view=1,
      description="3-letter uppercase code used in naming series, e.g. KCH"),
    f("branch_type", "Select", "Branch Type", "Sales Only\nService Only\nSales & Service",
      default="Sales & Service", reqd=1, in_list_view=1),
    f("is_head_office", "Check", "Is Head Office"),
    f("is_active", "Check", "Active", default="1", in_standard_filter=1),
    cb(),
    f("company", "Link", "Company", "Company", reqd=1),
    f("cost_center", "Link", "Cost Center", "Cost Center", reqd=1),
    f("address", "Link", "Branch Address", "Address"),
    f("gstin", "Data", "GSTIN", length=15),
    f("state_code", "Data", "GST State Code", read_only=1, length=2),

    sb("contact_section", "Contact"),
    f("contact_no", "Data", "Contact Number", options="Phone"),
    f("branch_email", "Data", "Branch Email", options="Email"),
    cb(),
    f("latitude", "Float", "Latitude", precision="6", description="Used for geofenced attendance"),
    f("longitude", "Float", "Longitude", precision="6"),
    f("geofence_radius_metres", "Int", "Geofence Radius (m)", default="200"),

    sb("stock_section", "Stock Defaults"),
    f("default_warehouse", "Link", "Selling Warehouse", "Warehouse"),
    f("service_warehouse", "Link", "Service Bay Warehouse", "Warehouse",
      description="Spare parts issued to technicians"),
    cb(),
    f("damaged_warehouse", "Link", "Damaged Goods Warehouse", "Warehouse"),
    f("used_device_warehouse", "Link", "Used Devices Warehouse", "Warehouse"),
    f("transit_warehouse", "Link", "Goods In Transit", "Warehouse",
      description="Shared company-level in-transit warehouse"),

    sb("sales_section", "Sales Defaults"),
    f("pos_profile", "Link", "POS Profile", "POS Profile"),
    f("default_price_list", "Link", "Selling Price List", "Price List"),
    cb(),
    f("default_income_account", "Link", "Income Account", "Account"),
    f("sales_cost_center", "Link", "Sales Cost Center", "Cost Center"),
    f("service_cost_center", "Link", "Service Cost Center", "Cost Center"),

    sb("service_section", "Service Defaults"),
    f("branch_manager", "Link", "Branch Manager", "Employee", reqd=1),
    f("service_manager", "Link", "Service Manager", "Employee"),
    f("default_tat_hours", "Int", "Default TAT (hours)", default="48"),
    cb(),
    f("working_hours_from", "Time", "Working Hours From", default="09:30:00"),
    f("working_hours_to", "Time", "Working Hours To", default="20:00:00"),
    f("weekly_off", "Select", "Weekly Off", DAYS, default="Sunday"),
    f("holiday_list", "Link", "Holiday List", "Holiday List"),

    sb("communication_section", "Communication"),
    f("whatsapp_sender_sales", "Link", "WhatsApp Sender (Sales)", "WhatsApp Sender Profile"),
    f("whatsapp_sender_service", "Link", "WhatsApp Sender (Service)", "WhatsApp Sender Profile"),
    cb(),
    f("letter_head", "Link", "Letter Head", "Letter Head"),

    sb("capacity_section", "Capacity & Targets"),
    f("daily_footfall_target", "Int", "Footfall Target / Day"),
    f("monthly_sales_target", "Currency", "Monthly Sales Target"),
    cb(),
    f("monthly_service_target", "Int", "Monthly Service Target"),
]

CONTROLLER = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Branch Profile — the operational master for a branch (scope 1.1).

One Company, many branches (ADR-01). A branch is the tuple of
Branch + Cost Center + warehouse group + POS Profile, and this document is where
all of that is declared so every other module can resolve defaults from it.
"""

import frappe
from frappe import _
from frappe.model.document import Document

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
		if self.working_hours_from and self.working_hours_to:
			if str(self.working_hours_to) <= str(self.working_hours_from):
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
'''

CLIENT = '''// Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors

frappe.ui.form.on("Branch Profile", {
	setup(frm) {
		// Only leaf warehouses of this company can hold stock.
		["default_warehouse", "service_warehouse", "damaged_warehouse", "used_device_warehouse"].forEach(
			(field) => {
				frm.set_query(field, () => ({
					filters: { company: frm.doc.company, is_group: 0 },
				}));
			}
		);
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("branch_manager", () => ({ filters: { status: "Active" } }));
		frm.set_query("service_manager", () => ({ filters: { status: "Active" } }));
	},

	branch_code(frm) {
		if (frm.doc.branch_code) {
			frm.set_value("branch_code", frm.doc.branch_code.toUpperCase());
		}
	},

	gstin(frm) {
		if (frm.doc.gstin && frm.doc.gstin.length >= 2) {
			frm.set_value("state_code", frm.doc.gstin.substring(0, 2));
		}
	},

	refresh(frm) {
		if (frm.doc.__islocal) return;
		frm.add_custom_button(__("Stock Explorer"), () =>
			frappe.set_route("a3-stock-explorer", { branch: frm.doc.branch })
		);
	},
});
'''

TEST = '''# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.tests.fixtures import ensure_branch, ensure_company


class TestBranchProfile(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()

	def test_branch_creates_four_warehouses(self):
		profile = ensure_branch("Kochi", "KCH")
		for field in ("default_warehouse", "service_warehouse", "damaged_warehouse", "used_device_warehouse"):
			self.assertTrue(profile.get(field), f"{field} was not auto-created")
			self.assertFalse(frappe.db.get_value("Warehouse", profile.get(field), "is_group"))

	def test_state_code_derived_from_gstin(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.gstin = "32AABCM1234K1Z5"
		profile.save()
		self.assertEqual(profile.state_code, "32")

	def test_short_gstin_is_rejected(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.gstin = "32AABCM"
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()

	def test_branch_code_is_uppercased(self):
		profile = ensure_branch("Thiruvananthapuram", "tvm")
		self.assertEqual(profile.branch_code, "TVM")

	def test_group_cost_center_is_rejected(self):
		profile = ensure_branch("Kochi", "KCH")
		group_cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
		profile.cost_center = group_cc
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()

	def test_warehouse_carries_branch_backreference(self):
		profile = ensure_branch("Kochi", "KCH")
		self.assertEqual(
			frappe.db.get_value("Warehouse", profile.default_warehouse, "custom_branch"), profile.branch
		)

	def test_working_hours_must_be_ordered(self):
		profile = ensure_branch("Kochi", "KCH")
		profile.working_hours_from = "20:00:00"
		profile.working_hours_to = "09:30:00"
		self.assertRaises(frappe.ValidationError, profile.save)
		profile.reload()
'''

print("Step 2 — branch model")
DT(
    "Branch Profile",
    OPS,
    fields,
    autoname="field:branch",
    title_field="branch",
    search_fields="branch_code,branch_type",
    track_changes=1,
    sort_field="branch_code",
    sort_order="ASC",
    perms_spec=[
        ("System Manager", "CRUD"),
        ("A3 Retail Admin", "CRUD"),
        ("Branch Manager", "R"),
        ("Service Manager", "R"),
        ("Sales Executive", "R"),
        ("Reception Executive", "R"),
        ("Store Keeper", "R"),
        ("Accounts Manager", "R"),
        ("HR Manager", "R"),
        ("Technician", "R"),
    ],
).write(controller=CONTROLLER, client=CLIENT, test=TEST)
