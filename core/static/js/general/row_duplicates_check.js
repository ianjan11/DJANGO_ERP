(function () {
    // ─── Helpers ────────────────────────────────────────────────────

    const ROW_SELECTOR =
        'tr[id^="purchase-row-"], tr[id^="invoice-row-"], tr[id^="order-row-"]';

    function getRows() {
        return document.querySelectorAll(ROW_SELECTOR);
    }

    function isDeleted(row) {
        return row.querySelector('[name$="-DELETE"]')?.checked ?? false;
    }

    function getFieldValue(row, suffix) {
        return row.querySelector(`[name$="${suffix}"]`)?.value?.trim() ?? '';
    }

    function getTaxesValue(row) {
        const checkboxes = row.querySelectorAll('.item-taxes');
        if (!checkboxes.length) return '';

        return Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value)
            .sort()
            .join(',');
    }

    function getRowKey(row) {
        const product = getFieldValue(row, '-product');
        const price   = getFieldValue(row, '-price_unit');
        const taxes   = getTaxesValue(row);
        return `${product}|${price}|${taxes}`;
    }

    function isEmptyRow(row) {
        return !getFieldValue(row, '-product');
    }

    // ─── Core Check ─────────────────────────────────────────────────

    function checkDuplicateLines() {
        const rows = getRows();
        const keyCounts = {};

        rows.forEach(row => {
            if (isDeleted(row) || isEmptyRow(row)) return;
            const key = getRowKey(row);
            keyCounts[key] = (keyCounts[key] || 0) + 1;
        });

        document.querySelectorAll('.duplicate-warning').forEach(el => el.remove());

        rows.forEach(row => {
            if (isDeleted(row) || isEmptyRow(row)) return;

            const key = getRowKey(row);
            if (keyCounts[key] > 1) {
                const productTd = row.querySelector('[name$="-product"]')?.closest('td');
                if (!productTd) return;

                const warn = document.createElement('div');
                warn.className = 'duplicate-warning';
                warn.style.cssText = [
                    'color: orange',
                    'font-size: 0.82em',
                    'margin-top: 4px',
                    'display: flex',
                    'align-items: center',
                    'gap: 4px',
                ].join(';');
                warn.textContent = '⚠ Duplicate line (same product, price & taxes) — consider merging';
                productTd.appendChild(warn);
            }
        });
    }

    // Debounced, so several swaps or partials in one response run one check
    let timer = null;
    function scheduleCheck(delay = 0) {
        clearTimeout(timer);
        timer = setTimeout(checkDuplicateLines, delay);
    }

    // ─── Event Listeners ────────────────────────────────────────────

    // Any field change inside a row (now covers purchase, invoice and order rows)
    document.addEventListener('change', function (e) {
        if (e.target.closest(ROW_SELECTOR)) {
            // Tax checkboxes update their hidden state a moment later
            scheduleCheck(e.target.classList.contains('item-taxes') ? 50 : 0);
        }
    });

    // htmx 4: no settle phase, so listen for after:swap. This also covers
    // added rows, replaced rows and deletes, so the click hack is gone.
    document.addEventListener('htmx:after:swap', function () {
        scheduleCheck();
    });

    // On page load (works whether the script runs before or after DOM ready)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => scheduleCheck());
    } else {
        scheduleCheck();
    }
})();