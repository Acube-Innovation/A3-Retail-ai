# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Incentive schemes, the calculation engine and payroll posting (scope step 23, 10.2)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from a3_retail.tests.fixtures import ensure_branch, ensure_company

PERIOD = ("2026-07-01", "2026-07-31")


def make_scheme(**overrides):
	"""A throwaway scheme with a single 100% slab unless overridden."""
	doc = frappe.new_doc("Employee Incentive Scheme")
	doc.scheme_name = overrides.pop("scheme_name", f"Test Scheme {frappe.generate_hash(length=6)}")
	doc.applicable_to = overrides.pop("applicable_to", "Custom (Employee List)")
	doc.frequency = "Monthly"
	doc.is_active = 1
	doc.metric = overrides.pop("metric", "Jobs Completed")
	doc.target_type = overrides.pop("target_type", "Absolute Target")
	doc.monthly_target = overrides.pop("monthly_target", 60)
	doc.slab_basis = overrides.pop("slab_basis", "Metric Value")

	slabs = overrides.pop("slabs", [(0, 39, "Per Unit", 0), (40, 59, "Per Unit", 60),
	                                (60, 9999, "Per Unit", 90)])
	for from_percent, to_percent, kind, value in slabs:
		doc.append("slabs", {"from_percent": from_percent, "to_percent": to_percent,
		                     "incentive_type": kind, "value": value})

	for employee in overrides.pop("employees", []):
		doc.append("employees", employee)

	doc.update(overrides)
	doc.flags.ignore_permissions = True
	return doc


def make_run(scheme, **overrides):
	doc = frappe.new_doc("Incentive Calculation Run")
	doc.scheme = scheme
	doc.from_date, doc.to_date = PERIOD
	doc.company = ensure_company()
	doc.update(overrides)
	doc.flags.ignore_permissions = True
	return doc


def technician(name="Vishnu P"):
	return frappe.db.get_value("Employee", {"employee_name": name}, "name")


class TestSchemeMasters(FrappeTestCase):
	def test_six_schemes_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Employee Incentive Scheme"), 6)

	def test_sales_scheme_slabs(self):
		scheme = frappe.get_doc("Employee Incentive Scheme", "Sales Executive Monthly")
		self.assertEqual(len(scheme.slabs), 5)
		self.assertEqual(flt(scheme.slabs[3].value), 0.90)
		self.assertEqual(flt(scheme.cap_amount), 25000)

	def test_technician_scheme_bands_units_not_percentages(self):
		scheme = frappe.get_doc("Employee Incentive Scheme", "Technician Monthly")
		self.assertEqual(scheme.slab_basis, "Metric Value")
		self.assertTrue(scheme.quality_gate)

	def test_each_scheme_has_a_payout_component(self):
		for name in frappe.get_all("Employee Incentive Scheme", pluck="name"):
			self.assertTrue(
				frappe.db.get_value("Employee Incentive Scheme", name, "payout_component"), name
			)


class TestSlabResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _run(self, **scheme_kwargs):
		scheme = make_scheme(**scheme_kwargs)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		return frappe.get_cached_doc("Employee Incentive Scheme", scheme.name), run

	def test_unit_slab_uses_the_raw_count(self):
		scheme, run = self._run()
		label, amount = run.apply_slab(scheme, achieved=55, percent=91.67, target=60)
		self.assertIn("40.0-59.0", label)
		self.assertEqual(amount, 3300)

	def test_percentage_slab_uses_achievement(self):
		scheme, run = self._run(
			slab_basis="Achievement %", metric="Net Sales Value", monthly_target=600000,
			slabs=[(0, 79.99, "% of Metric Value", 0), (120, 149.99, "% of Metric Value", 0.90)],
		)
		label, amount = run.apply_slab(scheme, achieved=742000, percent=123.67, target=600000)
		self.assertIn("120.0-149.99", label)
		self.assertEqual(amount, 6678)

	def test_no_matching_slab_pays_nothing(self):
		scheme, run = self._run()
		label, amount = run.apply_slab(scheme, achieved=-5, percent=0, target=60)
		self.assertEqual((label, amount), ("", 0.0))

	def test_fixed_amount_slab(self):
		scheme, run = self._run(slabs=[(0, 9999, "Fixed Amount", 2500)])
		_label, amount = run.apply_slab(scheme, achieved=3, percent=0, target=0)
		self.assertEqual(amount, 2500)

	def test_employee_target_overrides_the_scheme(self):
		employee = technician("Rafeeq M")
		scheme, run = self._run(
			metric="Net Sales Value", monthly_target=600000,
			employees=[{"employee": employee, "monthly_target": 400000}],
		)
		target = run.resolve_target(scheme, frappe._dict(name=employee, branch="Kozhikode"))
		self.assertEqual(target, 400000)

	def test_no_target_scheme_reports_zero(self):
		scheme, run = self._run(target_type="No Target (Slab from Zero)")
		self.assertEqual(run.resolve_target(scheme, frappe._dict(name="X", branch="Kochi")), 0)


class TestGates(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _run(self, **scheme_kwargs):
		scheme = make_scheme(**scheme_kwargs)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		return frappe.get_cached_doc("Employee Incentive Scheme", scheme.name), run

	def test_attendance_counts_a_half_day_as_half(self):
		_scheme, run = self._run()
		self.assertEqual(run.attendance_percent(technician("Manoj Kumar")), 98.0)

	def test_missing_attendance_never_fails_an_employee(self):
		_scheme, run = self._run()
		self.assertEqual(run.attendance_percent("HR-EMP-NONEXISTENT"), 100.0)

	def test_attendance_gate_blocks_the_slab(self):
		scheme, run = self._run(attendance_gate_percent=90)
		gates = run.evaluate_gates(scheme, technician("Sajeer K"), 91.67)
		self.assertFalse(gates["passed"])
		self.assertIn("Attendance", gates["reason"])

	def test_attendance_gate_passes_above_the_line(self):
		scheme, run = self._run(attendance_gate_percent=90)
		gates = run.evaluate_gates(scheme, technician("Vishnu P"), 118.33)
		self.assertTrue(gates["passed"])

	def test_qc_gate_uses_the_status_log(self):
		scheme, run = self._run(quality_gate=1, max_qc_fail_percent=1)
		gates = run.evaluate_gates(scheme, technician("Vishnu P"), 118.33)
		self.assertFalse(gates["passed"])
		self.assertIn("QC", gates["reason"])

	def test_minimum_qualification_blocks_below_the_line(self):
		scheme, run = self._run(metric="Net Sales Value", monthly_target=600000,
		                        minimum_qualification_percent=80)
		gates = run.evaluate_gates(scheme, technician("Rafeeq M"), 76.25)
		self.assertFalse(gates["passed"])
		self.assertIn("minimum", gates["reason"].lower())

	def test_csat_gate_reads_customer_feedback(self):
		_scheme, run = self._run()
		self.assertGreaterEqual(run.csat_score(technician("Vishnu P")), 4.0)

	def test_no_feedback_does_not_fail_the_csat_gate(self):
		scheme, run = self._run(csat_gate=1, min_csat=4.0)
		gates = run.evaluate_gates(scheme, technician("Jithin Raj"), 100)
		self.assertTrue(gates["passed"])


class TestCollectors(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _run(self, metric):
		scheme = make_scheme(metric=metric)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		return frappe.get_cached_doc("Employee Incentive Scheme", scheme.name), run

	def test_jobs_completed(self):
		scheme, run = self._run("Jobs Completed")
		self.assertEqual(run.collect_metric(scheme, technician("Vishnu P")), 71)

	def test_net_sales_value(self):
		scheme, run = self._run("Net Sales Value")
		self.assertEqual(run.collect_metric(scheme, technician("Vipin S")), 742000)

	def test_emi_applications_disbursed(self):
		scheme, run = self._run("EMI Applications Disbursed")
		self.assertEqual(run.collect_metric(scheme, technician("Manoj Kumar")), 18)

	def test_telecalling_conversions(self):
		scheme, run = self._run("Telecalling Conversions")
		self.assertEqual(run.collect_metric(scheme, technician("Sneha M")), 41)

	def test_ew_plans_sold(self):
		scheme, run = self._run("EW Plans Sold")
		self.assertEqual(run.collect_metric(scheme, technician("Vipin S")), 7)

	def test_an_unknown_metric_collects_nothing(self):
		scheme, run = self._run("Jobs Completed")
		scheme.metric = "Gross Profit Per Handshake"
		self.assertEqual(run.collect_metric(scheme, technician()), 0.0)

	def test_an_employee_without_a_sales_person_earns_nothing(self):
		scheme, run = self._run("Net Sales Value")
		self.assertEqual(run.collect_metric(scheme, technician("Anoop R")), 0.0)


class TestClawbackAndCap(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_returns_are_clawed_back_at_the_top_slab(self):
		scheme = make_scheme(
			metric="Net Sales Value", slab_basis="Achievement %", return_clawback=1,
			slabs=[(0, 9999, "% of Metric Value", 1.25)],
		)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)

		# The July demo return is ₹24,000 → 24,000 × 1.25% = 300.
		self.assertEqual(
			run.compute_clawback(frappe.get_cached_doc("Employee Incentive Scheme", scheme.name),
			                     technician("Vipin S")),
			300,
		)

	def test_clawback_is_off_unless_the_scheme_asks(self):
		scheme = make_scheme(metric="Net Sales Value", return_clawback=0)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		self.assertEqual(
			run.compute_clawback(frappe.get_cached_doc("Employee Incentive Scheme", scheme.name),
			                     technician("Vipin S")),
			0.0,
		)

	def test_cap_limits_the_payout(self):
		scheme = make_scheme(cap_amount=1000)
		scheme.insert(ignore_permissions=True)
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)

		row = run.compute_for(
			frappe.get_cached_doc("Employee Incentive Scheme", scheme.name),
			frappe._dict(name=technician("Vishnu P"), employee_name="Vishnu P",
			             designation="Technician L3", branch="Kochi"),
		)
		self.assertEqual(row["base_incentive"], 6390)
		self.assertEqual(row["final_incentive"], 1000)


class TestBonusRules(FrappeTestCase):
	def test_emi_fast_approval_bonus(self):
		scheme = frappe.get_cached_doc("Employee Incentive Scheme", "EMI Conversion")
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		bonus = run.compute_bonus(scheme, frappe._dict(name=technician("Manoj Kumar"),
		                                              branch="Kochi"))
		self.assertEqual(bonus, 600)

	def test_branch_attach_rate(self):
		scheme = frappe.get_cached_doc("Employee Incentive Scheme", "EW Attach Bonus")
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		self.assertGreater(run.branch_attach_rate("Kochi"), 0)

	def test_a_scheme_without_a_rule_pays_no_bonus(self):
		scheme = frappe.get_cached_doc("Employee Incentive Scheme", "Telecaller Monthly")
		run = make_run(scheme.name)
		run.insert(ignore_permissions=True)
		self.assertEqual(run.compute_bonus(scheme, frappe._dict(name=technician("Sneha M"),
		                                                       branch="Head Office")), 0.0)


class TestCalculationRun(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def test_dates_must_be_in_order(self):
		run = make_run("Technician Monthly", from_date="2026-07-31", to_date="2026-07-01")
		self.assertRaises(frappe.ValidationError, run.insert)

	def test_calculate_fills_one_row_per_eligible_employee(self):
		run = make_run("Technician Monthly")
		run.insert(ignore_permissions=True)
		count = run.calculate()

		self.assertEqual(count, len(run.employees))
		self.assertEqual(run.status, "Calculated")
		self.assertGreaterEqual(count, 3)

	def test_calculate_is_idempotent(self):
		run = make_run("Technician Monthly")
		run.insert(ignore_permissions=True)
		first = run.calculate()
		second = run.calculate()
		self.assertEqual(first, second)

	def test_branch_narrows_the_employee_list(self):
		run = make_run("Technician Monthly", branch="Thiruvananthapuram")
		run.insert(ignore_permissions=True)
		run.calculate()
		self.assertTrue(all(row.branch == "Thiruvananthapuram" for row in run.employees))

	def test_total_is_the_sum_of_the_rows(self):
		run = make_run("Technician Monthly")
		run.insert(ignore_permissions=True)
		run.calculate()
		self.assertEqual(
			flt(run.total_incentive),
			flt(sum(flt(row.final_incentive) for row in run.employees)),
		)

	def test_an_empty_run_cannot_be_submitted(self):
		run = make_run("Technician Monthly")
		run.insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, run.submit)


class TestPayrollPosting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_branch("Kochi", "KCH")
		frappe.db.commit()

	def _submitted_run(self):
		run = make_run("Technician Monthly")
		run.insert(ignore_permissions=True)
		run.calculate()
		run.reload()
		run.submit()
		run.reload()
		return run

	def test_posting_creates_one_additional_salary_per_payout(self):
		run = self._submitted_run()
		payable = [row for row in run.employees if flt(row.final_incentive) > 0]
		posted = run.post_to_payroll()

		self.assertEqual(posted, len(payable))
		run.reload()
		for row in run.employees:
			if flt(row.final_incentive) > 0:
				self.assertTrue(row.additional_salary, row.employee_name)

	def test_posting_marks_the_run(self):
		run = self._submitted_run()
		run.post_to_payroll()
		run.reload()
		self.assertEqual(run.status, "Posted to Payroll")
		self.assertTrue(run.posted_on)

	def test_posting_twice_does_not_duplicate(self):
		run = self._submitted_run()
		run.post_to_payroll()
		run.reload()
		self.assertEqual(run.post_to_payroll(), 0)

	def test_the_salary_row_carries_the_amount_and_the_link_back(self):
		run = self._submitted_run()
		run.post_to_payroll()
		run.reload()

		row = next(r for r in run.employees if flt(r.final_incentive) > 0)
		salary = frappe.get_doc("Additional Salary", row.additional_salary)
		self.assertEqual(flt(salary.amount), flt(row.final_incentive))
		self.assertEqual(salary.ref_docname, run.name)
		self.assertEqual(str(salary.payroll_date), "2026-07-31")


class TestJulyDemoTable(FrappeTestCase):
	"""Scope 10.2 acceptance: the July run reproduces the demo table."""

	# (scheme, employee): achieved, base, spiff, clawback, final
	EXPECTED = {
		("Sales Executive Monthly", "Vipin S"): (742000, 6678, 1650, 300, 8028),
		("Sales Executive Monthly", "Rafeeq M"): (305000, 0, 450, 0, 450),
		("EMI Conversion", "Manoj Kumar"): (18, 1800, 600, 0, 2400),
		("Technician Monthly", "Vishnu P"): (71, 6390, 0, 0, 6390),
		("Technician Monthly", "Sajeer K"): (55, 3300, 0, 0, 0),
		("Technician Monthly", "Rijo Thomas"): (63, 5670, 0, 0, 5670),
		("Telecaller Monthly", "Sneha M"): (41, 1640, 0, 0, 1640),
	}

	def _rows(self):
		return {
			(row.scheme, row.employee_name): row
			for row in frappe.db.sql(
				"""select r.scheme, i.employee_name, i.achieved, i.base_incentive, i.spiff_amount,
				          i.clawback_amount, i.final_incentive, i.gates_passed, i.attendance_percent
				   from `tabIncentive Calculation Item` i
				   join `tabIncentive Calculation Run` r on r.name = i.parent
				   where r.docstatus = 1 and r.from_date = '2026-07-01'""",
				as_dict=True,
			)
		}

	def test_every_demo_row_reproduces(self):
		rows = self._rows()
		for key, (achieved, base, spiff, clawback, final) in self.EXPECTED.items():
			row = rows.get(key)
			self.assertIsNotNone(row, f"{key} missing from the July runs")
			self.assertEqual(flt(row.achieved), achieved, key)
			self.assertEqual(flt(row.base_incentive), base, key)
			self.assertEqual(flt(row.spiff_amount), spiff, key)
			self.assertEqual(flt(row.clawback_amount), clawback, key)
			self.assertEqual(flt(row.final_incentive), final, key)

	def test_sajeer_fails_the_attendance_gate_with_a_zero_payout(self):
		row = self._rows()[("Technician Monthly", "Sajeer K")]
		self.assertFalse(row.gates_passed)
		self.assertLess(flt(row.attendance_percent), 90)
		self.assertEqual(flt(row.final_incentive), 0)

	def test_vipins_payout_is_slab_plus_spiff_less_clawback(self):
		row = self._rows()[("Sales Executive Monthly", "Vipin S")]
		self.assertEqual(
			flt(row.final_incentive),
			flt(row.base_incentive) + flt(row.spiff_amount) - flt(row.clawback_amount),
		)
