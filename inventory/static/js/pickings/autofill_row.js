(function () {
  "use strict";

  const SEL = {
    row:       "tr.move-row",
    table:     "#move-lines",
    product:   'select[name$="-product"]',
    quantity:  'input[name$="-quantity"]',
    srcLoc:    'select[name$="-source_location"]',
    dstLoc:    'select[name$="-dest_location"]',
    lineLoc:   "select.line-location",
    headerLoc: "#id_source_location, #id_dest_location",
  };

  function getRow(el) { return el.closest(SEL.row); }

  const headerVal = (id) => document.getElementById(id)?.value || "";

  // Set a select's value and refresh select2's display without firing a
  // change event (change.select2 is namespaced, so it can't re-enter our
  // handlers or the row's htmx trigger)
  function setSelect(el, value) {
    if (!el || !value || el.value === String(value)) return;
    el.value = value;
    const $ = window.jQuery;
    if ($ && $(el).hasClass("select2-hidden-accessible")) $(el).trigger("change.select2");
  }

  function fillLocations(row, force) {
    if (row.dataset.locEdited && !force) return;
    const table = document.querySelector(SEL.table);
    const src = headerVal("id_source_location") || table?.dataset.defaultSource;
    const dst = headerVal("id_dest_location")   || table?.dataset.defaultDest;
    setSelect(row.querySelector(SEL.srcLoc), src);
    setSelect(row.querySelector(SEL.dstLoc), dst);
  }

  function onProductChange(select) {
    const row = getRow(select);
    if (!row || !row.isConnected) return;

    const quantityInput = row.querySelector(SEL.quantity);

    if (!select.value) {
      if (quantityInput) quantityInput.value = "";
      return;  // nothing to save
    }

    if (quantityInput && !quantityInput.value) quantityInput.value = "1";
    fillLocations(row);

    // Fire one clean autosave after the browser has painted the new values
    requestAnimationFrame(() => {
      if (row.isConnected) htmx.trigger(row, "save-row");
    });
  }

  function onLocationEdit(select) {
    const row = getRow(select);
    if (row) row.dataset.locEdited = "1";   // stop the header overwriting this row
  }

  function onHeaderLocationChange() {
    document.querySelectorAll(SEL.row).forEach((row) => fillLocations(row));
  }

  // ── Event delegation ──────────────────────────────────────────────────────
  document.addEventListener("change", (e) => {
    if (e.target.matches(SEL.product))   onProductChange(e.target);
    if (e.target.matches(SEL.lineLoc))   onLocationEdit(e.target);
    if (e.target.matches(SEL.headerLoc)) onHeaderLocationChange();
  });
})();