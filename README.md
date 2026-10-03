# Ezoro Intercompany

ERPNext multi-company assessment: External Supplier -> Ecofinit Dubai -> Metal Green Saudi Arabia.

Tested on Frappe 16.35 and ERPNext 16.37 (version-16), MariaDB, Python 3.14.

## 1. Setup

```bash
bench get-app https://github.com/Nikunj7943/ezoro.git --branch main
bench --site <site> install-app ezoro_intercompany
bench --site <site> migrate
```

Migrate imports the custom doctypes, the report, and the fixtures (role, workflow states and actions, workflow, one custom field).

The two companies are created in the ERPNext UI first:

| Company | Abbr | Currency | Country |
|---|---|---|---|
| Ecofinit Dubai | ED | AED | United Arab Emirates |
| Metal Green Saudi Arabia | MGS | SAR | Saudi Arabia |

Then create the masters and demo users (safe to run again):

```bash
bench --site <site> execute ezoro_intercompany.setup.masters.run
```

This creates: UOM `MT`, price list `Intercompany SAR`, SAR to AED exchange rate, two SAR accounts under Ecofinit, item `ALU-DROSS-001`, supplier `Gulf Metal Recyclers`, the intercompany customer and supplier pair, and three users:

| User | Company | Roles |
|---|---|---|
| ecofinit.buyer@example.com | Ecofinit Dubai | Purchase User, Stock User, Accounts User, Sales User |
| ecofinit.approver@example.com | Ecofinit Dubai | same as buyer plus Sales Value Approver |
| metalgreen.user@example.com | Metal Green Saudi Arabia | Purchase User, Stock User, Accounts User |

Demo password for all three is set in `setup/masters.py` (`DEMO_PASSWORD`). Change it for any real use.

Warehouses used: `Receiving - ED`, `Receiving - MGS`, `Main - MGS`.

## 2. Assumptions

- Ecofinit books in AED but trades in SAR. The PO, supplier invoice and intercompany sale are in SAR; ERPNext converts to AED on the books using a SAR to AED rate of 0.9793 (an assumed demo rate, not a market rate). Because of this, Ecofinit's ledger shows AED amounts that differ from the SAR document totals.
- Both companies use perpetual inventory (ERPNext default for these charts).
- The intercompany price is set by the Sales Value Confirmation (demo markup: SAR 2,000 purchase, SAR 2,200 sale per MT).
- Ecofinit is treated as a document-handling entity but still holds the stock in `Receiving - ED` between receipt and sale, because ERPNext needs a stock movement for the sale to relieve inventory. No cost centres, manufacturing, or operational costing are set up for it.
- The intercompany Purchase Invoice is created by a user who can see both companies (Administrator in the demo). Company-restricted users cannot read the other company's invoice by design.
- VAT, ZATCA and tax templates are out of scope for this build (see question 5).

## 3. Standard ERPNext used

| Requirement | Standard feature |
|---|---|
| Companies, currencies, chart of accounts | Company master and generated chart of accounts |
| Item, warehouses, supplier, customer | Standard masters |
| PO with partial receipts, ordered / received / pending tracking | Purchase Order, "Create Receipt", `received_qty` and `per_received` updates |
| One supplier invoice for three receipts | Purchase Invoice created from several Purchase Receipts |
| Attachments on any document | Attachments sidebar on every transaction |
| Document traceability | Connections tab and linked document fields |
| Ecofinit Sales Invoice to Metal Green Purchase Invoice | Internal Customer / Internal Supplier, "Allowed To Transact With", and Sales Invoice "Create > Inter Company Purchase Invoice" |
| Metal Green stock and warehouse transfer | Stock Entry (Material Transfer), Stock Ledger, Bin |
| Role and company data isolation | Roles, User Permissions on Company |
| Approval workflow engine | Frappe Workflow |

## 4. Customizations and reasons

| Customization | Reason |
|---|---|
| Doctype `Sales Value Confirmation` (+ child table) | ERPNext has no document to record an authorised agreement on the intercompany sale value before the sale is created. Pricing rules set prices automatically; they do not capture a human sign-off. Submittable so an approved record is locked. |
| Workflow `Sales Value Confirmation Approval` (Draft, Pending Approval, Approved, Rejected) and role `Sales Value Approver` | Only an authorised role can approve or reject; the creator cannot approve their own record. |
| Hook on Sales Invoice (`events/sales_invoice.py`) and custom field `sales_value_confirmation` | Server-side gate: an intercompany sale cannot be saved without an approved confirmation that matches company, customer and value, and a confirmation can be used once. This stops bypassing the approval through the API or by creating the invoice by hand. |
| Script Report `Intercompany Transaction Tracker` | Requirement 7. Joins Sales Invoice, Purchase Invoice and the confirmation. Respects company user permissions. |
| `setup/masters.py` | Makes the master data and users repeatable. |

No ERPNext or Frappe core file is modified. All customization is in this app.

Not customized on purpose: partial receipts, purchase tracking, the intercompany Purchase Invoice, warehouse transfers.

One standard behaviour to know: the Purchase Invoice stores the reference to the Sales Invoice (`inter_company_invoice_reference`), but the Sales Invoice field stays empty. The tracker follows the link from the Purchase Invoice side.

## 5. Debugging exercise

Issue: PO for 100 MT, two submitted receipts total 70 MT, but the PO shows 100 MT received.

How ERPNext computes it (`controllers/status_updater.py`, rules in `purchase_receipt.py`): a PO row's `received_qty` is the sum of `received_qty` on submitted Purchase Receipt rows linked by `purchase_order_item`, plus submitted Purchase Invoice rows linked by `po_detail` where the invoice has Update Stock on. `per_received` and the dashboard are derived from that stored value.

Investigation order:

1. Compare the stored value with the source rows for the PO row:

```sql
select poi.name, poi.qty as ordered, poi.received_qty as stored_received,
  (select ifnull(sum(received_qty),0) from `tabPurchase Receipt Item`
     where purchase_order_item = poi.name and docstatus = 1) as receipts_received,
  (select ifnull(sum(qty),0) from `tabPurchase Receipt Item`
     where purchase_order_item = poi.name and docstatus = 1) as receipts_accepted,
  (select ifnull(sum(rejected_qty),0) from `tabPurchase Receipt Item`
     where purchase_order_item = poi.name and docstatus = 1) as receipts_rejected,
  (select ifnull(sum(pii.received_qty),0) from `tabPurchase Invoice Item` pii
     join `tabPurchase Invoice` pi on pi.name = pii.parent
     where pii.po_detail = poi.name and pii.docstatus = 1 and pi.update_stock = 1) as invoices_with_stock
from `tabPurchase Order Item` poi
where poi.parent = 'PUR-ORD-2026-00001';
```

2. If stored differs from the sum of sources, the stored value was changed outside the standard update: check the PO's Version history (track changes), modified timestamps, and any direct database edit or script.
3. If stored equals the sum of sources, the number is explained by the data. Find which source adds the extra quantity: invoices with Update Stock, rejected quantity, or a receipt row linked to the wrong PO row.
4. Rule out customization: Server Scripts, Client Scripts, Custom Fields and Property Setters on the purchasing doctypes, `doc_events` and `override_doctype_class` in installed apps' hooks, and the Error Log and server logs around the receipt submissions. On this site there is nothing touching quantities; the custom fields on purchase documents are ERPNext's UAE VAT fields.
5. Only if the data and customization are clean, treat it as a possible framework defect: reproduce on a clean site, note the exact versions, and search the ERPNext and Frappe issue trackers before changing anything.

I reproduced the two common data causes in a rolled-back transaction on a PO of 100 MT with receipts of 30 and 40:

| Scenario | Stored received | Receipts total | Explanation |
|---|---|---|---|
| Two receipts 30 + 40 | 70 | 70 | correct |
| Plus a 30 MT Purchase Invoice with Update Stock | 100 | 70 | the invoice moved stock and counts as received; cancelling it returns the PO to 70 |
| Second receipt 40 accepted + 30 rejected | 100 | 100 (70 accepted, 30 rejected) | rejected quantity counts as received; "70 MT" refers to accepted quantity only |

Fix is on the data, never a database patch: cancel or amend the offending document so ERPNext recalculates. A direct database edit of a submitted document is not used.

## 6. Technical questions

**1. What was achieved with standard ERPNext?** Company setup, masters, partial receipts and quantity tracking, supplier invoice against several receipts, attachments, traceability, the intercompany Purchase Invoice, Metal Green stock and the warehouse transfer, roles and company restrictions, and the workflow engine itself.

**2. What was customized?** The Sales Value Confirmation doctype and its workflow and role, the Sales Invoice gate and one custom field, the tracker report, and the setup script.

**3. Why was each customization necessary?** See section 4. Each covers something ERPNext has no document or rule for: a recorded, approved sales value that blocks the sale until approved, and a cross-document view.

**4. What would change before production?** Real exchange rates (Currency Exchange updates or a feed) instead of a fixed rate; tax templates and VAT; a proper intercompany price source (price list or transfer pricing policy) instead of manual rates; email or notification for approvals; stronger tests including permissions and cancellation paths; handling partial intercompany sales and returns; backup, monitoring and a staging site; replace demo users and passwords; review the intercompany credit/payment settlement between the two companies.

**5. Saudi VAT and ZATCA e-invoicing for Metal Green?** Treat it as a separate, later phase on the Metal Green company only. Start from ERPNext's KSA localization (company country Saudi Arabia, VAT accounts and tax templates, VAT report). For ZATCA, use an integration for Phase 2 (clearance and reporting): QR code and UBL XML generation, cryptographic stamp, onboarding with ZATCA (CSID), and submission with status stored on the Sales Invoice. Because Metal Green is the buyer in this flow, its main early need is correct input VAT on purchase invoices; e-invoicing applies when it issues sales invoices. Keep it in its own app or a maintained community app, not in this app.

**6. Upgrade safety?** Keep all custom code in this app and never edit core. Prefer hooks, doc events, fixtures, custom fields and reports over overriding core classes; where an override is unavoidable, keep it small and covered by a test. Pin versions, keep fixtures in the repo, run `bench migrate` on a staging copy of production data before upgrading, run the test suite on the new version, and read the ERPNext and Frappe release notes for changes to the APIs used (here: `get_mapped_doc`, workflow, `get_user_permissions`, the Sales Invoice validate hook).

**7. Permissions and data isolation for three companies?** Use User Permissions on Company with "apply to all doctypes" so users see only their company's records; keep shared masters such as items and UOMs unrestricted. ERPNext already lets the Item Defaults, Allowed To Transact With and Party Account company fields ignore user permissions, which is why the cross-company customer and supplier setup works for restricted users. Use roles for what a user can do and user permissions for which company's data. Add a small group role for cross-company roles (finance, auditors) with permissions for the companies they cover. Script reports that use raw SQL must apply company filtering themselves, as the tracker does. Consider Permission Query Conditions for any further raw-SQL reports, and test with a restricted user for every new report or API.
