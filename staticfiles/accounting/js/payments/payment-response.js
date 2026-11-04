/**
 * Payment Modal Lifecycle Event Controller
 */

const PAYMENT_FIELD_LABELS = {
    date: 'Date',
    journal: 'Journal',
    payment_method: 'Payment Method',
    payment_type: 'Payment Type',
    amount: 'Amount',
    memo: 'Memo / Reference',
    partner: 'Partner',
    currency: 'Currency',
};

// -------------------- SUCCESS --------------------
document.body.addEventListener('paymentSuccess', function () {
    const paymentForm = document.getElementById('paymentForm');
    const errorBox = document.getElementById('payment-errors');

    FormErrorHandler.reset(paymentForm, errorBox);
    FormErrorHandler.closeModal('paymentModal');
});

// -------------------- FIELD VALIDATION ERRORS --------------------
document.body.addEventListener('paymentValidationError', function (event) {
    const errors = event.detail?.errors || {};
    const paymentForm = document.getElementById('paymentForm');
    const errorBox = document.getElementById('payment-errors');

    FormErrorHandler.showValidationErrors(errors, paymentForm, errorBox, PAYMENT_FIELD_LABELS);
});

// -------------------- GENERAL / SYSTEM FAILURES --------------------
document.body.addEventListener('paymentFailed', function (event) {
    const payload = event.detail || {};
    const paymentForm = document.getElementById('paymentForm');
    const errorBox = document.getElementById('payment-errors');

    if (payload.errors) {
        // Fallback if backend sends field errors via paymentFailed
        FormErrorHandler.showValidationErrors(payload.errors, paymentForm, errorBox, PAYMENT_FIELD_LABELS);
    } else if (payload.message) {
        // General banner error (e.g., missing invoice, no company assigned)
        FormErrorHandler.showBannerError(payload.message, errorBox);
    }
});

// -------------------- CLEAR ERRORS ON INTERACTION --------------------
const paymentForm = document.getElementById('paymentForm');
if (paymentForm) {
    const errorBox = document.getElementById('payment-errors');
    const clearError = (e) => FormErrorHandler.handleFieldInteraction(e, errorBox);

    paymentForm.addEventListener('input', clearError);
    paymentForm.addEventListener('change', clearError);
}