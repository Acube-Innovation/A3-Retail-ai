# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
# For license information, please see license.txt
"""The second list of twelve the shop raised, counter by counter.

Each class below is one of them. Where the fault was in a branch screen the
test reads the script, because the branch app has no JS harness and a dead
button ships silently otherwise; where it was in the API it calls the API.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt


def _script(name: str) -> str:
	return open(frappe.get_app_path("a3_retail", "public", "js", name),
	            encoding="utf-8").read()


def _source(*parts: str) -> str:
	return open(frappe.get_app_path("a3_retail", *parts), encoding="utf-8").read()


class TestThePinCodeDirectory(FrappeTestCase):
	"""1 · The address writes itself from six digits — or it did not.

	The lookup was never broken. The shop's server could not reach India Post,
	and the till had no second way to ask.
	"""

	def test_the_till_can_ask_the_directory_itself(self):
		body = _script("a3_branch.js")
		self.assertIn("async function pincode(", body)
		self.assertIn("api.postalpincode.in/pincode/", body)
		# The site first, so a counter typing the same PIN all day reaches
		# India Post once rather than once a till.
		asking = body[body.index("async function pincode("):]
		asking = asking[:asking.index("\n\treturn {")]
		self.assertLess(asking.index("customer.pincode_info"), asking.index("fetch("))

	def test_the_helper_is_handed_to_the_screens(self):
		self.assertIn("printUrl, printParts, pincode,", _script("a3_branch.js"))

	def test_the_till_uses_it_rather_than_the_server_alone(self):
		pos = _script("a3_pos.js")
		self.assertIn("await A3.pincode(code)", pos)
		self.assertNotIn('A3.call("a3_retail.api.customer.pincode_info"', pos)

	def test_both_routes_answer_in_the_same_shape(self):
		"""The screen reads four fields and must not care which route filled
		them, so the browser's parser mirrors `customer._parse_pincode`."""
		body = _script("a3_branch.js")
		mirror = body[body.index("function parsePincode("):body.index("async function pincode(")]
		for field in ("pincode", "found", "state", "city", "offices", "office"):
			self.assertIn(f"{field}:", mirror, f"{field} is missing from the browser's reply")
		# India Post calls it District; on a bill it is the city line.
		self.assertIn("first.District", mirror)
		self.assertIn("first.State", mirror)


class TestSplittingAPayment(FrappeTestCase):
	"""2 · A second payment line takes its money off the first."""

	def test_a_line_takes_the_difference_off_the_one_above(self):
		body = _script("a3_pos.js")
		self.assertIn("function rebalanceSplit(", body)
		share = body[body.index("function rebalanceSplit("):]
		share = share[:share.index("\n\t}")]
		# Upwards first — the counter split the line above by adding this one.
		self.assertIn("for (let i = changedIndex - 1; i >= 0; i -= 1)", share)
		# Typing on the very first line instead: the one under it gives way.
		self.assertIn("for (let i = changedIndex + 1;", share)

	def test_a_financed_line_still_absorbs_it_first(self):
		"""What the customer puts down is money the financier need not lend."""
		body = _script("a3_pos.js")
		share = body[body.index("function rebalanceSplit("):]
		share = share[:share.index("\n\t}")]
		self.assertIn("rebalanceAgainstEmi(changedIndex)", share)

	def test_typing_an_amount_rebalances(self):
		self.assertIn("rebalanceSplit(index);", _script("a3_pos.js"))


class TestWhoSoldIt(FrappeTestCase):
	"""3 · A held bill keeps the person who served the customer."""

	def test_a_reopened_draft_is_handed_its_seller(self):
		body = _source("api", "pos.py")
		opening = body[body.index("def load_invoice("):]
		opening = opening[:opening.index("\n@frappe.whitelist")]
		self.assertIn('"sold_by": sold_by,', opening)
		# As the Employee the counter's picker is keyed on, not the Sales
		# Person the invoice stores — the two are different records.
		self.assertIn('"Sales Person", team[0].sales_person, "employee"', opening)

	def test_the_till_puts_it_back_on_the_picker(self):
		body = _script("a3_pos.js")
		self.assertIn("function setSoldBy(", body)
		self.assertIn("setSoldBy(bill.sold_by);", body)

	def test_setting_it_does_not_change_what_the_till_remembers(self):
		"""Only the picker's own `change` writes the remembered seller, and
		setting `value` from code does not fire it."""
		body = _script("a3_pos.js")
		setter = body[body.index("function setSoldBy("):]
		setter = setter[:setter.index("\n\t}")]
		self.assertNotIn("localStorage", setter)

	def test_a_real_draft_resolves_to_an_employee(self):
		draft = frappe.db.sql("""
			select si.name from `tabSales Invoice` si
			where si.docstatus = 0 and exists (
			  select 1 from `tabSales Team` t where t.parent = si.name)
			limit 1""")
		if not draft:
			self.skipTest("no draft with a seller on this site")
		doc = frappe.get_doc("Sales Invoice", draft[0][0])
		employee = frappe.db.get_value(
			"Sales Person", doc.sales_team[0].sales_person, "employee")
		self.assertTrue(employee, "the Sales Person on this bill has no Employee behind it")
		self.assertTrue(frappe.db.exists("Employee", employee))


class TestPrintingACreditNote(FrappeTestCase):
	"""4 · 9 · The shop's own sheet, at the printer, without a tab to close."""

	def test_the_shop_s_own_format_is_named_for_a_sales_invoice(self):
		"""Without this a credit note fell through to ERPNext's own sheet."""
		self.assertIn('"Sales Invoice": "Retail Tax Invoice",',
		              _source("api", "stock_control.py"))

	def test_neither_route_opens_a_tab(self):
		body = _script("a3_returns.js")
		self.assertNotIn('window.open(result.print_url', body)
		# The call, not the word — the comment above it explains why that
		# endpoint is no longer the way to a credit note.
		self.assertNotIn('A3.call("a3_retail.api.stock_control.print_url"', body)
		self.assertIn("A3.printDoc(result.print_url);", body)
		self.assertIn('format: "Retail Tax Invoice"', body)

	def test_the_list_still_offers_a_view(self):
		"""Nothing opens by itself, so the way back to the note has to be on
		its own row."""
		self.assertIn('title="View"', _script("a3_returns.js"))


class TestTheItemThatLookedLikeTwo(FrappeTestCase):
	"""5 · One record, whose name already ends in its own code."""

	def test_the_screen_strips_a_repeated_code(self):
		body = _script("a3_pos.js")
		self.assertIn("function displayName(", body)
		self.assertIn("displayName(item)", body)
		self.assertIn("displayName(line)", body)

	def test_the_item_behind_the_report_is_a_single_record(self):
		rows = frappe.get_all("Item", filters={"item_code": "T150"}, fields=["item_name"])
		if not rows:
			self.skipTest("T150 is not on this site")
		self.assertEqual(len(rows), 1, "there really are two records")
		# The name carries the code, which is what read as a duplicate.
		self.assertTrue(rows[0].item_name.strip().upper().endswith("T150"))


class TestAddingACustomerTwice(FrappeTestCase):
	"""8 · A number already on file belongs to somebody."""

	def test_the_endpoint_is_told_which_it_is_doing(self):
		body = _source("api", "pos.py")
		saving = body[body.index("def save_customer("):]
		saving = saving[:saving.index("\n@frappe.whitelist")]
		self.assertIn('mode: str = "edit"', saving)
		self.assertIn('== "create"', saving)
		self.assertIn("Customer already exists", saving)

	def test_the_add_form_says_it_is_creating(self):
		"""Edit and Add reach the same endpoint; only Add must be refused."""
		body = _script("a3_pos.js")
		adding = body[body.index("async function saveNewCustomer("):]
		adding = adding[:adding.index("\n\t}")]
		self.assertIn('mode: "create"', adding)

	def test_the_edit_form_does_not(self):
		"""A name corrected on a customer already on file has to land."""
		pos = _script("a3_pos.js")
		editing = pos[pos.index("async function saveCustomer("):]
		editing = editing[:editing.index("\n\t}")]
		self.assertNotIn('mode: "create"', editing)
		desk = _script("a3_customers.js")
		desk_edit = desk[desk.index("async function saveCustomer("):]
		desk_edit = desk_edit[:desk_edit.index("\n\t}")]
		self.assertNotIn('mode: "create"', desk_edit)

	def test_a_number_on_file_is_found(self):
		row = frappe.db.sql("""select name, customer_name, a3_mobile_no from `tabCustomer`
		                       where ifnull(a3_mobile_no,'') <> '' limit 1""", as_dict=True)
		if not row:
			self.skipTest("no customer carries a mobile number on this site")
		from a3_retail.api.customer import validate_mobile

		found = frappe.db.get_value(
			"Customer", {"a3_mobile_no": validate_mobile(row[0].a3_mobile_no)}, "name")
		self.assertEqual(found, row[0].name)


class TestSchemeDebitNotes(FrappeTestCase):
	"""11 · A scheme is an offer's name, not a box on a shelf."""

	def test_the_recent_list_keys_on_the_branch(self):
		body = _source("api", "supplier_returns.py")
		listing = body[body.index("def recent("):]
		listing = listing[:listing.index("\n@frappe.whitelist")]
		self.assertIn("pi.branch = %(branch)s", listing)
		# And no longer refuses outright when the branch keeps no store, which
		# is what hid every scheme note at a counter without a warehouse.
		self.assertNotIn('return {"branch": employee.branch, "rows": []}', listing)

	def test_a_scheme_note_is_still_warehouseless(self):
		"""The fix must not have been to give schemes a warehouse."""
		body = _source("api", "supplier_returns.py")
		self.assertIn("if not scheme:\n\t\tdoc.set_warehouse = warehouse", body)
		self.assertIn("if not scheme:\n\t\t\tline.warehouse = warehouse", body)

	def test_the_branch_is_stamped_on_the_note(self):
		body = _source("api", "supplier_returns.py")
		self.assertIn('if doc.meta.has_field("branch"):\n\t\tdoc.branch = employee.branch', body)
		self.assertTrue(frappe.get_meta("Purchase Invoice").has_field("branch"))


class TestWhoInsuredIt(FrappeTestCase):
	"""12 · The insurer belongs on the bill's own history."""

	def test_the_timeline_carries_the_insurer(self):
		body = _source("api", "bills.py")
		line = body[body.index("def _timeline("):]
		line = line[:line.index("\n\n\n")]
		self.assertIn('doc.get("a3_insured_by")', line)
		self.assertIn('_("Insured by")', line)
		self.assertIn('"note": insurer', line)

	def test_the_field_it_reads_exists(self):
		self.assertTrue(frappe.get_meta("Sales Invoice").has_field("a3_insured_by"))


class TestTheBookingBarcode(FrappeTestCase):
	"""6 · The sticker, from the booking as well as the job card."""

	def test_the_button_is_on_both_ends_of_the_page(self):
		body = _script("a3_booking.js")
		for button in ("print-top-label", "print-bottom-label"):
			self.assertIn(f'id="{button}"', body)
			self.assertIn(f'$("{button}").addEventListener("click", printBarcode)', body)

	def test_it_prints_the_sticker_the_job_card_already_uses(self):
		"""A booking is a Service Job Card underneath, so it is the same roll
		and nothing new is set up on the printer."""
		body = _script("a3_booking.js")
		self.assertIn('return printAs("Job Card Label")', body)
		self.assertTrue(frappe.db.exists("Print Format", "Job Card Label"))

	def test_the_three_buttons_share_one_route_to_the_printer(self):
		"""Print, Thermal and Print Barcode differ only by the format they
		name, so they go through one function rather than three copies."""
		body = _script("a3_booking.js")
		self.assertIn("async function printAs(format)", body)

		sheet = body[body.index("async function print(thermal)"):]
		sheet = sheet[:sheet.index("\n\t}")]
		self.assertIn("printAs(", sheet)
		self.assertNotIn("A3.printDoc(", sheet)

		label = body[body.index("async function printBarcode()"):]
		label = label[:label.index("\n\t}")]
		self.assertIn('printAs("Job Card Label")', label)
		self.assertNotIn("A3.printDoc(", label)

		route = body[body.index("async function printAs(format)"):]
		route = route[:route.index("\n\t}")]
		self.assertIn("A3.printDoc(", route)


class TestTheRepairBill(FrappeTestCase):
	"""7 · A repair billed on the shop's service sheet, with the device on it."""

	def test_a_booking_s_invoice_names_the_service_format(self):
		body = _source("api", "bookings.py")
		self.assertIn('print_format="Service Invoice"', body)

	def test_the_sheet_reads_the_field_a_sales_invoice_actually_has(self):
		"""It looked for `a3_job_card`, which a Sales Invoice does not carry,
		so `is_service` was always false: no job card was ever named and every
		repair printed the manufacturer warranty instead of the shop's own."""
		body = _source("templates", "print_formats", "service_tax_invoice.html")
		self.assertIn('doc.get("a3_service_job_card")', body)
		self.assertNotIn('set is_service = doc.get("a3_job_card")', body)
		self.assertTrue(frappe.get_meta("Sales Invoice").has_field("a3_service_job_card"))

	def test_the_device_block_carries_the_paper_form_s_fields(self):
		body = _source("templates", "print_formats", "service_tax_invoice.html")
		self.assertIn("a3_job_card_intake(doc)", body)
		for label in ("Make &amp; model", "IMEI / Serial", "Symptom", "Condition",
		              "Received with", "Lock code", "Advance paid", "Booked in"):
			self.assertIn(label, body, f"the sheet no longer prints {label}")

	def test_the_block_is_absent_on_an_ordinary_sale(self):
		from a3_retail.print_helpers import a3_job_card_intake

		sale = frappe.db.sql("""select name from `tabSales Invoice`
		                        where ifnull(a3_service_job_card,'') = '' limit 1""")
		if not sale:
			self.skipTest("every invoice on this site is a repair")
		self.assertEqual(a3_job_card_intake(frappe.get_doc("Sales Invoice", sale[0][0])), {})

	def test_a_real_repair_fills_it(self):
		from a3_retail.print_helpers import a3_job_card_intake

		repair = frappe.db.sql("""select name from `tabSales Invoice`
		                          where ifnull(a3_service_job_card,'') <> ''
		                          order by creation desc limit 1""")
		if not repair:
			self.skipTest("no repair bill on this site")
		intake = a3_job_card_intake(frappe.get_doc("Sales Invoice", repair[0][0]))
		self.assertTrue(intake, "the repair bill found no job card behind it")
		self.assertTrue(intake.get("job_card"))
		self.assertIn("device", intake)


class TestTheEmiSalesReport(FrappeTestCase):
	"""10 · The register of what went out on finance."""

	def test_the_whole_card_opens_it_not_just_the_words_see_all(self):
		body = _script("a3_emi.js")
		self.assertIn('data-go-tab="${action}" role="button" tabindex="0"', body)
		self.assertIn("is-clickable", body)

	def test_a_heading_that_takes_focus_answers_the_keyboard(self):
		body = _script("a3_emi.js")
		self.assertIn('.panel-head[data-go-tab]', body)
		self.assertIn('event.key !== "Enter" && event.key !== " "', body)

	def test_the_report_filters_by_date_and_financier(self):
		body = _script("a3_emi.js")
		row = body[body.index("sales: ["):]
		row = row[:row.index("]")]
		for wanted in ("from-date", "to-date", "partner"):
			self.assertIn(wanted, row, f"the EMI Sales tab no longer offers {wanted}")

	def test_a_row_is_one_bill_not_one_application(self):
		"""The counter does not raise an EMI Application. It picks EMI and a
		financier at the till, and the bill carries the partner while the money
		arrives as `EMI - <financier>`. Reading applications showed nothing."""
		body = _source("api", "emi.py")
		sales = body[body.index("def _sales(data"):]
		sales = sales[:sales.index("\n\n\n")]
		self.assertIn("from `tabSales Invoice` si", sales)
		self.assertIn("a3_finance_partner", sales)
		# The application is joined where there is one, not required.
		self.assertIn("left join `tabEMI Application` e", sales)
		for column in ("sales_invoice", "customer_name", "finance_partner",
		               "loan_amount", "down_payment"):
			self.assertIn(column, sales, f"{column} is no longer on the report")

	def test_the_financier_s_share_comes_off_the_payments(self):
		body = _source("api", "emi.py")
		sales = body[body.index("def _sales(data"):]
		sales = sales[:sales.index("\n\n\n")]
		self.assertIn("pe.mode_of_payment like 'EMI%%'", sales)

	def test_the_report_answers_for_the_bills_on_this_site(self):
		from a3_retail.api.emi import _sales

		billed = frappe.db.sql("""select si.branch, count(*) n from `tabSales Invoice` si
		                          where si.docstatus = 1
		                            and ifnull(si.a3_finance_partner,'') <> ''
		                          group by si.branch order by n desc limit 1""", as_dict=True)
		if not billed:
			self.skipTest("no EMI bill on this site")

		# The register answers for whoever is at the till, so the test stands
		# at one — Administrator has no employee behind it.
		till = frappe.db.get_value(
			"Employee", {"branch": billed[0].branch, "status": "Active",
			             "user_id": ["is", "set"]}, "user_id")
		if not till:
			self.skipTest(f"no till user at {billed[0].branch}")

		was = frappe.session.user
		try:
			frappe.set_user(till)
			out = _sales({}, 1, 5)
		finally:
			frappe.set_user(was)
		self.assertGreater(out["total"], 0,
		                   "the register is empty while EMI bills are on file")
		row = out["rows"][0]
		self.assertTrue(row["sales_invoice"])
		self.assertTrue(row["finance_partner"])
		# Gross is the bill; financed plus what the customer put down is it.
		self.assertAlmostEqual(
			flt(row["loan_amount"]) + flt(row["down_payment"]),
			flt(row["invoice_total"]), places=2)

	def test_the_clickable_heading_is_styled_as_one(self):
		css = open(frappe.get_app_path("a3_retail", "public", "css", "a3_branch.css"),
		           encoding="utf-8").read()
		self.assertIn(".panel-head.is-clickable { cursor: pointer; }", css)
