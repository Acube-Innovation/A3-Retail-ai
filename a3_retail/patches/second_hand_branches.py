# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Open the two second-hand counters, and the line their GST rides on.

PhoneXpert buys used handsets from customers and sells them on. That trade is
taxed differently from new stock — GST on the margin, under Rule 32(5) — and
is kept at its own counter at each of the two shops so the margin, the stock
and the profit can all be read on their own.

Three things are set up here.

**The branches.** `PhoneXpert Used PSLA` and `PhoneXpert Used UK`, each with a
Branch Profile sitting at the same site as the shop it belongs to, so a till
that may work both counters is offered this one too.

**A warehouse of its own for each.** Used handsets must not sit with new stock:
every one was bought at a different price, the valuation is quite different,
and the margin can only be worked out against the handset's own purchase cost.

**The margin line item.** A used-device bill carries two lines — the handset at
what the shop paid for it, nil rated, and the margin, taxed. `USED-DEVICE-MARGIN`
is that second line. Without it a used device cannot be billed at all.

Nothing here is destructive and it can be run again: anything already on file is
left exactly as it is.
"""

import frappe

MARGIN_ITEM = "USED-DEVICE-MARGIN"

# Codes follow the shop's own three-letter convention — ACP/ACU for
# Accessories, SLP/SLU for Sales, SVP/SVU for Service — so USP and USU for
# Used. Branch Profile caps them at four characters.
BRANCHES = [
	{"branch": "PhoneXpert Used PSLA", "code": "USP", "site": "PSLA",
	 "after": "PhoneXpert Sales PSLA"},
	{"branch": "PhoneXpert Used UK", "code": "USU", "site": "UK",
	 "after": "PhoneXpert Sales UK"},
]


def execute():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		return

	made_item = _margin_item(company)
	opened, already = [], []

	for spec in BRANCHES:
		if frappe.db.exists("Branch", spec["branch"]):
			already.append(spec["branch"])
			continue
		_open_branch(spec, company)
		opened.append(spec["branch"])

	frappe.db.commit()

	print(f"  margin line item: {'created' if made_item else 'already there'} "
	      f"({MARGIN_ITEM})")
	print(f"  {len(opened)} second-hand counter(s) opened")
	for name in opened:
		print(f"      {name}")
	if already:
		print(f"  {len(already)} already on file, left alone: {', '.join(already)}")


def _open_branch(spec, company):
	branch = frappe.new_doc("Branch")
	branch.branch = spec["branch"]
	branch.flags.ignore_permissions = True
	branch.insert(ignore_permissions=True)

	# Its own shelf. Used stock mixed in with new cannot be valued or counted.
	warehouse = _warehouse(spec["branch"], company)
	# And its own cost centre, so the used trade's profit is readable on its
	# own rather than buried in the shop it stands in.
	cost_center = _cost_center(spec["branch"], company)

	profile = frappe.new_doc("Branch Profile")
	profile.branch = spec["branch"]
	profile.is_active = 1
	if profile.meta.has_field("branch_code"):
		profile.branch_code = spec["code"]
	if profile.meta.has_field("site"):
		profile.site = spec["site"]
	if profile.meta.has_field("branch_type"):
		profile.branch_type = "Sales Only"
	if profile.meta.has_field("default_warehouse"):
		profile.default_warehouse = warehouse
	if profile.meta.has_field("used_device_warehouse"):
		profile.used_device_warehouse = warehouse
	if profile.meta.has_field("company"):
		profile.company = company
	profile.cost_center = cost_center
	# Who runs it is the shop's own decision; until they say, the counter next
	# door's manager is the honest answer rather than a blank.
	profile.branch_manager = frappe.db.get_value(
		"Branch Profile", {"branch": spec["after"]}, "branch_manager")

	# The shop it belongs to already knows the address, the number and which
	# Google listing a customer should review; a second-hand counter at the
	# same door shares all three.
	neighbour = frappe.db.get_value("Branch Profile", {"branch": spec["after"]},
	                                ["address", "contact_no", "state_code",
	                                 "google_review_code"], as_dict=True)
	if neighbour:
		for field, value in neighbour.items():
			if value and profile.meta.has_field(field):
				profile.set(field, value)

	profile.flags.ignore_permissions = True
	profile.insert(ignore_permissions=True)


def _cost_center(branch: str, company: str) -> str:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{branch} Sales - {abbr}"
	if frappe.db.exists("Cost Center", name):
		return name

	doc = frappe.new_doc("Cost Center")
	doc.cost_center_name = f"{branch} Sales"
	doc.company = company
	doc.is_group = 0
	parent = (frappe.db.get_value("Cost Center",
	                              {"company": company, "is_group": 1,
	                               "cost_center_name": ["like", "%PhoneXpert%"]}, "name")
	          or frappe.db.get_value("Cost Center",
	                                 {"company": company, "is_group": 1}, "name"))
	doc.parent_cost_center = parent
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _warehouse(branch: str, company: str) -> str:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{branch} - {abbr}"
	if frappe.db.exists("Warehouse", name):
		return name

	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = branch
	doc.company = company
	doc.is_group = 0
	parent = frappe.db.get_value("Warehouse",
	                             {"company": company, "is_group": 1}, "name")
	if parent:
		doc.parent_warehouse = parent
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _margin_item(company: str) -> bool:
	"""The line a used-device bill puts its taxable value on.

	Not stock: it is the value of supply, not a thing on a shelf. It carries
	the ordinary rate for a phone, because a used phone is taxed at the rate of
	a phone — only the value it is charged on is different.
	"""
	if frappe.db.exists("Item", MARGIN_ITEM):
		return False

	group = (frappe.db.get_value("Item Group", {"item_group_name": "Services"}, "name")
	         or frappe.db.get_value("Item Group", {"is_group": 0}, "name"))

	doc = frappe.new_doc("Item")
	doc.item_code = MARGIN_ITEM
	doc.item_name = "Margin on used device"
	doc.description = ("The value of supply on a second-hand sale under "
	                   "Rule 32(5): selling price less purchase price.")
	doc.item_group = group
	doc.stock_uom = "Nos"
	doc.is_stock_item = 0
	doc.is_sales_item = 1
	doc.is_purchase_item = 0
	# A used phone is taxed at a phone's rate; this line is where that lands.
	hsn = frappe.db.sql("""select gst_hsn_code from `tabItem`
	                       where ifnull(gst_hsn_code, '') != ''
	                         and ifnull(a3_is_margin_scheme, 0) = 1 limit 1""")
	if not hsn:
		hsn = frappe.db.sql("""select gst_hsn_code from `tabItem`
		                       where ifnull(gst_hsn_code, '') != ''
		                         and item_name like '%%IPHONE%%' limit 1""")
	if hsn and doc.meta.has_field("gst_hsn_code"):
		doc.gst_hsn_code = hsn[0][0]

	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return True
