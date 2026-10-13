# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# See license.txt
"""Working a repair from the branch app.

Everything between booking a device in and handing it back used to need the
desk, which the people doing the work are not meant to open. These are the
rules that keep the screen honest: it offers the steps the job card allows and
the person may take, and nothing else.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from a3_retail.a3_retail_service.doctype.service_job_card import state as st
from a3_retail.api import bookings


class TestTheStepsOffered(FrappeTestCase):
	def test_only_the_state_machine_decides_what_comes_next(self):
		"""The screen never invents a path — it reads the one that exists."""
		for status, expected in (
			(st.OPEN, (st.UNDER_DIAGNOSIS, st.CANCELLED)),
			(st.IN_PROGRESS, (st.REPAIR_COMPLETED, st.ON_HOLD, st.AWAITING_PARTS,
			                  st.NOT_REPAIRABLE)),
			(st.REPAIR_COMPLETED, (st.QC_PASSED, st.QC_FAILED)),
			(st.QC_PASSED, (st.READY_FOR_DELIVERY,)),
		):
			self.assertEqual(st.next_statuses(status), expected, status)

	def test_delivery_is_never_just_a_status_button(self):
		"""Handing a device back needs the customer's code, the accessories and
		the balance — so it is its own action, not a step on the rail."""
		self.assertIn(st.DELIVERED, bookings.NOT_A_BUTTON)
		self.assertIn(st.DELIVERED, st.next_statuses(st.READY_FOR_DELIVERY))

	def test_the_steps_that_stall_a_repair_must_say_why(self):
		"""A card that stops with no reason is the one nobody can answer the
		customer about."""
		for status in (st.ON_HOLD, st.CANCELLED, st.NOT_REPAIRABLE, st.QC_FAILED):
			self.assertIn(status, bookings.NEEDS_REASON, status)

	def test_every_step_reads_as_something_a_person_would_say(self):
		"""“QC Passed” is not how anybody on the floor says it."""
		for status in st.STATUSES:
			if status in (st.DRAFT, st.OPEN):
				continue
			self.assertIn(status, bookings.STEP_WORDS, status)
			label, hint = bookings.STEP_WORDS[status]
			self.assertTrue(label and label != status, status)
			self.assertTrue(hint, status)


class TestWhoMayTakeAStep(FrappeTestCase):
	def test_a_technician_does_not_pass_qc_on_their_own_repair(self):
		for status in (st.QC_PASSED, st.QC_FAILED, st.NOT_REPAIRABLE):
			roles = st.TRANSITION_ROLES.get(status)
			self.assertTrue(roles, status)
			self.assertNotIn("Technician", roles, status)

	def test_a_technician_can_change_a_submitted_card(self):
		"""Sixty-six fields here are allow_on_submit — the status, the diagnosis,
		the bench it is on — so the whole repair happens after submit. Frappe
		calls changing a submitted document "submit", so without it a technician
		could not move their own job card one step."""
		from a3_retail.setup.permissions import PERMISSION_MATRIX

		flags = PERMISSION_MATRIX["Service Job Card"]["Technician"]
		self.assertIn("R", flags)
		self.assertIn("U", flags)
		self.assertIn("S", flags)
		# and still cannot open one: reception books, the bench works
		self.assertNotIn("C", flags)


class TestTheBookingPageLayout(FrappeTestCase):
	def test_the_bench_spans_the_page(self):
		"""The booking page is a two-column grid — the sheet, then a 340px rail.

		The bench is a third child of that grid, so without an explicit span it
		took the sheet's column and pushed the whole sheet into the rail, where
		the sticky totals then sat on top of the content behind them.
		"""
		css = open(frappe.get_app_path(
			"a3_retail", "public", "css", "a3_branch.css")).read()
		self.assertIn(".wb { grid-column: 1 / -1;", css,
		              "the bench has to span both columns of the booking page")

	def test_a_device_does_not_say_its_brand_twice(self):
		"""Some products carry the maker's name — Apple Watch, Galaxy Tab — so
		pasting the brand in front of every model read "Apple Apple Watch SE 3"
		on the face of the booking."""
		script = open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_booking.js")).read()
		self.assertIn("function deviceTitle", script)
		self.assertIn("startsWith(brand.toLowerCase())", script)

		repeats = frappe.db.sql("""
			select name from `tabDevice Model`
			where lower(model_name) like concat(lower(brand), ' %')""", pluck=True)
		self.assertEqual(repeats, [],
		                 "these models repeat their own brand: " + ", ".join(repeats))


class TestWhatTheCounterIsMadeToDo(FrappeTestCase):
	"""Checks a shop can switch off, because not every shop works the same way."""

	def _setting(self, field, value):
		before = frappe.db.get_single_value("A3 Retail Settings", field)
		frappe.db.set_single_value("A3 Retail Settings", field, value)
		self.addCleanup(frappe.db.set_single_value, "A3 Retail Settings", field, before)

	def test_the_collection_code_can_be_switched_off(self):
		"""A counter that knows its customers by face should not be made to type
		a code it never sent. With it off, the signature on the job card is what
		the hand-over rests on."""
		import inspect

		from a3_retail.api import service

		source = inspect.getsource(service.deliver_job_card)
		self.assertIn("require_delivery_otp", source,
		              "the OTP check has to be behind the setting")
		# and the screens have to know, or they ask for something nobody wants
		from a3_retail.api import bookings, service_pos

		self.assertIn("require_delivery_otp", inspect.getsource(service_pos.bootstrap))
		self.assertIn("require_otp", inspect.getsource(bookings.steps))

	def test_the_signature_is_already_a_setting(self):
		from a3_retail.a3_retail_service.doctype.service_job_card import service_job_card

		self.assertTrue(hasattr(service_job_card, "_require_signature"))
		self._setting("require_signature", 0)
		self.assertFalse(service_job_card._require_signature())


class TestChangingWhatIsCharged(FrappeTestCase):
	"""What a device needs is found at the bench, not guessed at intake."""

	def test_the_lines_can_be_changed_while_the_job_is_open(self):
		import inspect

		from a3_retail.api import bookings

		for name in ("lines", "add_line", "update_line", "remove_line"):
			self.assertTrue(hasattr(bookings, name), f"bookings.{name} is missing")
		# every one of them has to check the job is still open
		for name in ("add_line", "update_line", "remove_line"):
			self.assertIn("_editable(doc)", inspect.getsource(getattr(bookings, name)),
			              f"{name} must refuse a billed or closed job")

	def test_a_billed_repair_stops_being_editable(self):
		"""The lines are what the customer was charged. A change after that
		belongs on a credit note, not here."""
		import inspect

		from a3_retail.api import bookings

		source = inspect.getsource(bookings._editable)
		self.assertIn("sales_invoice", source)
		self.assertIn("TERMINAL_STATUSES", source)

	def test_an_issued_part_cannot_just_be_deleted(self):
		"""It is off the shelf already — taking it off the bill without putting
		it back leaves the stock and the paperwork disagreeing."""
		import inspect

		from a3_retail.api import bookings

		source = inspect.getsource(bookings.remove_line)
		self.assertIn("Issued", source)
		self.assertIn("Consumed", source)

	def test_the_bench_can_bill_the_repair(self):
		from a3_retail.api import bookings

		self.assertTrue(hasattr(bookings, "invoice_now"))


class TestTheProblemsOnOffer(FrappeTestCase):
	def test_a_counter_has_problems_to_pick_from(self):
		"""The dropdown reads Service Issue Type, and an empty one gives the
		counter nothing to choose — the complaint then goes in free text only."""
		live = frappe.db.count("Service Issue Type", {"is_active": 1})
		self.assertGreater(live, 0, "no problems are set up for the counter to pick")

	def test_each_problem_says_what_kind_it_is(self):
		rows = frappe.get_all("Service Issue Type", filters={"is_active": 1},
		                      fields=["name", "category"])
		missing = [r.name for r in rows if not r.category]
		self.assertEqual(missing, [], "these have no category: " + ", ".join(missing))


class TestEveryStepIsAsked(FrappeTestCase):
	"""A step is rarely just a status.

	It is a technician finishing a piece of work and the parts they used on it.
	Advancing straight off the button meant the parts were remembered
	afterwards, or not at all.
	"""

	def _script(self):
		return open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_booking.js")).read()

	def test_a_step_opens_a_dialog_rather_than_moving_the_card(self):
		script = self._script()
		self.assertIn("stage-modal", script)
		self.assertIn("function confirmStage", script)
		# the move only happens on confirm, never on the step button itself
		self.assertIn("async function confirmStage", script)
		self.assertIn('"a3_retail.api.bookings.advance"', script)

	def test_the_dialog_carries_who_did_it_and_what_it_cost(self):
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "booking.html")).read()
		for field in ("stage-tech", "stage-lines", "stage-reason"):
			self.assertIn(f'id="{field}"', markup, field)

	def test_a_step_that_stalls_the_job_still_insists_on_a_reason(self):
		script = self._script()
		self.assertIn("needsReason && !remarks", script)

	def test_a_part_can_be_catalogued_from_inside_the_step(self):
		"""A bench meets a connector the shop has never bought. Sending somebody
		to the stock screen to name it and back here to add it is how the line
		ends up in the notes instead."""
		script = self._script()
		self.assertIn("function adderMarkup", script)
		self.assertIn("function wireAdder", script)
		# the same block serves the bench and the step dialog
		self.assertIn('wireAdder("wb"', script)
		self.assertIn('wireAdder("sg"', script)
		self.assertIn('"a3_retail.api.service_pos.create_line_item"', script)

	def test_what_the_bench_may_offer_is_known_before_it_paints(self):
		"""Otherwise the buttons that depend on it are drawn once, without it,
		and never drawn again."""
		script = self._script()
		self.assertIn("loadBench().then(load, load)", script)


class TestTheBookingPageFooter(FrappeTestCase):
	def test_the_action_row_is_not_buried_by_the_rail(self):
		"""Chrome holds a sticky grid item inside the grid container, not its own
		row, so a tall rail slides down over whatever follows — and a static row
		loses, because anything positioned paints on top of it.
		"""
		css = open(frappe.get_app_path(
			"a3_retail", "public", "css", "a3_branch.css")).read()
		block = css.split(".inv-actions {")[1].split("}")[0]
		self.assertIn("position: relative", block)
		self.assertIn("z-index", block)

	def test_the_rail_never_grows_taller_than_the_window(self):
		css = open(frappe.get_app_path(
			"a3_retail", "public", "css", "a3_branch.css")).read()
		block = css.split(".inv-side {")[1].split("}")[0]
		self.assertIn("max-height", block)
		self.assertIn("overflow-y", block)


class TestHandingItBack(FrappeTestCase):
	def test_no_code_is_generated_where_none_is_wanted(self):
		"""Generating it would text the customer a number nobody will ask for."""
		import inspect

		from a3_retail.a3_retail_service.doctype.service_job_card import service_job_card

		source = inspect.getsource(service_job_card.ServiceJobCard)
		self.assertIn("_require_delivery_otp()", source,
		              "the code must only be made where the shop asks for one")

	def test_who_is_collecting_is_offered_not_typed(self):
		"""The customer collects their own device far more often than anybody
		else, so their name is the first thing offered."""
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "booking.html")).read()
		self.assertIn('id="hand-who"', markup)
		script = open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_booking.js")).read()
		self.assertIn("(the customer)", script)


class TestNamingADevice(FrappeTestCase):
	"""A shop services handsets it has never sold."""

	def test_the_make_and_the_model_are_both_nameable_at_the_counter(self):
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "service.html")).read()
		self.assertIn('id="model-modal"', markup)
		for field in ("dm-make", "dm-newmake", "dm-model", "dm-type"):
			self.assertIn(f'id="{field}"', markup, field)
		script = open(frappe.get_app_path(
			"a3_retail", "public", "js", "a3_service.js")).read()
		self.assertNotIn("window.prompt", script,
		                 "a model is named in the dialog, not a browser prompt")

	def test_an_existing_make_is_matched_however_it_is_typed(self):
		"""Otherwise the catalogue fills up with Vivo, VIVO and vivo, and the
		models underneath them stop adding up."""
		import inspect

		from a3_retail.api import service_pos

		source = inspect.getsource(service_pos.create_device_model)
		self.assertIn("lower(name) = lower(", source)

	def test_a_make_is_only_created_when_it_is_asked_for(self):
		"""A typo in the make should not quietly mint a brand."""
		import inspect

		from a3_retail.api import service_pos

		source = inspect.getsource(service_pos.create_device_model)
		self.assertIn("cint(new_make)", source)
		self.assertIn('require_permission("Brand", "create")', source)

	def test_the_counter_may_name_a_make(self):
		from a3_retail.setup.permissions import PERMISSION_MATRIX

		for role in ("Service Manager", "Reception Executive"):
			self.assertIn("C", PERMISSION_MATRIX["Brand"][role],
			              f"{role} must be able to name a make it is servicing")


class TestTakingACustomerIn(FrappeTestCase):
	def test_the_counter_reads_a_customer_rather_than_retyping_one(self):
		"""Editing someone's details on the way past a repair is how two
		spellings of the same person end up on the ledger."""
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "service.html")).read()
		for field in ("customer-name", "customer-email", "customer-address",
		              "customer-city", "customer-state", "customer-pin"):
			block = markup.split(f'id="{field}"')[1].split(">")[0]
			self.assertIn("readonly", block, f"{field} must not be typed into")

	def test_a_new_customer_is_made_in_its_own_dialog(self):
		markup = open(frappe.get_app_path(
			"a3_retail", "www", "retail", "service.html")).read()
		self.assertIn('id="cust-modal"', markup)
		for field in ("nc-mobile", "nc-name", "nc-city", "nc-pin"):
			self.assertIn(f'id="{field}"', markup, field)


class TestWhoIsOnTheBench(FrappeTestCase):
	def test_the_list_is_never_silently_empty(self):
		"""A Technician Profile is the proper record, but a shop that has not
		filled them in still has technicians — and a dropdown with nothing in it
		is how a repair ends up assigned to nobody."""
		import inspect

		from a3_retail.api import service_pos

		source = inspect.getsource(service_pos.technicians)
		self.assertIn("Technician Profile", source)
		self.assertIn("tabHas Role", source, "it must fall back to the role")
		self.assertIn("a3_is_counter_terminal", source,
		              "a till is not a person who repairs things")


class TestWhoMaySeeACard(FrappeTestCase):
	def test_an_unassigned_card_is_not_hidden_from_the_bench(self):
		"""A job card carries three Employee links — who took it in, whose bench
		it is on, who handed it back. Two are blank for most of a repair's life,
		and with strict user permissions a blank link denied the whole document:
		no technician could open any job card at all, because `delivered_by` is
		empty until the moment it is delivered. Branch is what scopes this app;
		these three must not.
		"""
		meta = frappe.get_meta("Service Job Card")
		for fieldname in ("received_by", "assigned_technician", "delivered_by"):
			field = meta.get_field(fieldname)
			self.assertEqual(field.options, "Employee", fieldname)
			self.assertTrue(field.ignore_user_permissions,
			                f"{fieldname} must not gate access to the card")

	def test_no_employee_link_anywhere_can_lock_a_document(self):
		"""The same trap, across the whole app.

		Every Employee user permission turns every Employee link into a lock:
		strict mode denies the document when the link is blank or points at
		somebody else. It cost the bench its job cards, and then the counter its
		bookings — "not allowed to access this Job Card Labour record because it
		is linked to Employee HR-EMP-00022 in row 1, field Technician" — for the
		ordinary act of putting a colleague's name on a labour line.

		Branch is what scopes this app. Employee never should.
		"""
		import glob
		import json
		import os

		app = frappe.get_app_path("a3_retail")
		offenders = []
		for path in glob.glob(os.path.join(app, "a3_retail_*", "doctype", "*", "*.json")):
			stem = os.path.basename(path).replace(".json", "")
			if stem != os.path.basename(os.path.dirname(path)):
				continue
			with open(path) as handle:
				doc = json.load(handle)
			for field in doc.get("fields", []):
				if field.get("fieldtype") == "Link" \
						and field.get("options") == "Employee" \
						and not field.get("ignore_user_permissions"):
					offenders.append(f"{doc.get('name')}.{field['fieldname']}")

		self.assertEqual(
			offenders, [],
			"these Employee links will deny the whole document to anyone who is "
			"not that employee: " + ", ".join(sorted(offenders)))

	def test_branch_still_scopes_the_card(self):
		"""The fix must not open another shop's repairs."""
		meta = frappe.get_meta("Service Job Card")
		branch = meta.get_field("branch")
		self.assertEqual(branch.options, "Branch")
		self.assertFalse(branch.ignore_user_permissions,
		                 "branch is what keeps one shop out of another's repairs")
