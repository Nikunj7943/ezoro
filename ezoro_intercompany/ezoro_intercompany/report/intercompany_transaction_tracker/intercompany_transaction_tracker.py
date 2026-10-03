import frappe
from frappe import _
from frappe.permissions import get_user_permissions


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = get_rows(filters)
	if filters.status:
		rows = [row for row in rows if row["status"] == filters.status]
	return get_columns(), rows


def get_columns():
	return [
		{"label": _("Supplier Invoice"), "fieldname": "supplier_invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
		{"label": _("Sales Value Confirmation"), "fieldname": "confirmation", "fieldtype": "Link", "options": "Sales Value Confirmation", "width": 160},
		{"label": _("Ecofinit Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"label": _("Metal Green Purchase"), "fieldname": "purchase_invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 190},
	]


def get_rows(filters):
	conditions = ["si.is_internal_customer = 1", "si.is_return = 0", "si.docstatus < 2"]
	values = {}
	if filters.from_date:
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.to_date:
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.item_code:
		conditions.append("sii.item_code = %(item_code)s")
		values["item_code"] = filters.item_code

	companies = [d.get("doc") for d in get_user_permissions(frappe.session.user).get("Company", [])]
	if companies:
		conditions.append("(si.company in %(companies)s or pi.company in %(companies)s)")
		values["companies"] = companies

	data = frappe.db.sql(
		f"""
		select
			svc.purchase_invoice as supplier_invoice,
			si.sales_value_confirmation as confirmation,
			si.name as sales_invoice,
			si.docstatus as si_docstatus,
			pi.name as purchase_invoice,
			pi.docstatus as pi_docstatus,
			sii.item_code,
			sii.qty,
			sii.uom,
			sii.net_amount as value,
			si.currency
		from `tabSales Invoice` si
		inner join `tabSales Invoice Item` sii on sii.parent = si.name
		left join `tabPurchase Invoice` pi
			on pi.inter_company_invoice_reference = si.name and pi.docstatus < 2
		left join `tabSales Value Confirmation` svc on svc.name = si.sales_value_confirmation
		where {" and ".join(conditions)}
		order by si.posting_date desc, si.name desc, sii.idx
		""",
		values,
		as_dict=True,
	)
	for row in data:
		row["status"] = get_status(row)
	return data


def get_status(row):
	if row.si_docstatus == 0:
		return "Sales Invoice Draft"
	if not row.purchase_invoice:
		return "Awaiting Purchase Invoice"
	if row.pi_docstatus == 0:
		return "Purchase Invoice Draft"
	return "Completed"
