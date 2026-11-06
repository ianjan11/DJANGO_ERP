/* ============================================================
   TABS — behaviour for [data-tabs] containers
   tabs.js   (load once in base.html, with `defer`)

   - Event delegation on document: works for content swapped in by
     HTMX, no per-swap re-initialisation needed.
   - Clicking [data-tab="x"] shows [data-tab-panel="x"] inside the
     same [data-tabs] container.
   - If browser validation fails on a field inside a hidden panel,
     that panel is opened so the error is visible.
   - A tab button with data-error opens automatically on load/swap.
   ============================================================ */
(function () {
  'use strict';

  function activate(root, name) {
    root.querySelectorAll('[data-tab]').forEach(function (btn) {
      var on = btn.dataset.tab === name;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    root.querySelectorAll('[data-tab-panel]').forEach(function (panel) {
      panel.classList.toggle('active', panel.dataset.tabPanel === name);
    });
  }

  function openErrorTabs(scope) {
    (scope || document).querySelectorAll('[data-tabs]').forEach(function (root) {
      var err = root.querySelector('[data-tab][data-error]');
      if (err) activate(root, err.dataset.tab);
    });
  }

  // Tab click
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-tab]');
    if (!btn) return;
    var root = btn.closest('[data-tabs]');
    if (root) activate(root, btn.dataset.tab);
  });

  // Native validation failed inside a hidden panel -> reveal it
  document.addEventListener('invalid', function (e) {
    var panel = e.target.closest && e.target.closest('[data-tab-panel]');
    if (!panel) return;
    var root = panel.closest('[data-tabs]');
    if (root) activate(root, panel.dataset.tabPanel);
  }, true);

  // Initial page load + every HTMX swap
  document.addEventListener('DOMContentLoaded', function () { openErrorTabs(); });
  document.addEventListener('htmx:load', function (e) { openErrorTabs(e.target); });

  // Optional public API: Tabs.open(rootEl, 'name')
  window.Tabs = { open: activate };
})();
