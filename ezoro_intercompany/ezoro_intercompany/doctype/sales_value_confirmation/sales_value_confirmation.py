import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt

APPROVED = "Approved"


class SalesValueConfirmation(Document):
	def validate(self):
		self.validate_purchase_invoice()
		self.validate_customer()
		self.calculate_totals()

	def validate_purchase_invoice(self):
		invoice = frappe.db.get_value(
			"Purchase Invoice", self.purchase_invoice, ["company", "docstatus"], as_dict=True
		)
		if invoice.docstatus != 1:
			frappe.throw(_("Supplier Invoice {0} must be submitted").format(self.purchase_invoice))
		if invoice.company != self.company:
			frappe.throw(_("Supplier Invoice {0} belongs to a different company").format(self.purchase_invoice))

	def validate_customer(self):
		represents = frappe.db.get_value(
			"Customer", self.customer, ["is_internal_customer", "represents_company"], as_dict=True
		)
		if not represents.is_internal_customer or represents.represents_company == self.company:
			frappe.throw(_("{0} is not an intercompany customer of {1}").format(self.customer, self.company))

	def calculate_totals(self):
		self.total_cost = self.total_sales_value = 0
		for row in self.items:
			row.amount = flt(row.qty) * flt(row.sales_rate)
			self.total_cost += flt(row.qty) * flt(row.cost_rate)
			self.total_sales_value += row.amount

	def on_cancel(self):
		if self.sales_invoice and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") != 2:
			frappe.throw(_("Cancel Sales Invoice {0} first").format(self.sales_invoice))


@frappe.whitelist()
def get_invoice_items(purchase_invoice):
	frappe.has_permission("Purchase Invoice", "read", purchase_invoice, throw=True)
	rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": purchase_invoice},
		fields=["item_code", "item_name", {"SUM": "qty", "as": "qty"}, "uom", "rate as cost_rate"],
		group_by="item_code, uom, rate",
	)
	return rows


@frappe.whitelist()
def make_sales_invoice(source_name):
	frappe.has_permission("Sales Invoice", "create", throw=True)

	def set_missing_values(source, target):
		target.selling_price_list = frappe.db.get_value("Customer", source.customer, "default_price_list")
		target.update_stock = 1
		target.set_warehouse = frappe.db.get_value(
			"Item Default",
			{"parent": source.items[0].item_code, "company": source.company},
			"default_warehouse",
		)
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	return get_mapped_doc(
		"Sales Value Confirmation",
		source_name,
		{
			"Sales Value Confirmation": {
				"doctype": "Sales Invoice",
				"field_map": {"name": "sales_value_confirmation", "customer": "customer", "company": "company", "currency": "currency"},
				"field_no_map": ["naming_series", "posting_date", "workflow_state", "remarks"],
				"validation": {"docstatus": ["=", 1], "workflow_state": ["=", APPROVED]},
			},
			"Sales Value Confirmation Item": {
				"doctype": "Sales Invoice Item",
				"field_map": {"sales_rate": "rate"},
			},
		},
		None,
		set_missing_values,
	)
