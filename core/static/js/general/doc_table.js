/* doc-table.js: behaviour for the toolbar search dropdown.
   Load once in your base template (after htmx). Safe across HTMX swaps. */
(function () {
  'use strict';
  if (window.__docTableInit) return;
  window.__docTableInit = true;

  var refocus = false;

  function input(d) { return d.querySelector('.doc-search__input'); }

  // Focus the input when the dropdown opens
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (d.classList && d.classList.contains('doc-search') && d.open) {
      var i = input(d);
      if (i) i.focus();
    }
  }, true);

  // Close on outside click (only if empty, so an applied search stays visible)
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.doc-search[open]').forEach(function (d) {
      var i = input(d);
      if (!d.contains(e.target) && !(i && i.value)) d.removeAttribute('open');
    });
  });

  // Escape closes
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.doc-search[open]').forEach(function (d) { d.removeAttribute('open'); });
  });

  // Clear button: empty the field and re-trigger the form's change
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.doc-search__clear');
    if (!btn) return;
    var d = btn.closest('.doc-search');
    var i = d && input(d);
    if (i) {
      i.value = '';
      i.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });

  // The list is re-rendered on every keystroke: remember focus and restore it
  document.body.addEventListener('htmx:beforeRequest', function () {
    var a = document.activeElement;
    refocus = !!(a && a.classList && a.classList.contains('doc-search__input'));
  });

  function restore() {
    if (!refocus) return;
    refocus = false;
    var i = document.querySelector('.doc-search__input');
    if (!i) return;
    var d = i.closest('.doc-search');
    d.setAttribute('open', '');
    i.focus();
    i.setSelectionRange(i.value.length, i.value.length);
  }
  document.body.addEventListener('htmx:afterSettle', restore);
})();