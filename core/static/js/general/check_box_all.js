(function () {
    // Delegated checkbox behavior for any table marked [data-checkbox-table].
    // Header checkbox:  [data-select-all]
    // Row checkboxes:   [data-select-row]
    // Works for any number of such tables on the page, and survives
    // htmx swapping <tbody> content since the listener lives on document.

    function getTable(el) {
        return el.closest('[data-checkbox-table]');
    }

    function getRowCheckboxes(table) {
        return table.querySelectorAll('[data-select-row]');
    }

    function syncSelectAllState(table) {
        const selectAll = table.querySelector('[data-select-all]');
        if (!selectAll) return;

        const rows = getRowCheckboxes(table);
        if (rows.length === 0) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
            return;
        }

        let checkedCount = 0;
        rows.forEach(cb => { if (cb.checked) checkedCount++; });

        selectAll.checked = checkedCount === rows.length;
        selectAll.indeterminate = checkedCount > 0 && checkedCount < rows.length;
    }

    document.addEventListener('change', function (e) {
        const target = e.target;

        if (target.matches('[data-select-all]')) {
            const table = getTable(target);
            if (!table) return;
            getRowCheckboxes(table).forEach(cb => { cb.checked = target.checked; });
            return;
        }

        if (target.matches('[data-select-row]')) {
            const table = getTable(target);
            if (!table) return;
            syncSelectAllState(table);
        }
    });

    // Re-sync select-all state after htmx swaps in new rows
    // (e.g. after a filter/search reloads the tbody).
    document.addEventListener('htmx:afterSwap', function (e) {
        e.target.querySelectorAll('[data-checkbox-table]').forEach(syncSelectAllState);
        if (e.target.matches && e.target.matches('[data-checkbox-table]')) {
            syncSelectAllState(e.target);
        }
    });
})();
