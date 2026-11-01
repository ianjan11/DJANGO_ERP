/**
 * Partner Form Lifecycle & Error Controller
 */

const PARTNER_FIELD_LABELS = {
    name: "Partner Name",
    partner_type: "Partner Type",
    tax_id: "Tax ID",
    email: "Email Address",
    phone: "Phone Number",
    address: "Address",
    city: "City",
    country: "Country",
    payment_term: "Customer Payment Term",
    supplier_payment_term: "Supplier Payment Term",
    preferred_purchase_currency: "Preferred Currency",
    account_receivable: "Receivable Account",
    account_payable: "Payable Account",
    is_active: "Active Status",
};

// --- SUCCESS ---
document.body.addEventListener('PartnerCreatedSuccess', function () {
    const partnerForm = document.getElementById('partnerForm');
    const errorBox = document.getElementById('partner-errors');

    FormErrorHandler.reset(partnerForm, errorBox);
    FormErrorHandler.closeModal('partnerModal');
});

// --- FIELD VALIDATION FAILURES ---
function handlePartnerValidation(event) {
    const errors = event.detail?.errors || {};
    const partnerForm = document.getElementById('partnerForm');
    const errorBox = document.getElementById('partner-errors');

    // Fully clears previous inline/banner state before writing new ones
    FormErrorHandler.showValidationErrors(errors, partnerForm, errorBox, PARTNER_FIELD_LABELS);
}

document.body.addEventListener('PartnerFormValidationError', handlePartnerValidation);
document.body.addEventListener('PartnerValidationError', handlePartnerValidation);

// --- GENERAL / DUPLICATE FAILURES ---
document.body.addEventListener('PartnerDuplicateError', function (event) {
    const payload = event.detail || {};
    const partnerForm = document.getElementById('partnerForm');
    const errorBox = document.getElementById('partner-errors');

    if (payload.errors) {
        FormErrorHandler.showValidationErrors(payload.errors, partnerForm, errorBox, PARTNER_FIELD_LABELS);
    } else {
        const message = payload.message || "A partner with these details already exists.";
        FormErrorHandler.reset(partnerForm, errorBox);
        FormErrorHandler.showBannerError(message, errorBox);
    }
});

// --- REAL-TIME FIELD CLEARING ---
const partnerForm = document.getElementById('partnerForm');
if (partnerForm) {
    const errorBox = document.getElementById('partner-errors');
    const clearError = (e) => FormErrorHandler.handleFieldInteraction(e, errorBox);

    partnerForm.addEventListener('input', clearError);
    partnerForm.addEventListener('change', clearError);
}