# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Customer Feedback (scope 8.3).

A rating of three or below is a detractor: an Issue is opened automatically so
somebody owns the recovery rather than the score simply being recorded.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate

DETRACTOR_THRESHOLD = 3
PROMOTER_THRESHOLD = 5


class CustomerFeedback(Document):
	def before_validate(self):
		if not self.feedback_date:
			self.feedback_date = getdate(nowdate())

	def validate(self):
		self.pull_customer()
		self.classify()

	def on_update(self):
		self.raise_issue_for_detractor()

	def pull_customer(self):
		if self.customer and not self.mobile_no:
			self.mobile_no = frappe.db.get_value("Customer", self.customer, "a3_mobile_no")

		if not self.customer and self.reference_type and self.reference_name:
			field = "customer"
			if frappe.get_meta(self.reference_type).has_field(field):
				self.customer = frappe.db.get_value(self.reference_type, self.reference_name, field)

	def classify(self):
		"""Frappe's Rating stores 0–1, so a 5-star score arrives as 1.0."""
		stars = _stars(self.overall_rating)

		if stars and stars <= DETRACTOR_THRESHOLD:
			self.sentiment = "Detractor"
			self.requires_follow_up = 1
		elif stars >= PROMOTER_THRESHOLD:
			self.sentiment = "Promoter"
			self.requires_follow_up = 0
		else:
			self.sentiment = "Passive"
			self.requires_follow_up = 0

		if self.nps_score is None or self.nps_score == 0:
			self.nps_score = cint(stars * 2)

	def raise_issue_for_detractor(self):
		if not self.requires_follow_up or self.follow_up_issue:
			return

		issue = frappe.new_doc("Issue")
		issue.subject = _("Detractor feedback from {0}").format(self.customer or self.mobile_no)
		issue.raised_by = frappe.db.get_value("Customer", self.customer, "email_id") if self.customer else None
		issue.customer = self.customer
		issue.description = self.comments or _("Rated {0}/5").format(_stars(self.overall_rating))
		issue.status = "Open"
		if issue.meta.has_field("a3_branch"):
			issue.a3_branch = self.branch
		if issue.meta.has_field("a3_severity"):
			issue.a3_severity = "High"
		if issue.meta.has_field("a3_complaint_category"):
			issue.a3_complaint_category = "Repair Quality"
		if issue.meta.has_field("a3_channel"):
			issue.a3_channel = "WhatsApp"
		if self.reference_type == "Service Job Card" and issue.meta.has_field("a3_job_card"):
			issue.a3_job_card = self.reference_name

		issue.flags.ignore_permissions = True
		issue.flags.ignore_mandatory = True
		try:
			issue.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"A3 Retail: detractor issue for {self.name}")
			return

		self.db_set("follow_up_issue", issue.name, update_modified=False)


def _stars(rating) -> float:
	"""Rating fields are stored 0–1; return the familiar 0–5 scale."""
	value = float(rating or 0)
	return round(value * 5, 2) if value <= 1 else round(value, 2)


@frappe.whitelist()
def nps_summary(branch: str | None = None) -> dict:
	"""Promoters minus detractors, as a percentage (scope 12.7)."""
	from a3_retail.api import require_permission

	require_permission("Customer Feedback", "read")

	filters = {"branch": branch} if branch else {}
	rows = frappe.get_all("Customer Feedback", filters=filters, fields=["sentiment", "overall_rating"])
	if not rows:
		return {"responses": 0, "nps": 0, "average_rating": 0,
		        "promoters": 0, "passives": 0, "detractors": 0}

	promoters = sum(1 for r in rows if r.sentiment == "Promoter")
	detractors = sum(1 for r in rows if r.sentiment == "Detractor")
	total = len(rows)

	return {
		"responses": total,
		"promoters": promoters,
		"passives": total - promoters - detractors,
		"detractors": detractors,
		"nps": round((promoters - detractors) / total * 100, 2),
		"average_rating": round(sum(_stars(r.overall_rating) for r in rows) / total, 2),
	}
