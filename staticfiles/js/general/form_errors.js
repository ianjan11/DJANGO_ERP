/**
 * Shared Form Validation & UI Error Handler
 */
const FormErrorHandler = {
    /**
     * Clears field inline errors and resets the error banner summary.
     */
    reset(form, errorBox) {
        if (form) {
            form.querySelectorAll('.is-invalid')
                .forEach((el) => el.classList.remove('is-invalid'));
            form.querySelectorAll('.invalid-feedback[data-dynamic]')
                .forEach((el) => el.remove());
        }
        if (errorBox) {
            errorBox.classList.add('d-none');
            errorBox.innerHTML = '';
        }
    },

    /**
     * Highlights inputs with inline error messages and populates a summary banner.
     */
    showValidationErrors(errors, form, errorBox, fieldLabels = {}) {
        // 1. Full reset of previous states
        this.reset(form, errorBox);

        // 2. Render Per-Field Inline Errors
        Object.entries(errors).forEach(([field, messages]) => {
            const input =
                form?.querySelector(`#id_${field}`) ||
                form?.querySelector(`[name="${field}"]`) ||
                document.getElementById(`id_${field}`) ||
                document.querySelector(`[name="${field}"]`);

            if (!input) return;

            // Defensive check: remove existing dynamic feedback attached directly to this input
            const parent = input.parentElement;
            if (parent) {
                parent.querySelectorAll('.invalid-feedback[data-dynamic]').forEach(el => el.remove());
            }

            input.classList.add('is-invalid');

            const feedback = document.createElement('div');
            feedback.className = 'invalid-feedback';
            feedback.dataset.dynamic = 'true';
            feedback.textContent = Array.isArray(messages)
                ? messages.join(', ')
                : String(messages);

            input.insertAdjacentElement('afterend', feedback);
        });

        // 3. Render Summary Error Banner
        if (!errorBox) return;

        const listItems = Object.entries(errors).flatMap(([field, messages]) => {
            const label = fieldLabels[field] || field;
            const messageList = Array.isArray(messages) ? messages : [messages];

            return messageList.map(
                (msg) => `<li data-field="${field}">${label !== field ? `${label}: ` : ''}${msg}</li>`
            );
        });

        if (listItems.length > 0) {
            errorBox.innerHTML = `
                <div class="fw-bold text-danger">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    Please correct the errors below:
                </div>
                <ul class="mb-0 mt-1 ps-4">
                    ${listItems.join('')}
                </ul>
            `;
            errorBox.classList.remove('d-none');
        }
    },

    /**
     * Displays non-field or duplicate/backend error banner messages.
     */
    showBannerError(message, errorBox) {
        if (!errorBox) return;

        errorBox.innerHTML = '';

        const displayMsg = typeof message === 'object' ? JSON.stringify(message) : message;

        errorBox.innerHTML = `
            <div class="fw-bold text-danger">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                ${displayMsg}
            </div>
        `;
        errorBox.classList.remove('d-none');
    },

    /**
     * Safely closes a Bootstrap Modal and resets form focus.
     */
    closeModal(modalId) {
        document.activeElement?.blur();
        const modalEl = document.getElementById(modalId);
        if (!modalEl) return;

        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        modal.hide();
    },

    /**
     * Real-time field interaction handler to clear errors on user typing/selecting.
     */
    handleFieldInteraction(event, errorBox) {
        const target = event.target;
        if (!target || !target.name) return;

        if (target.classList.contains('is-invalid')) {
            target.classList.remove('is-invalid');

            // Clean up sibling invalid feedback elements
            let sibling = target.nextElementSibling;
            while (sibling) {
                if (sibling.classList.contains('invalid-feedback') && sibling.dataset.dynamic) {
                    sibling.remove();
                    break;
                }
                sibling = sibling.nextElementSibling;
            }
        }

        // Remove item from summary banner
        if (errorBox) {
            const item = errorBox.querySelector(`li[data-field="${target.name}"]`);
            if (item) item.remove();

            if (errorBox.querySelectorAll('li').length === 0) {
                errorBox.classList.add('d-none');
                errorBox.innerHTML = '';
            }
        }
    }
};