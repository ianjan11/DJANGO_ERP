from django.urls import path
from . import views


app_name = 'accounting'
urlpatterns = [
    # ----------------------------payments--------------------------------#
    path('accounting/dashboard/', views.accounting_dashboard, name='accounting_dashboard'),
    path('accounting/payments/customer/', views.customer_payments, name='customer_payments'),
    path('accounting/payments/vendor/', views.vendor_payments, name='vendor_payments'),
    path('accounting/payments/create/', views.save_payments, name='create_payment'),
    path('accounting/payments/create_prepayment/', views.save_pre_payments, name='create_pre_payment'),
    path('accounting/payments/edit/<int:payment_id>/', views.edit_payments, name='edit_payment'),

    path('accounting/payments/<int:payment_id>/', views.payment_details, name='payment_details'),
    path('accounting/payment/<int:payment_id>/post/', views.post_payment_view, name='post_payment'),
    path('accounting/payments/refresh/', views.refresh_payments, name='refresh_payments'),
    path('accounting/payments/new/prepayment/', views.get_empty_payment_form, name='get_empty_payment_form'),

    path('accounting/payments/<int:payment_id>/cancel_payment', views.cancel_payment_view, name='cancel_payment'),
    path('accounting/payments/<int:payment_id>/apply_pre_payment', views.apply_pre_payment_view, name='apply_pre_payment'),

    path('accounting/ar-aging/', views.ar_aging_report, name='ar_aging'),
    path('accounting/ap-aging/', views.ap_aging_report, name='ap_aging'),
    path('accounting/trial-balance/', views.trial_balance, name='trial_balance'),
    path('accounting/balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('accounting/profit-loss/', views.profit_and_loss, name='profit_and_loss'),
    path('accounting/general-ledger/', views.get_general_ledger, name='general_ledger'),

    path('accounting/journal-entries/', views.journal_entries, name='journal_entries'),
    path('accounting/journal-entry/<int:move_id>/', views.journal_create_or_detail, name='journal_detail'),
    path('accounting/journal-entry/create/', views.journal_create_or_detail, name='create_journal'),
    path('accounting/journal-entry/<int:move_id>/item-row/', views.journal_item_row, name='journal_item_row'),
    path('accounting/journal-entry/<int:move_id>/totals/', views.journal_totals, name='journal_totals'),

    path('accounting/journal-entry/<int:move_id>/delete/', views.delete_journal_view, name='delete_journal'),
    path('accounting/journal-entry/<int:move_id>/cancel/', views.cancel_journal_view, name='cancel_journal'),
    path('accounting/journal-entry/<int:move_id>/post/', views.post_journal_view, name='post_journal'),

    path('accounting/journal-entry/update/', views.journal_update, name='journal_update'),

    path("accounting/credit-notes/vendor/", views.vendor_credit_notes_view, name="vendors_credit_notes"),
    path("accounting/credit-notes/customer/", views.customer_credit_notes_view, name="customers_credit_notes"),

    path('accounting/journals/reconciliation/', views.reconciliation_page_view, name='reconciliation'),
    path('accounting/journals/reconcile/', views.reconcile_journal, name='reconcile_journal'),
    path('accounting/journals/auto_reconcile/', views.auto_reconcile_journal, name='auto_reconcile_journal'),

    path('accounting/invoices/customer', views.customer_invoices, name='customer_invoices'),
    path('accounting/invoices/vendor', views.vendor_invoices, name='vendor_invoices'),
    path('accounting/invoices/update/', views.invoice_update, name='invoice_update'),
    path('accounting/invoices/<int:invoice_id>/totals/', views.invoice_totals, name='invoice_totals'),
    path('accounting/invoice/create/', views.invoice_create_or_detail, name='invoice_create'),
    path('accounting/invoice/<int:invoice_id>/item-rows/', views.invoice_item_row, name='invoice_item_row'),
    path('accounting/invoices/<int:invoice_id>/cancel/', views.cancel_invoice, name='cancel_invoice'),

    path('accounting/invoices/<int:invoice_id>/reset/', views.reset_invoice, name='reset_invoice'),
    path('accounting/invoices/refresh/<int:invoice_id>/', views.refresh_invoice_view, name='invoice_refresh'),
    path('accounting/invoice/<int:invoice_id>/', views.invoice_create_or_detail, name='invoice_create_or_detail'),
    path('accounting/invoices/<int:invoice_id>/post/', views.post_invoice_view, name='post_invoice'),
    path('accounting/invoices/<int:invoice_id>/credit/', views.issue_credit_note_view, name='credit_invoice'),

    path('accounting/customers/', views.get_customers_view, name='customers'),
    path('accounting/vendors/', views.get_vendors_view, name='vendors'),
    path('accounting/partner/create/', views.create_partner_view, name='partner_create'),
    path('accounting/partner/<int:partner_id>/', views.partners_details_view, name='partner_detail'),
    path('accounting/partner/<int:partner_id>/edit', views.edit_partner_view, name='partner_edit'),

    path('accounting/configurations/accounts/', views.accounts_list_view, name='accounts_list'),
    path('accounting/configurations/account/<int:account_id>/', views.account_detail, name='account_detail'),
    path('accounting/configurations/account/<int:account_id>/edit/', views.edit_account, name='account_edit'),
    path('accounting/configurations/account/empty-form/', views.get_empty_account_form, name='get_empty_account_form'),
    path('accounting/configurations/account/create/', views.create_account, name='create_account'),
    path('accounting/configurations/account/delete/', views.delete_account, name='delete_account'),
    path('accounting/configurations/account/toggle/<int:account_id>/', views.toggle_account_view,name='toggle_account'),
    path('accounting/configurations/account/toggle/reconciliation/<int:account_id>/', views.toggle_account_reconciliation_view,
         name='toggle_reconciliation'),

    path('accounting/configurations/currency/', views.currency_view, name='currency_view'),
    path('accounting/configurations/currency/rate/<int:currency_id>/', views.save_rate_view, name='save_rate'),
    path('accounting/configurations/currency/rate/sync/', views.sync_rate_view, name='sync_rates'),
    path('accounting/configurations/currency/toggle/<int:currency_id>/', views.toggle_currency_view, name='toggle_currency'),
    path('accounting/configurations/currency/empty-row/', views.get_empty_currency_row, name='get_empty_currency_row'),
    path('accounting/configurations/currency/save/', views.add_currency_view, name='add_currency'),

    path('accounting/configurations/journals/', views.journals_list_view, name='journals_list'),
    path('accounting/configurations/journals/<int:journal_id>/', views.journal_detail, name='company_journal_detail'),
    path('accounting/configurations/journals/<int:journal_id>/edit/', views.edit_journal, name='journal_edit'),
    path('accounting/configurations/journals/create/', views.create_journal, name='journal_create'),
    path('accounting/configurations/journals/form/', views.get_empty_journal_form, name='get_empty_journal_form'),
    path('accounting/configurations/journals/delete/', views.delete_journal, name='journals_delete'),

    path("accounting/configurations/taxes/",views.taxes_view,name="taxes_list",),
    path("accounting/configurations/taxes/<int:tax_id>/",views.tax_detail, name="tax_detail",),
    path("accounting/configurations/taxes/<int:tax_id>/edit/",views.edit_tax,name="tax_edit",),
    path("accounting/configurations/taxes/create/",views.create_tax,name="tax_create",),
    path("accounting/configurations/taxes/form/",views.get_empty_tax_form,name="get_empty_tax_form",),
    path("accounting/configurations/taxes/delete/",views.delete_tax,name="taxes_delete",),
    path('accounting/configurations/tax/toggle/<int:tax_id>/', views.toggle_tax_view,name='toggle_tax'),

]
