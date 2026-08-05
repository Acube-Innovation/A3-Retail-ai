# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""Incentive Calculation Run (scope 10.2).

"Calculate" collects each employee's metric, works out the slab, adds product
spiffs, subtracts clawbacks, then applies the gates. A failed gate zeroes the
*slab* incentive but never the spiffs — a spiff is earned per unit sold, and the
demo table shows exactly that for Rafeeq M.

"Post to Payroll" turns the result into Additional Salary rows so the money
reaches the payslip through payroll rather than an ad-hoc payment.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_last_day, getdate, now_datetime

from a3_retail.utils import money

DRAFT = "Draft"
CALCULATED = "Calculated"
APPROVED = "Approved"
POSTED = "Posted to Payroll"
CANCELLED = "Cancelled"


class IncentiveCalculationRun(Document):
	def before_validate(self):
		if not self.company:
			self.company = frappe.db.get_single_value("Global Defaults", "default_company")

	def validate(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date cannot be before From Date."))
		self.total_incentive = money(
			sum(flt(row.final_incentive) for row in self.get("employees") or [])
		)

	def before_update_after_submit(self):
		self.total_incentive = money(
			sum(flt(row.final_incentive) for row in self.get("employees") or [])
		)

	def before_submit(self):
		if not self.get("employees"):
			frappe.throw(_("Calculate the run before submitting."))
		if self.status == DRAFT:
			self.status = CALCULATED

	def on_cancel(self):
		self.status = CANCELLED

	# ------------------------------------------------------------------ calculate
	@frappe.whitelist()
	def calculate(self) -> int:
		"""Rebuild every employee row from live data."""
		self.check_permission("write")
		scheme = frappe.get_cached_doc("Employee Incentive Scheme", self.scheme)
		employees = self.eligible_employees(scheme)

		self.set("employees", [])
		for employee in employees:
			row = self.compute_for(scheme, employee)
			if row:
				self.append("employees", row)

		self.status = CALCULATED
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)
		return len(self.get("employees") or [])

	def eligible_employees(self, scheme) -> list[dict]:
		"""Who the scheme applies to, narrowed by the run's branch."""
		filters = {"status": "Active"}
		if self.branch:
			filters["branch"] = self.branch

		if scheme.applicable_to == "Custom (Employee List)":
			names = [row.employee for row in scheme.get("employees") or []]
			if not names:
				return []
			filters["name"] = ["in", names]
		else:
			designations = [row.designation for row in scheme.get("designations") or []]
			if designations:
				filters["designation"] = ["in", designations]
			else:
				# Fall back to the scheme's headline role, matched loosely so
				# "Technician L2" is covered by a Technician scheme.
				filters["designation"] = ["like", f"%{scheme.applicable_to.split(' (')[0]}%"]

		branches = [row.branch for row in scheme.get("branches") or [] if row.is_included]
		if branches and not self.branch:
			filters["branch"] = ["in", branches]

		return frappe.get_all(
			"Employee", filters=filters, fields=["name", "employee_name", "designation", "branch"]
		)

	def compute_for(self, scheme, employee) -> dict | None:
		achieved = self.collect_metric(scheme, employee.name)
		target = self.resolve_target(scheme, employee)
		percent = round(flt(achieved) / flt(target) * 100, 2) if flt(target) else 0.0

		slab, base = self.apply_slab(scheme, achieved, percent, target)
		spiff = self.compute_spiff(scheme, employee.name) + self.compute_bonus(scheme, employee)
		clawback = self.compute_clawback(scheme, employee.name)

		gates = self.evaluate_gates(scheme, employee.name, percent)

		final = base if gates["passed"] else 0.0
		final = max(final + spiff - clawback, 0.0)
		if flt(scheme.cap_amount):
			final = min(final, flt(scheme.cap_amount))

		return {
			"employee": employee.name,
			"employee_name": employee.employee_name,
			"designation": employee.designation,
			"branch": employee.branch,
			"target": flt(target),
			"achieved": flt(achieved),
			"achievement_percent": percent,
			"slab_applied": slab,
			"base_incentive": money(base),
			"spiff_amount": money(spiff),
			"clawback_amount": money(clawback),
			"attendance_percent": gates["attendance"],
			"qc_fail_percent": gates["qc_fail"],
			"csat_score": gates["csat"],
			"gates_passed": 1 if gates["passed"] else 0,
			"gate_failure_reason": gates["reason"],
			"final_incentive": money(final),
		}

	# -------------------------------------------------------------- collectors
	def collect_metric(self, scheme, employee: str) -> float:
		"""One collector per metric in the scope 10.2 list."""
		collectors = {
			"Net Sales Value": self._net_sales,
			"Units Sold": self._units_sold,
			"Gross Profit": self._gross_profit,
			"Jobs Completed": self._jobs_completed,
			"EW Plans Sold": self._ew_plans,
			"EMI Applications Disbursed": self._emi_disbursed,
			"Service Revenue": self._service_revenue,
			"Accessory Attach Value": self._accessory_value,
			"Footfall Conversion %": self._footfall_conversion,
			"Telecalling Conversions": self._telecalling_conversions,
			"Collections": self._collections,
		}
		collector = collectors.get(scheme.metric)
		return flt(collector(employee)) if collector else 0.0

	def _sales_person(self, employee: str) -> str | None:
		return frappe.db.get_value("Sales Person", {"employee": employee}, "name")

	def _net_sales(self, employee: str) -> float:
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum(si.base_net_total * st.allocated_percentage / 100)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				where st.sales_person = %(person)s and si.docstatus = 1
				  and si.is_return = 0 and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _units_sold(self, employee: str) -> float:
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum(sii.qty)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				join `tabSales Invoice Item` sii on sii.parent = si.name
				where st.sales_person = %(person)s and si.docstatus = 1 and si.is_return = 0
				  and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _jobs_completed(self, employee: str) -> float:
		return flt(
			frappe.db.count(
				"Service Job Card",
				{
					"assigned_technician": employee,
					"docstatus": 1,
					"status": ["in", ["Delivered", "Closed"]],
					"delivered_on": ["between", [self.from_date, self.to_date]],
				},
			)
		)

	def _ew_plans(self, employee: str) -> float:
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum(sii.qty)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				join `tabSales Invoice Item` sii on sii.parent = si.name
				join `tabItem` i on i.name = sii.item_code
				where st.sales_person = %(person)s and si.docstatus = 1
				  and i.a3_is_ew_plan = 1
				  and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _emi_disbursed(self, employee: str) -> float:
		return flt(
			frappe.db.count(
				"EMI Application",
				{
					"coordinator": employee,
					"docstatus": 1,
					"status": ["in", ["Disbursed", "Settled"]],
					"application_date": ["between", [self.from_date, self.to_date]],
				},
			)
		)

	def _service_revenue(self, employee: str) -> float:
		return flt(
			frappe.db.sql(
				"""
				select sum(grand_total) from `tabService Job Card`
				where assigned_technician = %(employee)s and docstatus = 1
				  and status in ('Delivered', 'Closed')
				  and delivered_on between %(from_date)s and %(to_date)s
				""",
				{"employee": employee, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _gross_profit(self, employee: str) -> float:
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum((sii.base_net_amount - ifnull(sii.incoming_rate, 0) * sii.stock_qty)
				           * st.allocated_percentage / 100)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				join `tabSales Invoice Item` sii on sii.parent = si.name
				where st.sales_person = %(person)s and si.docstatus = 1 and si.is_return = 0
				  and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _accessory_value(self, employee: str) -> float:
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum(sii.base_net_amount * st.allocated_percentage / 100)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				join `tabSales Invoice Item` sii on sii.parent = si.name
				join `tabItem` i on i.name = sii.item_code
				where st.sales_person = %(person)s and si.docstatus = 1 and si.is_return = 0
				  and ifnull(i.a3_is_device, 0) = 0 and ifnull(i.a3_is_service_item, 0) = 0
				  and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	def _footfall_conversion(self, employee: str) -> float:
		visits = frappe.db.count(
			"Branch Visit Log",
			{"attended_by": employee, "visit_datetime": ["between", [self.from_date, self.to_date]]},
		)
		if not visits:
			return 0.0
		converted = frappe.db.count(
			"Branch Visit Log",
			{
				"attended_by": employee,
				"outcome": ["like", "Converted%"],
				"visit_datetime": ["between", [self.from_date, self.to_date]],
			},
		)
		return round(converted / visits * 100, 2)

	def _telecalling_conversions(self, employee: str) -> float:
		"""Scheme 5 pays per conversion; the spec's metric list omits it (see BUILD_STATUS)."""
		if not frappe.db.exists("DocType", "Call Task"):
			return 0.0
		return flt(
			frappe.db.count(
				"Call Task",
				{
					"assigned_to": employee,
					"outcome": "Converted",
					"call_datetime": ["between", [self.from_date, f"{self.to_date} 23:59:59"]],
				},
			)
		)

	def _collections(self, employee: str) -> float:
		"""Payments collected against invoices the employee sold."""
		person = self._sales_person(employee)
		if not person:
			return 0.0
		return flt(
			frappe.db.sql(
				"""
				select sum(per.allocated_amount * st.allocated_percentage / 100)
				from `tabPayment Entry Reference` per
				join `tabPayment Entry` pe on pe.name = per.parent
				join `tabSales Team` st on st.parent = per.reference_name
				where per.reference_doctype = 'Sales Invoice' and pe.docstatus = 1
				  and st.sales_person = %(person)s
				  and pe.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

	# ------------------------------------------------------------------- slabs
	def resolve_target(self, scheme, employee) -> float:
		if scheme.target_type == "No Target (Slab from Zero)":
			return 0.0

		# A per-employee override wins: branches carry very different footfall, and
		# the July demo run gives Vipin 6,00,000 against Rafeeq's 4,00,000.
		for row in scheme.get("employees") or []:
			if row.employee == employee.name and flt(row.get("monthly_target")):
				return flt(row.monthly_target)

		if scheme.target_type == "% of Branch Target" and employee.branch:
			branch_target = flt(
				frappe.db.get_value("Branch Profile", {"branch": employee.branch}, "monthly_sales_target")
			)
			return branch_target * flt(scheme.monthly_target or 0) / 100
		return flt(scheme.monthly_target)

	def apply_slab(self, scheme, achieved: float, percent: float, target: float):
		"""Match a slab, either on achievement % or on the raw metric.

		Unit-based schemes band the count itself — the technician scheme pays the
		40–59 rate on 55 jobs even though that is 92% of a 60-job target — so the
		basis is an explicit choice on the scheme, not inferred from the target.
		"""
		if scheme.get("slab_basis") == "Metric Value" or not flt(target):
			measure = flt(achieved)
		else:
			measure = percent

		for slab in scheme.get("slabs") or []:
			if flt(slab.from_percent) <= measure <= flt(slab.to_percent or 999999):
				label = f"{slab.from_percent}-{slab.to_percent} @{slab.value}"
				if slab.incentive_type == "% of Metric Value":
					return label, flt(achieved) * flt(slab.value) / 100
				if slab.incentive_type == "Per Unit":
					return label, flt(achieved) * flt(slab.value)
				return label, flt(slab.value)

		return "", 0.0

	def compute_spiff(self, scheme, employee: str) -> float:
		"""Per-unit bonuses on specific brands, groups or items (scope 10.2)."""
		person = self._sales_person(employee)
		if not person or not scheme.get("product_spiffs"):
			return 0.0

		total = 0.0
		for spiff in scheme.product_spiffs:
			conditions = ["st.sales_person = %(person)s", "si.docstatus = 1", "si.is_return = 0",
			              "si.posting_date between %(from_date)s and %(to_date)s"]
			values = {"person": person, "from_date": self.from_date, "to_date": self.to_date}

			if spiff.item_code:
				conditions.append("sii.item_code = %(item_code)s")
				values["item_code"] = spiff.item_code
			if spiff.item_group:
				conditions.append("i.item_group = %(item_group)s")
				values["item_group"] = spiff.item_group
			if spiff.brand:
				conditions.append("i.brand = %(brand)s")
				values["brand"] = spiff.brand
			if flt(spiff.min_value):
				conditions.append("sii.rate >= %(min_value)s")
				values["min_value"] = flt(spiff.min_value)

			qty = flt(
				frappe.db.sql(
					f"""
					select sum(sii.qty)
					from `tabSales Team` st
					join `tabSales Invoice` si on si.name = st.parent
					join `tabSales Invoice Item` sii on sii.parent = si.name
					join `tabItem` i on i.name = sii.item_code
					where {" and ".join(conditions)}
					""",
					values,
				)[0][0]
			)
			total += qty * flt(spiff.spiff_per_unit)

		return total

	def compute_bonus(self, scheme, employee) -> float:
		"""Scope schemes 3 and 4 pay on a condition, not on a product line."""
		rule = scheme.get("bonus_rule")
		value = flt(scheme.get("bonus_value"))
		if not rule or not value:
			return 0.0

		if rule == "EMI Approved Within 24 Hours":
			# EMI Application dates the approval, not the minute of it — a same-day
			# or next-morning approval is what the scheme means by "within 24 hours".
			quick = frappe.db.sql(
				"""
				select count(*) from `tabEMI Application`
				where coordinator = %(employee)s and docstatus = 1
				  and status in ('Disbursed', 'Settled') and approval_date is not null
				  and datediff(approval_date, application_date) <= 1
				  and application_date between %(from_date)s and %(to_date)s
				""",
				{"employee": employee.name, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
			return flt(quick) * value

		if rule == "Branch EW Attach Rate":
			if self.branch_attach_rate(employee.branch) >= flt(scheme.bonus_threshold_percent):
				return value
			return 0.0

		if rule == "Repairs Within TAT":
			within = frappe.db.count(
				"Service Job Card",
				{
					"assigned_technician": employee.name,
					"docstatus": 1,
					"tat_status": "Within TAT",
					"delivered_on": ["between", [self.from_date, f"{self.to_date} 23:59:59"]],
				},
			)
			return flt(within) * value

		return 0.0

	def branch_attach_rate(self, branch: str) -> float:
		"""Extended-warranty plans sold per device sold, as a percentage."""
		if not branch:
			return 0.0
		rows = frappe.db.sql(
			"""
			select
				sum(case when ifnull(i.a3_is_ew_plan, 0) = 1 then sii.qty else 0 end) as plans,
				sum(case when ifnull(i.a3_is_device, 0) = 1 then sii.qty else 0 end) as devices
			from `tabSales Invoice` si
			join `tabSales Invoice Item` sii on sii.parent = si.name
			join `tabItem` i on i.name = sii.item_code
			where si.docstatus = 1 and si.is_return = 0 and si.branch = %(branch)s
			  and si.posting_date between %(from_date)s and %(to_date)s
			""",
			{"branch": branch, "from_date": self.from_date, "to_date": self.to_date},
			as_dict=True,
		)
		row = rows[0] if rows else None
		if not row or not flt(row.devices):
			return 0.0
		return round(flt(row.plans) / flt(row.devices) * 100, 2)

	def compute_clawback(self, scheme, employee: str) -> float:
		"""Incentive on goods returned within the period is taken back."""
		if not scheme.return_clawback:
			return 0.0

		person = self._sales_person(employee)
		if not person:
			return 0.0

		returned = flt(
			frappe.db.sql(
				"""
				select sum(abs(si.base_net_total) * st.allocated_percentage / 100)
				from `tabSales Team` st
				join `tabSales Invoice` si on si.name = st.parent
				where st.sales_person = %(person)s and si.docstatus = 1 and si.is_return = 1
				  and si.posting_date between %(from_date)s and %(to_date)s
				""",
				{"person": person, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)

		top_slab = max((flt(s.value) for s in scheme.get("slabs") or []), default=0.0)
		return returned * top_slab / 100 if top_slab else 0.0

	# ------------------------------------------------------------------- gates
	def evaluate_gates(self, scheme, employee: str, percent: float) -> dict:
		attendance = self.attendance_percent(employee)
		qc_fail = self.qc_fail_percent(employee)
		csat = self.csat_score(employee)

		reason = ""
		passed = True

		if flt(scheme.minimum_qualification_percent) and flt(scheme.monthly_target):
			if percent < flt(scheme.minimum_qualification_percent):
				passed, reason = False, _("Below minimum qualification")

		if passed and flt(scheme.attendance_gate_percent):
			if attendance < flt(scheme.attendance_gate_percent):
				passed, reason = False, _("Attendance {0}% below gate").format(attendance)

		if passed and scheme.quality_gate and qc_fail > flt(scheme.max_qc_fail_percent):
			passed, reason = False, _("QC failures {0}% above limit").format(qc_fail)

		if passed and scheme.csat_gate and csat and csat < flt(scheme.min_csat):
			passed, reason = False, _("CSAT {0} below minimum").format(csat)

		return {"passed": passed, "reason": reason, "attendance": attendance,
		        "qc_fail": qc_fail, "csat": csat}

	def attendance_percent(self, employee: str) -> float:
		"""Present days over marked days; a half day counts as half."""
		rows = frappe.db.sql(
			"""
			select status, count(*) as days from `tabAttendance`
			where employee = %(employee)s and docstatus = 1
			  and attendance_date between %(from_date)s and %(to_date)s
			group by status
			""",
			{"employee": employee, "from_date": self.from_date, "to_date": self.to_date},
			as_dict=True,
		)
		total = sum(row.days for row in rows)
		if not total:
			# No attendance captured yet: do not fail an employee for missing data.
			return 100.0

		by_status = {row.status: row.days for row in rows}
		present = by_status.get("Present", 0) + by_status.get("Work From Home", 0)
		present += by_status.get("Half Day", 0) * 0.5
		return round(present / total * 100, 2)

	def qc_fail_percent(self, employee: str) -> float:
		total = frappe.db.count(
			"Service Job Card",
			{"assigned_technician": employee, "docstatus": 1,
			 "received_on": ["between", [self.from_date, self.to_date]]},
		)
		if not total:
			return 0.0

		failures = flt(
			frappe.db.sql(
				"""
				select count(distinct l.parent) from `tabJob Card Status Log` l
				join `tabService Job Card` jc on jc.name = l.parent
				where l.to_status = 'QC Failed' and jc.assigned_technician = %(employee)s
				  and jc.received_on between %(from_date)s and %(to_date)s
				""",
				{"employee": employee, "from_date": self.from_date, "to_date": self.to_date},
			)[0][0]
		)
		return round(failures / total * 100, 2)

	def csat_score(self, employee: str) -> float:
		rows = frappe.get_all(
			"Customer Feedback",
			filters={"attended_employee": employee,
			         "feedback_date": ["between", [self.from_date, self.to_date]]},
			pluck="overall_rating",
		)
		if not rows:
			return 0.0

		from a3_retail.a3_retail_operations.doctype.customer_feedback.customer_feedback import _stars

		return round(sum(_stars(r) for r in rows) / len(rows), 2)

	# -------------------------------------------------------------- payroll
	@frappe.whitelist()
	def post_to_payroll(self) -> int:
		"""Create an Additional Salary per employee with a payout."""
		self.check_permission("submit")
		scheme = frappe.get_cached_doc("Employee Incentive Scheme", self.scheme)
		component = scheme.payout_component or _default_component(self.company)
		if not component:
			frappe.throw(_("Set a payout Salary Component on scheme {0}.").format(self.scheme))

		posted = 0
		for row in self.get("employees") or []:
			if flt(row.final_incentive) <= 0 or row.additional_salary:
				continue

			salary = frappe.new_doc("Additional Salary")
			salary.employee = row.employee
			salary.company = self.company
			salary.salary_component = component
			salary.amount = flt(row.final_incentive)
			salary.payroll_date = get_last_day(self.to_date)
			salary.overwrite_salary_structure_amount = 0
			salary.ref_doctype = self.doctype
			salary.ref_docname = self.name
			salary.flags.ignore_permissions = True
			try:
				salary.insert(ignore_permissions=True)
				salary.submit()
			except Exception:
				frappe.log_error(frappe.get_traceback(),
				                 f"A3 Retail: incentive payout for {row.employee}")
				continue

			row.db_set("additional_salary", salary.name, update_modified=False)
			posted += 1

		self.db_set("status", POSTED, update_modified=False)
		self.db_set("posted_on", now_datetime(), update_modified=False)
		return posted


def _default_component(company: str) -> str | None:
	configured = frappe.db.get_single_value("A3 Retail Settings", "incentive_payout_component")
	if configured and frappe.db.exists("Salary Component", configured):
		return configured

	name = "Sales Incentive"
	if frappe.db.exists("Salary Component", name):
		return name

	abbr = frappe.get_cached_value("Company", company, "abbr")
	account = f"Sales Incentive Expense - {abbr}"

	component = frappe.new_doc("Salary Component")
	component.salary_component = name
	component.salary_component_abbr = "SI"
	component.type = "Earning"
	if frappe.db.exists("Account", account):
		component.append("accounts", {"company": company, "account": account})
	component.flags.ignore_permissions = True
	try:
		component.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "A3 Retail: incentive salary component")
		return None
	return name
