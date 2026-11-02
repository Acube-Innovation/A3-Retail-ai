# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Brand Wise Sales — every line sold with its brand, and a summary per brand.

The brand is the one stamped on the sale line, else the item's own. A line with
neither is counted under Others (Non-Branded) rather than dropped, so the brands
always add up to the whole period's sales.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from a3_retail.reporting import build_conditions, col, default_period, percent

OTHERS = "Others (Non-Branded)"

# Offered beside the Brand list in the branch app's brand picker, so the
# unbranded lines can be looked at on their own.
EXTRA_CHOICES = {"brand": [OTHERS]}

BRAND = "coalesce(nullif(sii.brand, ''), nullif(item.brand, ''), %(others)s)"

COLUMNS = [
	col("Invoice", "invoice", "Link", 140, "Sales Invoice"),
	col("Date", "posting_date", "Date", 100),
	col("Branch", "branch", "Link", 110, "Branch"),
	col("Customer", "customer_name", "Data", 160),
	col("Item", "item_name", "Data", 220),
	col("Brand", "brand", "Data", 140),
	col("Qty", "qty", "Int", 70),
	col("Net Amount", "net_amount", "Currency", 120),
	col("Amount incl. GST", "gross_amount", "Currency", 130),
]

SUMMARY_COLUMNS = [
	col("Brand", "brand", "Data", 180),
	col("Bills", "bills", "Int", 80),
	col("Units Sold", "qty", "Int", 90),
	col("Net Amount", "net_amount", "Currency", 130),
	col("Amount incl. GST", "gross_amount", "Currency", 140),
	col("Share of Sales", "share", "Percent", 110),
]

# A line's amount with GST is its share of the bill's grand total, in proportion
# to its net — the bill's discount is already inside the net, and the tax follows
# it, so the lines of one bill add back up to exactly what the customer was billed.
SQL = f"""
select si.name as invoice, si.posting_date, si.branch, si.customer_name,
       sii.item_name, {BRAND} as brand, sii.qty,
       sii.base_net_amount as net_amount,
       case when si.base_net_total = 0 then 0
            else sii.base_net_amount * si.base_grand_total / si.base_net_total
       end as gross_amount
from `tabSales Invoice Item` sii
join `tabSales Invoice` si on si.name = sii.parent
left join `tabItem` item on item.name = sii.item_code
where si.docstatus = 1 and si.is_return = 0 {{conditions}}
order by {{order}}
"""


def execute(filters=None):
	filters = default_period(filters)
	brands = _chosen_brands(filters.get("brand"))
	extra = f"{BRAND} in %(brands)s" if brands else ""
	conditions, values = build_conditions(filters, "si", "branch", "si.posting_date", extra)
	values["others"] = OTHERS
	if brands:
		values["brands"] = tuple(brands)

	# Grouped, the register reads brand by brand under the summary above it.
	order = "brand, si.posting_date desc, si.name desc, sii.idx" if cint(
		filters.get("group_by_brand")) else "si.posting_date desc, si.name desc, sii.idx"
	data = frappe.db.sql(SQL.format(conditions=conditions, order=order), values, as_dict=True)
	for row in data:
		row.net_amount = flt(row.net_amount, 2)
		row.gross_amount = flt(row.gross_amount, 2)

	return COLUMNS, data, None, None, _number_cards(data)


def _chosen_brands(value) -> list[str]:
	"""The desk sends a list; a URL or an older client may send text."""
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.startswith("[") else value.split(",")
	return [str(brand).strip() for brand in value if str(brand).strip()]


def _number_cards(data: list[dict]) -> list[dict]:
	by_brand = {}
	for row in data:
		by_brand[row.brand] = by_brand.get(row.brand, 0) + row.net_amount
	named = [brand for brand in by_brand if brand != OTHERS]
	top = max(named, key=by_brand.get) if named else None

	return [
		{"label": _("Net Sales"), "value": flt(sum(row.net_amount for row in data), 2),
		 "datatype": "Currency"},
		{"label": _("Sales incl. GST"), "value": flt(sum(row.gross_amount for row in data), 2),
		 "datatype": "Currency"},
		{"label": _("Bills"), "value": len({row.invoice for row in data}), "datatype": "Int"},
		{"label": _("Units Sold"), "value": sum(cint(row.qty) for row in data),
		 "datatype": "Int"},
		{"label": _("Brands Sold"), "value": len(named), "datatype": "Int"},
		{"label": _("Top Brand"), "value": top or _("None yet"), "datatype": "Data"},
	]


def summary(filters, rows: list[dict]) -> dict | None:
	"""With Group by brand ticked: one row per brand — how many bills it was on,
	how many units went, and what it took — shown above the register.

	A bill with two brands on it counts once for each, so the Bills column does
	not add down; its total is the number of distinct bills instead.
	"""
	if not cint((filters or {}).get("group_by_brand")):
		return None

	brands = {}
	for row in rows:
		entry = brands.setdefault(row["brand"], {
			"brand": row["brand"], "bills": set(), "qty": 0,
			"net_amount": 0.0, "gross_amount": 0.0,
		})
		entry["bills"].add(row["invoice"])
		entry["qty"] += cint(row["qty"])
		entry["net_amount"] += flt(row["net_amount"])
		entry["gross_amount"] += flt(row["gross_amount"])

	net = sum(entry["net_amount"] for entry in brands.values())
	table = []
	# Biggest first; the unbranded lines last, whatever they came to.
	for entry in sorted(brands.values(),
	                    key=lambda e: (e["brand"] == OTHERS, -e["net_amount"])):
		table.append({**entry, "bills": len(entry["bills"]),
		              "net_amount": flt(entry["net_amount"], 2),
		              "gross_amount": flt(entry["gross_amount"], 2),
		              "share": percent(entry["net_amount"], net)})

	return {
		"title": _("Sales by brand"),
		"detail_title": _("Sales register"),
		"columns": SUMMARY_COLUMNS,
		"rows": table,
		"totals": {
			"bills": len({row["invoice"] for row in rows}),
			"qty": sum(entry["qty"] for entry in table),
			"net_amount": flt(net, 2),
			"gross_amount": flt(sum(entry["gross_amount"] for entry in table), 2),
			"share": 100.0 if table else 0.0,
		},
	}
