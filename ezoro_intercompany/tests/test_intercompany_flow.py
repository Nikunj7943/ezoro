import frappe
from frappe.exceptions import ValidationError
from frappe.model.workflow import WorkflowPermissionError, WorkflowTransitionError, apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_purchase_invoice
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

from ezoro_intercompany.ezoro_intercompany.doctype.sales_value_confirmation.sales_value_confirmation import (
	get_invoice_items,
	make_sales_invoice,
)
from ezoro_intercompany.ezoro_intercompany.report.intercompany_transaction_tracker.intercompany_transaction_tracker import (
	execute as run_tracker,
)

BUYER = "ecofinit.buyer@example.com"
APPROVER = "ecofinit.approver@example.com"
METAL_GREEN_USER = "metalgreen.user@example.com"
WORKFLOW_ERRORS = (WorkflowTransitionError, WorkflowPermissionError)


def make_purchase_order(qty=100):
	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"company": "Ecofinit Dubai",
			"supplier": "Gulf Metal Recyclers",
			"transaction_date": nowdate(),
			"schedule_date": add_days(nowdate(), 14),
			"currency": "SAR",
			"buying_price_list": "Intercompany SAR",
			"set_warehouse": "Receiving - ED",
			"items": [
				{
					"item_code": "ALU-DROSS-001",
					"qty": qty,
					"uom": "MT",
					"rate": 2000,
					"warehouse": "Receiving - ED",
					"schedule_date": add_days(nowdate(), 14),
				}
			],
		}
	).insert()
	po.submit()
	return po


def receive(po, qty):
	receipt = make_purchase_receipt(po.name)
	receipt.items[0].qty = qty
	receipt.insert()
	receipt.submit()
	return receipt


def bill(receipts):
	invoice = None
	for receipt in receipts:
		invoice = make_purchase_invoice(receipt.name, target_doc=invoice)
	invoice.bill_no = f"TEST-{frappe.generate_hash(length=6)}"
	invoice.bill_date = nowdate()
	invoice.insert()
	invoice.submit()
	return invoice


def make_confirmation(purchase_invoice, sales_rate=2200):
	confirmation = frappe.new_doc("Sales Value Confirmation")
	confirmation.company = "Ecofinit Dubai"
	confirmation.customer = "Metal Green Saudi Arabia"
	confirmation.purchase_invoice = purchase_invoice
	for row in get_invoice_items(purchase_invoice):
		row["sales_rate"] = sales_rate
		confirmation.append("items", row)
	return confirmation.insert()


class TestIntercompanyFlow(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def approved_confirmation(self, receipts):
		invoice = bill(receipts)
		frappe.set_user(BUYER)
		confirmation = make_confirmation(invoice.name)
		apply_workflow(confirmation, "Submit for Approval")
		frappe.set_user(APPROVER)
		confirmation.reload()
		apply_workflow(confirmation, "Approve")
		frappe.set_user("Administrator")
		return confirmation.reload()

	def test_partial_receipts_track_ordered_received_pending(self):
		po = make_purchase_order(100)
		expected = [(30, 30), (40, 70), (30, 100)]
		for qty, received in expected:
			receive(po, qty)
			po.reload()
			self.assertEqual(po.items[0].received_qty, received)
			self.assertEqual(po.items[0].qty - po.items[0].received_qty, 100 - received)
		self.assertEqual(po.per_received, 100)
		self.assertEqual(po.status, "To Bill")

	def test_one_supplier_invoice_covers_all_receipts(self):
		po = make_purchase_order(100)
		receipts = [receive(po, qty) for qty in (30, 40, 30)]
		invoice = bill(receipts)
		self.assertEqual(invoice.grand_total, 200000)
		self.assertEqual({row.purchase_receipt for row in invoice.items}, {r.name for r in receipts})
		self.assertEqual({row.purchase_order for row in invoice.items}, {po.name})

	def test_buyer_cannot_approve_but_approver_can(self):
		po = make_purchase_order(10)
		invoice = bill([receive(po, 10)])
		frappe.set_user(BUYER)
		confirmation = make_confirmation(invoice.name)
		self.assertEqual(confirmation.workflow_state, "Draft")
		with self.assertRaises(WORKFLOW_ERRORS):
			apply_workflow(confirmation, "Approve")
		apply_workflow(confirmation, "Submit for Approval")
		confirmation.reload()
		self.assertEqual(confirmation.workflow_state, "Pending Approval")
		with self.assertRaises(WORKFLOW_ERRORS):
			apply_workflow(confirmation, "Approve")
		confirmation.reload()
		confirmation.workflow_state = "Approved"
		with self.assertRaises(WORKFLOW_ERRORS):
			confirmation.save()
		frappe.set_user(APPROVER)
		confirmation.reload()
		apply_workflow(confirmation, "Approve")
		confirmation.reload()
		self.assertEqual((confirmation.workflow_state, confirmation.docstatus), ("Approved", 1))

	def test_rejected_confirmation_cannot_be_invoiced(self):
		po = make_purchase_order(10)
		invoice = bill([receive(po, 10)])
		frappe.set_user(BUYER)
		confirmation = make_confirmation(invoice.name)
		apply_workflow(confirmation, "Submit for Approval")
		frappe.set_user(APPROVER)
		confirmation.reload()
		apply_workflow(confirmation, "Reject")
		confirmation.reload()
		self.assertEqual(confirmation.workflow_state, "Rejected")
		with self.assertRaises(ValidationError):
			make_sales_invoice(confirmation.name)

	def test_sales_invoice_is_blocked_without_approval(self):
		po = make_purchase_order(10)
		invoice = bill([receive(po, 10)])
		confirmation = make_confirmation(invoice.name)
		with self.assertRaises(ValidationError):
			make_sales_invoice(confirmation.name)
		manual = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": "Ecofinit Dubai",
				"customer": "Metal Green Saudi Arabia",
				"currency": "SAR",
				"selling_price_list": "Intercompany SAR",
				"update_stock": 1,
				"set_warehouse": "Receiving - ED",
				"items": [{"item_code": "ALU-DROSS-001", "qty": 10, "uom": "MT", "rate": 2200}],
			}
		)
		with self.assertRaises(ValidationError):
			manual.insert()

	def test_invoice_value_must_match_confirmation_and_is_single_use(self):
		po = make_purchase_order(10)
		confirmation = self.approved_confirmation([receive(po, 10)])
		tampered = make_sales_invoice(confirmation.name)
		tampered.items[0].rate = 3000
		with self.assertRaises(ValidationError):
			tampered.insert()
		sales_invoice = make_sales_invoice(confirmation.name)
		sales_invoice.insert()
		sales_invoice.submit()
		confirmation.reload()
		self.assertEqual(confirmation.sales_invoice, sales_invoice.name)
		self.assertEqual(sales_invoice.net_total, confirmation.total_sales_value)
		second = make_sales_invoice(confirmation.name)
		with self.assertRaises(ValidationError):
			second.insert()

	def test_full_chain_and_tracker(self):
		po = make_purchase_order(10)
		receipt = receive(po, 10)
		confirmation = self.approved_confirmation([receipt])
		sales_invoice = make_sales_invoice(confirmation.name)
		sales_invoice.insert()
		sales_invoice.submit()
		purchase_invoice = make_inter_company_purchase_invoice(sales_invoice.name)
		purchase_invoice.bill_no = sales_invoice.name
		purchase_invoice.bill_date = nowdate()
		purchase_invoice.insert()
		purchase_invoice.submit()

		self.assertEqual(purchase_invoice.company, "Metal Green Saudi Arabia")
		self.assertEqual(purchase_invoice.inter_company_invoice_reference, sales_invoice.name)
		bin_qty = frappe.db.get_value(
			"Bin", {"item_code": "ALU-DROSS-001", "warehouse": "Receiving - MGS"}, "actual_qty"
		)
		self.assertGreaterEqual(bin_qty, 10)

		for user in ("Administrator", BUYER, METAL_GREEN_USER):
			frappe.set_user(user)
			_, rows = run_tracker({})
			match = [row for row in rows if row.sales_invoice == sales_invoice.name]
			self.assertEqual(len(match), 1, user)
			row = match[0]
			self.assertEqual(row.purchase_invoice, purchase_invoice.name)
			self.assertEqual(row.confirmation, confirmation.name)
			self.assertEqual((row.item_code, row.qty, row.uom, row.value), ("ALU-DROSS-001", 10, "MT", 22000))
			self.assertEqual(row.status, "Completed")

	def test_tracker_status_before_purchase_invoice(self):
		po = make_purchase_order(10)
		confirmation = self.approved_confirmation([receive(po, 10)])
		sales_invoice = make_sales_invoice(confirmation.name)
		sales_invoice.insert()
		sales_invoice.submit()
		_, rows = run_tracker({})
		row = next(r for r in rows if r.sales_invoice == sales_invoice.name)
		self.assertEqual(row.status, "Awaiting Purchase Invoice")
		frappe.set_user(METAL_GREEN_USER)
		_, rows = run_tracker({})
		self.assertFalse([r for r in rows if r.sales_invoice == sales_invoice.name])
