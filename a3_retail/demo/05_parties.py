"""Seed 05 — Customer groups, territories, 8 Customers, 8 Suppliers (scope 1.3, 1.4)."""

import frappe

from a3_retail.api.customer import normalize_mobile
from a3_retail.utils.gst import normalize_gstin

CUSTOMER_GROUPS = [
	"Retail Walk-in",
	"Corporate",
	"Dealer / Reseller",
	"Staff",
	"Insurance / Financier",
]

TERRITORIES = ["Kerala", "Ernakulam", "Thiruvananthapuram", "Kozhikode"]

# name, mobile, group, territory, source branch, gstin, optin
CUSTOMERS = [
	("Rahul Krishnan", "9847012345", "Retail Walk-in", "Ernakulam", "Kochi", None, 1),
	("Anjali Nair", "9633045678", "Retail Walk-in", "Ernakulam", "Kochi", None, 1),
	("Suresh Kumar", "9895067890", "Retail Walk-in", "Thiruvananthapuram", "Thiruvananthapuram", None, 0),
	("Fathima Beevi", "9744078901", "Retail Walk-in", "Kozhikode", "Kozhikode", None, 1),
	("Zenith Softech Pvt Ltd", "9846089012", "Corporate", "Ernakulam", "Kochi", "32AAECZ1234R1Z8", 1),
	("Deepak Menon", "9995090123", "Retail Walk-in", "Ernakulam", "Kochi", None, 1),
	("Sarath Chandran", "9605001122", "Dealer / Reseller", "Ernakulam", "Kochi", "32AAFPS9876L1ZP", 1),
	("Meera Raghavan", "9847112233", "Retail Walk-in", "Thiruvananthapuram", "Thiruvananthapuram", None, 1),
]

# name, category, gst_category, gstin, rcm, credit days, warranty returns
SUPPLIERS = [
	("Samsung India Electronics Pvt Ltd", "Device Distributor", "Registered Regular", "29AAACS1234M1Z6", 0, 30, 1),
	("Apple India Distributor - Redington", "Device Distributor", "Registered Regular", "33AAACR5678N1Z2", 0, 21, 1),
	("Kerala Mobile Accessories", "Accessory Vendor", "Registered Regular", "32AAFFK4321P1Z9", 0, 15, 0),
	("Spare Hub Chennai", "Spare Parts", "Registered Regular", "33AAGCS8765Q1Z4", 0, 30, 1),
	("Sreekumar Transport (Goods Carriage)", "Courier", "Unregistered", None, 1, 0, 0),
	("Rajan Electricals (Local Repairs)", "Utilities & Office", "Unregistered", None, 1, 0, 0),
	("Blue Dart Express Ltd", "Courier", "Registered Regular", "32AAACB0446L1ZR", 0, 15, 0),
	("Kochi Realty (Shop Rent)", "Utilities & Office", "Unregistered", None, 1, 0, 0),
	# Counter-party for used devices taken in exchange (scope 2.4).
	("Walk-in Public (Unregistered)", "Unregistered Local", "Unregistered", None, 0, 0, 0),
]

ADDRESSES = {
	"Rahul Krishnan": ("Aluva", "Ernakulam", "683101"),
	"Anjali Nair": ("Kakkanad", "Ernakulam", "682030"),
	"Suresh Kumar": ("Pattom", "Thiruvananthapuram", "695004"),
	"Fathima Beevi": ("Mavoor Road", "Kozhikode", "673004"),
	"Zenith Softech Pvt Ltd": ("Infopark Phase 1", "Ernakulam", "682042"),
}


def run():
	_customer_groups()
	_territories()
	_customers()
	_suppliers()


def _customer_groups():
	for group in CUSTOMER_GROUPS:
		if frappe.db.exists("Customer Group", group):
			continue
		doc = frappe.new_doc("Customer Group")
		doc.customer_group_name = group
		doc.parent_customer_group = "All Customer Groups"
		doc.is_group = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)


def _territories():
	for territory in TERRITORIES:
		if frappe.db.exists("Territory", territory):
			continue
		parent = "All Territories" if territory == "Kerala" else "Kerala"
		doc = frappe.new_doc("Territory")
		doc.territory_name = territory
		doc.parent_territory = parent
		doc.is_group = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	# Kerala must be a group once the districts hang off it.
	if frappe.db.exists("Territory", "Kerala") and not frappe.db.get_value("Territory", "Kerala", "is_group"):
		frappe.db.set_value("Territory", "Kerala", "is_group", 1, update_modified=False)


def _customers():
	for name, mobile, group, territory, branch, gstin, optin in CUSTOMERS:
		mobile = normalize_mobile(mobile)
		if frappe.db.exists("Customer", {"a3_mobile_no": mobile}):
			continue

		doc = frappe.new_doc("Customer")
		doc.customer_name = name
		doc.customer_type = "Company" if group == "Corporate" else "Individual"
		doc.customer_group = group
		doc.territory = territory
		doc.a3_mobile_no = mobile
		doc.a3_whatsapp_no = mobile
		doc.a3_source_branch = branch
		doc.a3_marketing_optin = optin
		doc.a3_customer_since = "2024-06-01"
		if gstin:
			doc.gstin = normalize_gstin(gstin)
			doc.gst_category = "Registered Regular"
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)

		if name in ADDRESSES:
			_address(name, "Customer", *ADDRESSES[name], mobile=mobile, gstin=gstin)


def _suppliers():
	for name, category, gst_category, gstin, rcm, credit_days, warranty in SUPPLIERS:
		if frappe.db.exists("Supplier", name):
			continue
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = name
		doc.supplier_group = _supplier_group()
		doc.country = "India"
		doc.a3_supplier_category = category
		doc.a3_is_rcm_applicable = rcm
		doc.a3_credit_days = credit_days
		doc.a3_warranty_return_allowed = warranty
		if doc.meta.has_field("gst_category"):
			doc.gst_category = gst_category
		if gstin:
			doc.gstin = normalize_gstin(gstin)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)

	# Point A3 Retail Settings at the exchange counter-party.
	if frappe.db.exists("Supplier", "Walk-in Public (Unregistered)"):
		if not frappe.db.get_single_value("A3 Retail Settings", "walkin_public_supplier"):
			frappe.db.set_single_value(
				"A3 Retail Settings", "walkin_public_supplier", "Walk-in Public (Unregistered)"
			)


def _supplier_group():
	for group in ("Local", "All Supplier Groups"):
		if frappe.db.exists("Supplier Group", group):
			return group
	return frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")


def _address(party_name, party_type, line1, city, pincode, mobile=None, gstin=None):
	title = f"{party_name}-Billing"
	if frappe.db.exists("Address", {"address_title": party_name, "address_type": "Billing"}):
		return
	doc = frappe.new_doc("Address")
	doc.address_title = party_name
	doc.address_type = "Billing"
	doc.address_line1 = line1
	doc.city = city
	doc.state = "Kerala"
	doc.country = "India"
	doc.pincode = pincode
	doc.phone = mobile
	if gstin and doc.meta.has_field("gstin"):
		doc.gstin = normalize_gstin(gstin)
		doc.gst_state = "Kerala"
	doc.append("links", {"link_doctype": party_type, "link_name": party_name})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return title
