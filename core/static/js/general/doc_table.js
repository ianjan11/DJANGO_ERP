/* doc-table.js: Filters dropdown + search behaviour for list toolbars.
   Load once in the base template (after htmx). Safe across HTMX swaps. */
(function () {
  'use strict';
  if (window.__docTableInit) return;
  window.__docTableInit = true;

  var restore = { search: false, filters: false };

  // ── active-filter count on the Filters button ──────────────
  function updateCounts() {
    document.querySelectorAll('.doc-filter').forEach(function (d) {
      var n = 0, seen = {};
      d.querySelectorAll('.doc-filter__panel [name]').forEach(function (el) {
        if (el.name === 'page' || el.disabled) return;
        if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked) n++; return; }
        if (el.value && !seen[el.name + el.value]) { seen[el.name + el.value] = 1; n++; }
      });
      var badge = d.querySelector('.doc-filter__count');
      if (badge) { badge.textContent = n; badge.hidden = n === 0; }
      var bar = d.closest('.doc-filterbar');
      var clr = bar && bar.querySelector('.doc-filterbar__clear');
      if (clr) clr.hidden = n === 0;
    });
  }

  // ── close on outside click / Escape ────────────────────────
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.doc-filter[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape')
      document.querySelectorAll('.doc-filter[open]').forEach(function (d) { d.removeAttribute('open'); });
  });

  // ── Clear all: reset every field in the form, then re-query ─
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.doc-filter__reset');
    if (!btn) return;
    var form = btn.closest('form');
    if (!form) return;
    form.querySelectorAll('[name]').forEach(function (el) {
      if (el.type === 'checkbox' || el.type === 'radio') el.checked = false;
      else if (el.tagName === 'SELECT') el.selectedIndex = 0;
      else el.value = '';
    });
    updateCounts();
    form.dispatchEvent(new Event('change', { bubbles: true }));
  });

  document.addEventListener('change', updateCounts);

  // ── the list re-renders on every change: keep UI state ─────
  document.body.addEventListener('htmx:beforeRequest', function () {
    var a = document.activeElement;
    restore.search = !!(a && a.classList && a.classList.contains('doc-search__input'));
    restore.filters = !!document.querySelector('.doc-filter[open]');
  });

  function afterSwap() {
    updateCounts();
    if (restore.filters) {
      var d = document.querySelector('.doc-filter');
      if (d) d.setAttribute('open', '');
    }
    if (restore.search) {
      var i = document.querySelector('.doc-search__input');
      if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
    }
    restore.search = restore.filters = false;
  }
  ['htmx:afterSettle', 'htmx:after:settle'].forEach(function (n) {
    document.body.addEventListener(n, afterSwap);
  });
  document.addEventListener('DOMContentLoaded', updateCounts);
})();