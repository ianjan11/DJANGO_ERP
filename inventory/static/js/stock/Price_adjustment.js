(function () {

  const FORM_SELECTOR = '#adjust-price-form';
  const INVALID_CLASS = 'is-invalid';

  // ── Helpers ───────────────────────────────────────────────

  function getField(formEl, id) {
    return formEl.querySelector('#' + id);
  }

  function getSubmitButton(form) {
    // #adjust-price-btn is a type="button" with hx-post (not a native
    // submit control), so it must be matched explicitly.
    return form.querySelector(
      '#adjust-price-btn, button[type="submit"], input[type="submit"]'
    );
  }

  function showError(errorBox, message) {
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.style.display = 'block';
  }

  function hideError(errorBox) {
    if (!errorBox) return;
    errorBox.style.display = 'none';
  }

  function markInvalid(field) {
    if (field) field.classList.add(INVALID_CLASS);
  }

  function clearInvalid(field) {
    if (field) field.classList.remove(INVALID_CLASS);
  }

  function clearAllInvalid(form) {
    clearInvalid(getField(form, 'start-date'));
    clearInvalid(getField(form, 'end-date'));
    clearInvalid(getField(form, 'cost-change'));
    clearInvalid(getField(form, 'price-change'));
  }

  function setSubmitDisabled(form, disabled) {
    const btn = getSubmitButton(form);
    if (btn) btn.disabled = disabled;
  }

  // ── Validation ────────────────────────────────────────────

  function validateDate(form, options) {
    const silent = options && options.silent;
    const startDate = getField(form, 'start-date');
    const endDate   = getField(form, 'end-date');
    const errorBox  = getField(form, 'errorbox');

    // start date field must exist — if not in DOM nothing to validate
    if (!startDate) return true;

    // start date is always required on this form regardless of whether
    // the price input is present
    if (!startDate.value) {
      if (!silent) {
        markInvalid(startDate);
        showError(errorBox, 'Start date is required. Every price must have an effective date for audit purposes.');
      }
      setSubmitDisabled(form, true);
      return false;
    }

    // only validate end date vs start date when end date has a value —
    // empty end date = open-ended price = valid in Odoo
    if (endDate && endDate.value && startDate.value > endDate.value) {
      if (!silent) {
        markInvalid(endDate);
        showError(errorBox, 'End date must be after start date.');
      }
      setSubmitDisabled(form, true);
      return false;
    }

    return true;
  }

  function validatePrice(form, options) {
    const silent = options && options.silent;
    const cost  = getField(form, 'cost-change');
    const price = getField(form, 'price-change');
    const errorBox = getField(form, 'errorbox');

    // field genuinely isn't part of this form — nothing to validate
    if (!price) return true;

    if (!price.value) {
      if (!silent) {
        markInvalid(price);
        showError(errorBox, 'Product price is required.');
      }
      setSubmitDisabled(form, true);
      return false;
    }

    if (!cost) return true;

    if (!cost.value) {
      if (!silent) {
        markInvalid(cost);
        showError(errorBox, 'Product cost is required.');
      }
      setSubmitDisabled(form, true);
      return false;
    }

    if (parseFloat(cost.value) > parseFloat(price.value)) {
      if (!silent) {
        markInvalid(cost);
        showError(errorBox, 'Product cost must be lower than new price.');
      }
      setSubmitDisabled(form, true);
      return false;
    }

    return true;
  }

  // Combines both checks into a single pass/fail so callers never have to
  // reason about ordering or which validator "owns" the error box.
  // Pass {silent: true} to update the disabled state without surfacing
  // error text/red borders — used on initial load so an empty form
  // doesn't greet the user with validation errors.
  function validateForm(form, options) {
    const silent = options && options.silent;
    const errorBox = getField(form, 'errorbox');

    clearAllInvalid(form);

    const priceOk = validatePrice(form, { silent });
    const dateOk  = validateDate(form, { silent });

    if (priceOk && dateOk) {
      hideError(errorBox);
      setSubmitDisabled(form, false);
      return true;
    }

    if (silent) {
      hideError(errorBox);
    }

    return false;
  }

  // ── Init (initial disabled state) ────────────────────────

  function initForm(form) {
    validateForm(form, { silent: true });
  }

  function initAllForms(root) {
    (root || document).querySelectorAll(FORM_SELECTOR).forEach(initForm);
  }

  // ── Event delegation on document ─────────────────────────
  // All listeners are on document — stable across HTMX swaps.
  // Each handler walks up to the form and checks it is the
  // correct form before acting. This allows external scripts
  // to independently listen for the same events.

  document.addEventListener('DOMContentLoaded', function () {
    initAllForms(document);
  });

  // Re-init whenever HTMX swaps in a new copy of the form.
  document.addEventListener('htmx:afterSwap', function (e) {
    const target = e.target;
    if (!target || !target.querySelectorAll) return;
    if (target.matches && target.matches(FORM_SELECTOR)) {
      initForm(target);
    }
    initAllForms(target);
  });

  // Real-time date validation when either date changes.
  document.addEventListener('change', function (e) {
    if (e.target.matches('#start-date, #end-date')) {
      const form = e.target.closest(FORM_SELECTOR);
      if (!form) return;
      validateForm(form);
    }
  });

  // Real-time price validation when either cost or price changes.
  document.addEventListener('change', function (e) {
    if (e.target.matches('#cost-change, #price-change')) {
      const form = e.target.closest(FORM_SELECTOR);
      if (!form) return;
      validateForm(form);
    }
  });

  // Block submission if validation fails (defense-in-depth;
  // the submit button is also disabled while invalid).
  // Covers a real native form submit, if one is ever used.
  document.addEventListener('submit', function (e) {
    const form = e.target.closest(FORM_SELECTOR);
    if (!form) return;
    if (!validateForm(form)) {
      e.preventDefault();
      const errorBox = getField(form, 'errorbox');
      if (errorBox) errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

  // #adjust-price-btn is type="button" with hx-post — it never fires a
  // native 'submit' event, so HTMX's own pre-request hook is used instead.
  // htmx:confirm fires before the request is issued and is cancelable.
  document.addEventListener('htmx:confirm', function (e) {
    const trigger = e.detail && e.detail.elt;
    if (!trigger || trigger.id !== 'adjust-price-btn') return;

    const form = trigger.closest(FORM_SELECTOR) || document.querySelector(FORM_SELECTOR);
    if (!form) return;

    if (!validateForm(form)) {
      e.preventDefault(); // cancels the HTMX request
      const errorBox = getField(form, 'errorbox');
      if (errorBox) errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

})();