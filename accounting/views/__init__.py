from .payments.payments_list import (customer_payments,
                                    vendor_payments, refresh_payments)
from .payments.direct_payment import save_payments
from .payments.pre_payments import save_pre_payments, edit_payments, get_empty_payment_form
from .reports.trial_balance import trial_balance
from  .reports.general_ledger import get_general_ledger
from .reports.statements.balance_sheet import balance_sheet
from .reports.statements.profit_and_loss import profit_and_loss
from .payments.payments_actions import (payment_details,cancel_payment_view,post_payment_view,
                                        apply_pre_payment_view)
from .accounting_dashboard import accounting_dashboard
from .reports.aging_reports.aging_reports import ar_aging_report, ap_aging_report

from .move_views.move_updates import  (invoice_item_row, invoice_update, invoice_totals)
from .move_views.sales_dashboard import sales_dashboard
from .move_views.move_list import (customer_invoices, vendor_invoices,
                                   vendor_credit_notes_view , customer_credit_notes_view)

from .move_views.move_updates import (invoice_update, invoice_totals, invoice_create_or_detail,
                                      invoice_item_row,
                                      post_invoice_view, cancel_invoice,
                                      refresh_invoice_view, reset_invoice)

from .move_views.move_credit_note import issue_credit_note_view

from .journal_entries.journal_entries import (journal_entries, journal_create_or_detail, journal_item_row,
                                              journal_update, journal_totals, post_journal_view,
                                              cancel_journal_view,delete_journal_view)

from .partners.partners import get_vendors_view, get_customers_view, create_partner_view
from .partners.partners_details import partners_details_view, edit_partner_view

from .recocniliation.recocniliation import reconciliation_page_view
from .recocniliation.reconcile_journal import reconcile_journal, auto_reconcile_journal


from .configurations.accounts import (accounts_list_view, account_detail, edit_account,
                                      get_empty_account_form,toggle_account_view,toggle_account_reconciliation_view,
                                      create_account, delete_account)

from .configurations.currency import (currency_view, save_rate_view, sync_rate_view, toggle_currency_view,
                                      get_empty_currency_row, add_currency_view)


from .configurations.journals import  (journals_list_view, journal_detail, edit_journal, create_journal,
                                       delete_journal, get_empty_journal_form)

from .configurations.taxes import (taxes_view,toggle_tax_view,tax_detail,create_tax, delete_tax,
                                   get_empty_tax_form, edit_tax)