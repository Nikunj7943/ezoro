import frappe

ECOFINIT = "Ecofinit Dubai"
METAL_GREEN = "Metal Green Saudi Arabia"
ITEM_CODE = "ALU-DROSS-001"
UOM = "MT"
EXTERNAL_SUPPLIER = "Gulf Metal Recyclers"
PRICE_LIST = "Intercompany SAR"
SAR_TO_AED = 0.9793
DEMO_PASSWORD = "nikunj@123"

USERS = [
	{
		"email": "ecofinit.buyer@example.com",
		"first_name": "Ecofinit",
		"last_name": "Buyer",
		"company": ECOFINIT,
		"roles": ["Purchase User", "Stock User", "Accounts User", "Sales User"],
	},
	{
		"email": "ecofinit.approver@example.com",
		"first_name": "Ecofinit",
		"last_name": "Approver",
		"company": ECOFINIT,
		"roles": ["Purchase User", "Stock User", "Accounts User", "Sales User", "Sales Value Approver"],
	},
	{
		"email": "metalgreen.user@example.com",
		"first_name": "Metal Green",
		"last_name": "User",
		"company": METAL_GREEN,
		"roles": ["Purchase User", "Stock User", "Accounts User"],
	},
]


COMPANIES = [
	{
		"company_name": ECOFINIT,
		"abbr": "ED",
		"default_currency": "AED",
		"country": "United Arab Emirates",
		"chart_of_accounts": "U.A.E - Chart of Accounts",
	},
	{
		"company_name": METAL_GREEN,
		"abbr": "MGS",
		"default_currency": "SAR",
		"country": "Saudi Arabia",
		"chart_of_accounts": "Standard",
	},
]

WAREHOUSES = [("Receiving", ECOFINIT), ("Receiving", METAL_GREEN), ("Main", METAL_GREEN)]


def after_install():
	if frappe.is_setup_complete():
		run()
	else:
		print("Complete the ERPNext setup wizard, then run: bench execute ezoro_intercompany.setup.masters.run")


def run():
	ensure_currencies()
	ensure_companies()
	abbr = {company: frappe.get_cached_value("Company", company, "abbr") for company in (ECOFINIT, METAL_GREEN)}
	ensure_warehouses(abbr)
	ensure_uom()
	ensure_price_list()
	ensure_exchange_rate()
	ensure_ecofinit_accounts(abbr[ECOFINIT])
	ensure_item(abbr)
	ensure_external_supplier(abbr[ECOFINIT])
	ensure_internal_customer(abbr[ECOFINIT])
	ensure_internal_supplier()
	for user in USERS:
		ensure_user(user)
	frappe.db.commit()


def ensure(doctype, filters, values):
	name = frappe.db.exists(doctype, filters)
	if name:
		return frappe.get_doc(doctype, name)
	return frappe.get_doc({"doctype": doctype, **values}).insert()


def ensure_currencies():
	for currency in ("AED", "SAR"):
		frappe.db.set_value("Currency", currency, "enabled", 1)


def ensure_companies():
	for spec in COMPANIES:
		ensure(
			"Company",
			spec["company_name"],
			{**spec, "create_chart_of_accounts_based_on": "Standard Template"},
		)


def ensure_warehouses(abbr):
	for name, company in WAREHOUSES:
		ensure(
			"Warehouse",
			f"{name} - {abbr[company]}",
			{
				"warehouse_name": name,
				"company": company,
				"parent_warehouse": f"All Warehouses - {abbr[company]}",
			},
		)


def ensure_uom():
	ensure("UOM", UOM, {"uom_name": UOM, "must_be_whole_number": 0})


def ensure_price_list():
	ensure(
		"Price List",
		PRICE_LIST,
		{"price_list_name": PRICE_LIST, "currency": "SAR", "buying": 1, "selling": 1, "enabled": 1},
	)


def ensure_exchange_rate():
	ensure(
		"Currency Exchange",
		{"from_currency": "SAR", "to_currency": "AED"},
		{
			"date": "2026-01-01",
			"from_currency": "SAR",
			"to_currency": "AED",
			"exchange_rate": SAR_TO_AED,
			"for_buying": 1,
			"for_selling": 1,
		},
	)


def ensure_ecofinit_accounts(abbr):
	ensure_account(f"Trade Receivable SAR - {abbr}", "Trade Receivable SAR", f"Accounts Receivable - {abbr}", "Receivable")
	ensure_account(f"Trade Payable SAR - {abbr}", "Trade Payable SAR", f"Payables - {abbr}", "Payable")
	company = frappe.get_doc("Company", ECOFINIT)
	company.default_receivable_account = f"Trade Receivable - {abbr}"
	company.exchange_gain_loss_account = f"Loss on Difference on Exchange - {abbr}"
	company.save()


def ensure_account(name, account_name, parent, account_type):
	ensure(
		"Account",
		name,
		{
			"account_name": account_name,
			"parent_account": parent,
			"company": ECOFINIT,
			"account_type": account_type,
			"account_currency": "SAR",
		},
	)


def ensure_item(abbr):
	ensure(
		"Item",
		ITEM_CODE,
		{
			"item_code": ITEM_CODE,
			"item_name": "Aluminium Dross",
			"item_group": "Raw Material",
			"stock_uom": UOM,
			"is_stock_item": 1,
			"include_item_in_manufacturing": 0,
			"item_defaults": [
				{
					"company": ECOFINIT,
					"default_warehouse": f"Receiving - {abbr[ECOFINIT]}",
					"income_account": f"Sales of I/C - {abbr[ECOFINIT]}",
				},
				{"company": METAL_GREEN, "default_warehouse": f"Receiving - {abbr[METAL_GREEN]}"},
			],
		},
	)


def ensure_external_supplier(abbr):
	ensure(
		"Supplier",
		{"supplier_name": EXTERNAL_SUPPLIER},
		{
			"supplier_name": EXTERNAL_SUPPLIER,
			"supplier_group": "Raw Material",
			"default_currency": "SAR",
			"default_price_list": PRICE_LIST,
			"accounts": [{"company": ECOFINIT, "account": f"Trade Payable SAR - {abbr}"}],
		},
	)


def ensure_internal_customer(abbr):
	ensure(
		"Customer",
		{"customer_name": METAL_GREEN},
		{
			"customer_name": METAL_GREEN,
			"customer_group": "Commercial",
			"territory": "Rest Of The World",
			"is_internal_customer": 1,
			"represents_company": METAL_GREEN,
			"companies": [{"company": ECOFINIT}],
			"default_currency": "SAR",
			"default_price_list": PRICE_LIST,
			"accounts": [{"company": ECOFINIT, "account": f"Trade Receivable SAR - {abbr}"}],
		},
	)


def ensure_internal_supplier():
	ensure(
		"Supplier",
		{"supplier_name": ECOFINIT},
		{
			"supplier_name": ECOFINIT,
			"supplier_group": "Raw Material",
			"is_internal_supplier": 1,
			"represents_company": ECOFINIT,
			"companies": [{"company": METAL_GREEN}],
			"default_currency": "SAR",
			"default_price_list": PRICE_LIST,
		},
	)


def ensure_user(spec):
	if frappe.db.exists("User", spec["email"]):
		user = frappe.get_doc("User", spec["email"])
		user.add_roles(*spec["roles"])
	else:
		frappe.get_doc(
			{
				"doctype": "User",
				"email": spec["email"],
				"first_name": spec["first_name"],
				"last_name": spec["last_name"],
				"user_type": "System User",
				"send_welcome_email": 0,
				"new_password": DEMO_PASSWORD,
				"roles": [{"role": role} for role in spec["roles"]],
			}
		).insert()
	ensure(
		"User Permission",
		{"user": spec["email"], "allow": "Company", "for_value": spec["company"]},
		{
			"user": spec["email"],
			"allow": "Company",
			"for_value": spec["company"],
			"apply_to_all_doctypes": 1,
			"is_default": 1,
		},
	)
