NAVIGATION = {
    "sales": {
        "target": "#sales-display",
        "items": [
            {"label": "Dashboard",    "icon": "speedometer2", "url": "sales:sales_dashboard"},
            {"label": "Sales Orders", "icon": "receipt",      "url": "sales:sales_orders_list"},
            {"label": "Customers",    "icon": "people",       "url": "accounting:customers"},
        ],
    },
    "purchases": {
        "target": "#purchases-display",
        "items": [
            {"label": "Dashboard",       "icon": "speedometer2", "url": "purchases:purchases_dashboard"},
            {"label": "Purchase Orders", "icon": "receipt",      "url": "purchases:purchases_list"},
            {"label": "Suppliers",       "icon": "people",       "url": "accounting:suppliers"},
        ],
    },

    "inventory": {
        "target": "#inventory-display",
        "items": [
            {
                "label": "Overview",
                "icon": "speedometer2",
                "url": "inventory:inventory_dashboard",
                "css_class": "dashboard-page",
                "data_urls": {"charts-url": "inventory:stock_charts"},
            },

            {
                "label": "Operations",
                "icon": "arrow-left-right",
                "sections": [
                    {
                        "label": "Transfers",
                        "items": [
                            {"label": "Receipts", "icon": "box-arrow-in-down", "url": "inventory:receipt_list"},
                            {"label": "Deliveries", "icon": "truck", "url": "inventory:delivery_list"},
                            {"label": "Returns", "icon": "arrow-return-left", "url": "inventory:return_list"},
                            {"label": "Internal Transfers", "icon": "arrow-repeat",
                             "url": "inventory:internal_transfer_list"},
                        ],
                    },
                    {
                        "label": "Stock Control",
                        "items": [
                            {"label": "Physical Inventory", "icon": "clipboard-check",
                             "url": "inventory:physical_inventory"},
                        ],
                    },
                ],
            },

            {"label": "Products", "icon": "boxes", "url": "inventory:view_stock"},

            {
                "label": "Configurations",
                "icon": "gear",
                "sections": [
                    {
                        "label": "Inventory Configuration",
                        "items": [
                            {"label": "Warehouses", "icon": "building", "url": "inventory:warehouse_list"},
                            {"label": "Locations", "icon": "geo-alt", "url": "inventory:locations_list"},
                            {"label": "Categories", "icon": "tags-fill", "url": "inventory:view_categories"},

                        ],
                    }
                ],
            },
        ],
    },


    "accounting": {
        "target": "#accounting-display",
        "items": [
            {
                "label": "Accounting",
                "icon": "journal-text",
                "sections": [
                    {
                        "label": "Overview",
                        "items": [
                            {"label": "Dashboard", "icon": "speedometer2", "url": "accounting:accounting_dashboard"},
                        ],
                    },
                    {
                        "label": "Journals",
                        "items": [
                            {"label": "Journal Entries", "icon": "book",             "url": "accounting:journal_entries"},
                            {"label": "Reconciliation",  "icon": "arrow-left-right", "url": "accounting:reconciliation"},
                        ],
                    },
                ],
            },
            {
                "label": "Customers",
                "icon": "people",
                "sections": [
                    {
                        "label": "Receivables",
                        "items": [
                            {"label": "Invoices",     "icon": "receipt",           "url": "accounting:customer_invoices"},
                            {"label": "Payments",     "icon": "cash-stack",        "url": "accounting:customer_payments"},
                            {"label": "AR Aging",     "icon": "clock-history",     "url": "accounting:ar_aging"},
                            {"label": "Credit Notes", "icon": "arrow-return-left", "url": "accounting:customers_credit_notes"},
                        ],
                    },
                    {
                        "label": "Customers",
                        "items": [
                            {"label": "Customer List", "icon": "person-lines-fill", "url": "accounting:customers"},
                        ],
                    },
                ],
            },
            {
                "label": "Vendors",
                "icon": "truck",
                "sections": [
                    {
                        "label": "Payables",
                        "items": [
                            {"label": "Purchase Invoices", "icon": "receipt",           "url": "accounting:vendor_invoices"},
                            {"label": "Payments",          "icon": "cash-stack",        "url": "accounting:vendor_payments"},
                            {"label": "AP Aging",          "icon": "clock-history",     "url": "accounting:ap_aging"},
                            {"label": "Credit Notes",      "icon": "arrow-return-left", "url": "accounting:vendors_credit_notes"},
                        ],
                    },
                    {
                        "label": "Suppliers",
                        "items": [
                            {"label": "Supplier List", "icon": "person-lines-fill", "url": "accounting:vendors"},
                        ],
                    },
                ],
            },
            {
                "label": "Reporting",
                "icon": "bar-chart-line",
                "sections": [
                    {
                        "label": "Financial statements",
                        "items": [
                            {"label": "Balance Sheet",   "icon": "bank",       "url": "accounting:balance_sheet"},
                            {"label": "Profit and Loss", "icon": "graph-up",   "url": "accounting:profit_and_loss"},
                            {"label": "Trial Balance",   "icon": "list-check", "url": "accounting:trial_balance"},
                        ],
                    },
                    {
                        "label": "Analysis",
                        "items": [
                            {"label": "General Ledger", "icon": "journal-text", "url": "accounting:general_ledger"},
                        ],
                    },
                ],
            },
            {
                "label": "Configuration",
                "icon": "gear",
                "sections": [
                    {
                        "label": "Chart of accounts",
                        "items": [
                            {"label": "Accounts", "icon": "diagram-3", "url": "accounting:accounts_list"},
                        ],
                    },
                    {
                        "label": "Setup",
                        "items": [
                            {"label": "Journals",   "icon": "journals",          "url": "accounting:journals_list"},
                            {"label": "Currencies", "icon": "currency-exchange", "url": "accounting:currency_view"},
                            {"label": "Tax",        "icon": "percent",           "url": "accounting:taxes_list"},
                        ],
                    },
                ],
            },
        ],
    },
}