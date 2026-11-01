(function () {

  const FORM_SELECTOR = '#adjust-stock-form';
  const INVALID_CLASS = 'is-invalid';

  // ── Helpers ───────────────────────────────────────────────

  function getField(formEl, id) {
    return formEl.querySelector('#' + id);
  }

  function getSubmitButton(form) {
    // #adjust-stock-btn is a type="button" with hx-post (not a native
    // submit control), so it must be matched explicitly.
    return form.querySelector(
      '#adjust-stock-btn, button[type="submit"], input[type="submit"]'
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
    clearInvalid(getField(form, 'source-location-select'));
    clearInvalid(getField(form, 'destination-location-select'));
  }

  function setSubmitDisabled(form, disabled) {
    const btn = getSubmitButton(form);
    if (btn) btn.disabled = disabled;
  }

  // ── Show/hide + required wiring ──────────────────────────

  function toggleLocation(form) {
    const adjustType    = getField(form, 'adjustment-type');
    const destWrapper   = getField(form, 'destination-location-wrapper');
    const sourceWrapper = getField(form, 'source-location-wrapper');
    const destSelect    = getField(form, 'destination-location-select');
    const sourceSelect  = getField(form, 'source-location-select');

    if (!adjustType) return;

    const value = adjustType.value;

    if (value === 'TRANSFER') {
      if (destWrapper) destWrapper.style.display = '';
      if (destSelect) destSelect.setAttribute('required', 'required');
      if (sourceWrapper) sourceWrapper.style.display = '';
      if (sourceSelect) sourceSelect.setAttribute('required', 'required');
      return;
    }

    if (value === 'INCREASE') {
      if (destWrapper) destWrapper.style.display = '';
      if (destSelect) destSelect.setAttribute('required', 'required');
      if (sourceWrapper) sourceWrapper.style.display = 'none';
      if (sourceSelect) {
        sourceSelect.removeAttribute('required');
        sourceSelect.value = '';
      }
      return;
    }

    if (value === 'DECREASE') {
      if (destWrapper) destWrapper.style.display = 'none';
      if (destSelect) {
        destSelect.removeAttribute('required');
        destSelect.value = '';
      }
      if (sourceWrapper) sourceWrapper.style.display = '';
      if (sourceSelect) sourceSelect.setAttribute('required', 'required');
      return;
    }

    // No adjustment type selected (or an unrecognized value):
    // both fields start/stay hidden and non-required.
    if (destWrapper) destWrapper.style.display = 'none';
    if (destSelect) {
      destSelect.removeAttribute('required');
      destSelect.value = '';
    }
    if (sourceWrapper) sourceWrapper.style.display = 'none';
    if (sourceSelect) {
      sourceSelect.removeAttribute('required');
      sourceSelect.value = '';
    }
  }

  // ── Validation ────────────────────────────────────────────

  // Pass {silent: true} to update the disabled state without surfacing
  // error text/red borders — used on initial load so an empty form
  // doesn't greet the user with validation errors.
  function validateLocations(form, options) {
    const silent = options && options.silent;
    const adjustType   = getField(form, 'adjustment-type');
    const sourceSelect = getField(form, 'source-location-select');
    const destSelect   = getField(form, 'destination-location-select');
    const errorBox     = getField(form, 'errorbox');

    clearAllInvalid(form);

    // Centralizes the "invalid" exit path so every failure branch below
    // respects `silent` the same way, instead of repeating the same
    // if (!silent) {...} guard at every return site.
    function fail(message, invalidFields) {
      if (!silent) {
        (invalidFields || []).forEach(markInvalid);
        showError(errorBox, message);
      } else {
        hideError(errorBox);
      }
      setSubmitDisabled(form, true);
      return false;
    }

    if (!adjustType) {
      hideError(errorBox);
      setSubmitDisabled(form, false);
      return true;
    }

    const value = adjustType.value;

    if (!value) {
      return fail('Please select an adjustment type.');
    }

    if (value === 'TRANSFER') {
      if (!sourceSelect || !sourceSelect.value) {
        return fail('Source location is required for a transfer.', [sourceSelect]);
      }
      if (!destSelect || !destSelect.value) {
        return fail('Destination location is required for a transfer.', [destSelect]);
      }
      if (sourceSelect.value === destSelect.value) {
        return fail('Source and destination locations must be different.', [sourceSelect, destSelect]);
      }
    }

    if (value === 'INCREASE' && (!destSelect || !destSelect.value)) {
      return fail('Please select a destination location.', [destSelect]);
    }

    if (value === 'DECREASE' && (!sourceSelect || !sourceSelect.value)) {
      return fail('Please select a source location.', [sourceSelect]);
    }

    hideError(errorBox);
    setSubmitDisabled(form, false);
    return true;
  }

  // ── Init (initial hidden/disabled state) ─────────────────

  function initForm(form) {
    toggleLocation(form);
    validateLocations(form, { silent: true });
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

  // Toggle destination/source when adjustment type changes
  document.addEventListener('change', function (e) {
    if (e.target.matches('#adjustment-type')) {
      const form = e.target.closest(FORM_SELECTOR);
      if (!form) return;
      toggleLocation(form);
      validateLocations(form);    // re-validate immediately on type change
    }
  });

  // Real-time location validation when either select changes
  document.addEventListener('change', function (e) {
    if (e.target.matches('#source-location-select, #destination-location-select')) {
      const form = e.target.closest(FORM_SELECTOR);
      if (!form) return;
      validateLocations(form);
    }
  });

  // Block submission if validation fails (defense-in-depth;
  // the submit button is also disabled while invalid).
  // Covers a real native form submit, if one is ever used.
  document.addEventListener('submit', function (e) {
    const form = e.target.closest(FORM_SELECTOR);
    if (!form) return;
    if (!validateLocations(form)) {
      e.preventDefault();
      const errorBox = getField(form, 'errorbox');
      if (errorBox) errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

  // #adjust-stock-btn is type="button" with hx-post — it never fires a
  // native 'submit' event, so HTMX's own pre-request hook is used instead.
  // htmx:confirm fires before the request is issued and is cancelable.
  document.addEventListener('htmx:confirm', function (e) {
    const trigger = e.detail && e.detail.elt;
    if (!trigger || trigger.id !== 'adjust-stock-btn') return;

    const form = trigger.closest(FORM_SELECTOR) || document.querySelector(FORM_SELECTOR);
    if (!form) return;

    if (!validateLocations(form)) {
      e.preventDefault(); // cancels the HTMX request
      const errorBox = getField(form, 'errorbox');
      if (errorBox) errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

})();