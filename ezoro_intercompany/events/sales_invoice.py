import frappe
from frappe import _
from frappe.utils import flt

APPROVED = "Approved"


def is_intercompany_sale(doc):
	return frappe.db.get_value("Customer", doc.customer, "is_internal_customer") and not doc.is_return


def validate(doc, method=None):
	if not is_intercompany_sale(doc):
		return
	if not doc.get("sales_value_confirmation"):
		frappe.throw(_("An approved Sales Value Confirmation is required for intercompany sales"))
	svc = frappe.get_doc("Sales Value Confirmation", doc.sales_value_confirmation)
	if svc.docstatus != 1 or svc.workflow_state != APPROVED:
		frappe.throw(_("Sales Value Confirmation {0} is not approved").format(svc.name))
	if svc.company != doc.company or svc.customer != doc.customer:
		frappe.throw(_("Sales Value Confirmation {0} does not match company or customer").format(svc.name))
	if svc.sales_invoice and svc.sales_invoice != doc.name:
		frappe.throw(_("Sales Value Confirmation {0} is already used in {1}").format(svc.name, svc.sales_invoice))
	if flt(doc.net_total, 2) != flt(svc.total_sales_value, 2):
		frappe.throw(
			_("Invoice value {0} differs from the confirmed sales value {1}").format(
				doc.net_total, svc.total_sales_value
			)
		)


def on_submit(doc, method=None):
	if doc.get("sales_value_confirmation"):
		frappe.db.set_value("Sales Value Confirmation", doc.sales_value_confirmation, "sales_invoice", doc.name)


def on_cancel(doc, method=None):
	if doc.get("sales_value_confirmation"):
		frappe.db.set_value("Sales Value Confirmation", doc.sales_value_confirmation, "sales_invoice", None)
