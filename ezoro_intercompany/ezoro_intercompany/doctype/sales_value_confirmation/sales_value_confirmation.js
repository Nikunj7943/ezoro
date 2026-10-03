frappe.ui.form.on("Sales Value Confirmation", {
	setup(frm) {
		frm.set_query("customer", () => ({ filters: { is_internal_customer: 1, disabled: 0 } }));
		frm.set_query("purchase_invoice", () => ({
			filters: { company: frm.doc.company, docstatus: 1 },
		}));
	},

	purchase_invoice(frm) {
		if (!frm.doc.purchase_invoice) return;
		frappe.call({
			method: "ezoro_intercompany.ezoro_intercompany.doctype.sales_value_confirmation.sales_value_confirmation.get_invoice_items",
			args: { purchase_invoice: frm.doc.purchase_invoice },
			callback({ message }) {
				frm.clear_table("items");
				(message || []).forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			},
		});
	},

	refresh(frm) {
		const approved = frm.doc.docstatus === 1 && frm.doc.workflow_state === "Approved";
		if (approved && !frm.doc.sales_invoice) {
			frm.add_custom_button(__("Sales Invoice"), () =>
				frappe.model.open_mapped_doc({
					method: "ezoro_intercompany.ezoro_intercompany.doctype.sales_value_confirmation.sales_value_confirmation.make_sales_invoice",
					frm,
				}), __("Create")
			);
		}
	},
});

frappe.ui.form.on("Sales Value Confirmation Item", {
	sales_rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.sales_rate));
	},
});
