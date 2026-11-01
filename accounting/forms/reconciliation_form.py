from django import forms
from accounting.models import AccountMove, PaymentInvoiceLine, AccountMoveLine
from django.core.exceptions import ValidationError


class ReconcilePaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentInvoiceLine
        fields = ['invoice_move', 'amount']
        widgets = {
            'invoice_move': forms.HiddenInput(),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
            }),
        }

    def __init__(self, *args, payment=None, **kwargs):
        # payment is required for cross-field validation (overpay check,
        # partner scoping) but isn't a model field on PaymentInvoiceLine
        # itself in this form, so it's passed in explicitly rather than
        # relying on an initial/hidden field the client could tamper with
        self.payment = payment
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None:
            raise ValidationError("Amount is required.")
        if amount <= 0:
            raise ValidationError("Amount must be greater than zero.")
        return amount

    def clean_invoice_move(self):
        move = self.cleaned_data.get('invoice_move')
        if move is None:
            raise ValidationError("Invoice is required.")
        if move.state != 'posted':
            raise ValidationError("Invoice is not in a postable state.")
        if self.payment and move.partner_id != self.payment.partner_id:
            # never trust the hidden field's value against the payment's
            # partner without re-checking server-side — client could
            # tamper with invoice_id to point at an unrelated partner
            raise ValidationError("Invoice does not belong to this payment's partner.")
        return move

    def clean(self):
        cleaned_data = super().clean()
        move = cleaned_data.get('invoice_move')
        amount = cleaned_data.get('amount')

        if move is None or amount is None:
            # field-level errors already raised above; nothing more to check
            return cleaned_data

        if self.payment is None:
            raise ValidationError("Payment context is required for reconciliation.")

        if self.payment.state != 'posted':
            raise ValidationError("Cannot reconcile. Payment is not in allowed state.")

        current_matched = move.get_already_matched_amount(self.payment)
        potential_total_match = current_matched + amount

        if potential_total_match > move.amount_total:
            raise ValidationError(
                f"Cannot overpay. Total would be {potential_total_match}, "
                f"but invoice is {move.amount_total}"
            )

        cleaned_data['current_matched'] = current_matched
        return cleaned_data


class ReconcileLinesForm(forms.Form):
    debit_line_id = forms.IntegerField(widget=forms.HiddenInput())
    credit_line_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= 0:
            raise ValidationError("Reconciliation amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        debit_line_id = cleaned_data.get('debit_line_id')
        credit_line_id = cleaned_data.get('credit_line_id')
        amount = cleaned_data.get('amount')

        if not debit_line_id or not credit_line_id or not amount:
            return cleaned_data

        # 1. Fetch lines securely from DB
        try:
            debit_line = AccountMoveLine.objects.select_related('move', 'account').get(pk=debit_line_id)
            credit_line = AccountMoveLine.objects.select_related('move', 'account').get(pk=credit_line_id)
        except AccountMoveLine.DoesNotExist:
            raise ValidationError("One or both selected lines do not exist.")

        # 2. Structural Ledger Rules
        if debit_line.debit <= 0 or credit_line.credit <= 0:
            raise ValidationError("Reconciliation requires one debit line and one credit line.")

        if debit_line.account_id != credit_line.account_id:
            raise ValidationError("Both lines must share the exact same GL account.")

        if debit_line.move.company_id != credit_line.move.company_id:
            raise ValidationError("Cannot reconcile lines across different companies.")

        if debit_line.move.state != 'posted' or credit_line.move.state != 'posted':
            raise ValidationError("Both journal moves must be posted prior to reconciliation.")

        if debit_line.partner_id != credit_line.partner_id:
            raise ValidationError("Cannot reconcile lines belonging to different partners.")

        # 3. Dynamic Residual Capacity Checks (using _remaining_balance_queryset)
        debit_residual = debit_line.get_remaining_balance()
        credit_residual = credit_line.get_remaining_balance()

        if amount > debit_residual:
            raise ValidationError(
                f"Amount exceeds debit line remaining balance ({debit_residual})."
            )

        if amount > credit_residual:
            raise ValidationError(
                f"Amount exceeds credit line remaining balance ({credit_residual})."
            )

        cleaned_data['debit_line'] = debit_line
        cleaned_data['credit_line'] = credit_line
        return cleaned_data