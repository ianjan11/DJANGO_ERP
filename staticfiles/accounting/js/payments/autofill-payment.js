function autofillPayment(event) {
    const button = event.target.closest('.open-payment-modal');
    if (!button) return;

    const modal = document.getElementById('paymentModal');
    if (!modal) return;

    const {
        amount = '',
        memo = '',
        partnerId = '',
        type = '',
        invoiceId = '',   // <-- read the correct attribute
        currency = ''
    } = button.dataset;

    const setValue = (selector, value) => {
        const el = modal.querySelector(selector);
        if (!el) return;

        if ($(el).hasClass('select2-hidden-accessible')) {
            $(el).val(value).trigger('change');
        } else {
            el.value = value;
        }
    };

    // strip thousands separators in case the server still sends formatted numbers
    const cleanAmount = String(amount).replace(/,/g, '');

    setValue('[name="partner"]', String(partnerId));
    setValue('[name="currency"]', String(currency));
    setValue('[name="amount"]', cleanAmount);
    setValue('[name="memo"]', memo);
    setValue('[name="payment_type"]', type);
    setValue('[name="invoice_id"]', String(invoiceId));   // <-- use invoiceId, not id
    setValue('[name="date"]', new Date().toISOString().split('T')[0]);
}

document.addEventListener('click', autofillPayment);