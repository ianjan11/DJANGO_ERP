(function () {
  if (window.__toolbarBound) return;          // htmx swaps/boosts can re-run inline scripts
  window.__toolbarBound = true;

  const FORM = 'form[data-toolbar]';
  const getForm = el => (el ? el.closest(FORM) : null);

  // One event the form listens for, whatever caused the change
  const fire = form => htmx.trigger(form, 'filters:changed');

  function setPreset(btn, form) {
    form.querySelectorAll('.date-select-preset').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const input = form.querySelector('.preset-input');
    if (input) input.value = btn.dataset.preset;
  }

  function syncToolbarVisuals(form) {
    if (!form) return;
    const searchInput = form.querySelector('.toolbar-search');
    const searchClear = form.querySelector('.toolbar-search-clear');
    const selects     = form.querySelectorAll('.toolbar-select');
    const clearAll    = form.querySelector('.toolbar-clear-btn');
    const targetDate  = form.querySelector('.date-select-input');
    const preset      = form.querySelector('.date-select-preset.active');

    const hasSearch = !!searchInput && searchInput.value.length > 0;
    const hasStatus = [...selects].some(s => s.value !== '');
    const hasDate   = !!targetDate && targetDate.value !== '';
    const hasPreset = !!preset;

    if (searchClear) searchClear.classList.toggle('is-visible', hasSearch);
    selects.forEach(s => s.classList.toggle('has-value', s.value !== ''));
    if (clearAll) clearAll.classList.toggle('is-visible', hasSearch || hasStatus || hasDate || hasPreset);
  }

  // Keep the visual state in sync while the user interacts
  ['input', 'change'].forEach(evt =>
    document.addEventListener(evt, e => syncToolbarVisuals(getForm(e.target))));

  document.addEventListener('click', e => {
    // Preset buttons
    const presetBtn = e.target.closest('.date-select-preset');
    if (presetBtn) {
      const form = getForm(presetBtn);
      if (!form) return;
      setPreset(presetBtn, form);
      const date = form.querySelector('.date-select-input');
      if (date) date.value = '';
      syncToolbarVisuals(form);
      fire(form);
      return;
    }

    // Clear search ×
    const clearSearch = e.target.closest('.toolbar-search-clear');
    if (clearSearch) {
      const form = getForm(clearSearch);
      const input = form && form.querySelector('.toolbar-search');
      if (input) {
        input.value = '';
        input.focus();
        syncToolbarVisuals(form);
        fire(form);
      }
      return;
    }

    // Clear all
    const clearAll = e.target.closest('.toolbar-clear-btn');
    if (clearAll) {
      const form = getForm(clearAll);
      if (!form) return;
      form.querySelectorAll('.toolbar-search, .date-select-input, .preset-input, .toolbar-select')
          .forEach(el => (el.value = ''));
      form.querySelectorAll('.date-select-preset').forEach(b => b.classList.remove('active'));
      syncToolbarVisuals(form);
      fire(form);
    }
  });

  const initAll = () => document.querySelectorAll(FORM).forEach(syncToolbarVisuals);

  // htmx 4 event names (colon-separated); settle events no longer exist
  document.addEventListener('htmx:after:init', initAll);
  document.addEventListener('htmx:after:swap', initAll);
  document.addEventListener('htmx:after:history:restore', initAll);
  window.addEventListener('DOMContentLoaded', initAll);
})();