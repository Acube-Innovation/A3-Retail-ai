# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""WhatsApp Delivery Report — scope 12.5 report #41."""

import frappe

from a3_retail.reporting import col, run_query

COLUMNS = [
	col("Stream", "stream", "Data", 130),
	col("Template", "template", "Link", 190, "WhatsApp Template"),
	col("Sent", "sent", "Int", 90),
	col("Delivered", "delivered", "Int", 100),
	col("Read", "read_count", "Int", 90),
	col("Failed", "failed", "Int", 90),
	col("Blocked", "blocked", "Int", 90),
	col("Delivery %", "delivery_rate", "Percent", 110),
]

SQL = """
select l.stream, l.template, count(*) as sent,
		       sum(case when l.status in ('Delivered', 'Read') then 1 else 0 end) as delivered,
		       sum(case when l.status = 'Read' then 1 else 0 end) as read_count,
		       sum(case when l.status = 'Failed' then 1 else 0 end) as failed,
		       sum(case when l.status like 'Blocked%%' or l.status like 'Held%%' then 1 else 0 end)
		           as blocked
		from `tabWhatsApp Message Log` l
		where 1 = 1 {conditions}
		group by l.stream, l.template
		order by sent desc
"""


def execute(filters=None):
	from a3_retail.reporting import percent

	columns, data = run_query(COLUMNS, SQL, filters, alias="l", date_field="l.creation")
	for row in data:
		row["delivery_rate"] = percent(row.get("delivered"), row.get("sent"))
	return columns, data
