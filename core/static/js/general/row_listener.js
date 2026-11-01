/**
 * Global row listener for htmx item rows.
 *
 * Each <tr> declares its type with data-row-type="invoice|order|purchase|journal|stock_move".
 * Use in hx-trigger:
 *   hx-trigger="save-row, change[rowReady(event, false)], keyup[rowReady(event, true)] changed delay:600ms"
 *
 * To add a new row type, add one entry to ROW_CONFIGS.
 */
(function () {
    const LINE_CONFIG = {
        changeFields: ['product', 'quantity', 'price_unit', 'discount_percent',
                       'taxes', 'account', 'product_uom', 'description'],
        typingFields: ['quantity', 'price_unit', 'discount_percent', 'description'],
        required: ['product', 'quantity'],          // let the server fill the rest
        requiredTyping: [],
        anyOf: [],
    };

    const ROW_CONFIGS = {
        invoice:  LINE_CONFIG,
        order:    LINE_CONFIG,
        purchase: LINE_CONFIG,

        journal: {
            changeFields: ['account', 'partner', 'memo', 'debit', 'credit'],
            typingFields: ['memo', 'debit', 'credit'],
            required: ['account'],
            requiredTyping: [],
            anyOf: [['debit', 'credit']],   // need a debit or a credit
        },

        stock_move: {
            changeFields: ['product', 'quantity', 'product_uom', 'source_location', 'dest_location'],
            typingFields: ['quantity'],
            required: ['product', 'quantity'],      // locations fall back to header if blank
            requiredTyping: [],
            anyOf: [],
        },
    };

    function fieldValue(row, field) {
        const el = row.querySelector(`[name$="-${field}"]`);
        return (el?.value ?? '').trim();
    }

    // A debit/credit of "0" or "0.00" shouldn't count as filled
    function isFilled(v) {
        return v !== '' && !(/^0+(\.0*)?$/.test(v));
    }

    window.rowReady = function (event, isTyping) {
        const target = event.target;
        if (!target || !target.name) return false;

        const row = target.closest('[data-row-type]');
        if (!row) return false;

        const cfg = ROW_CONFIGS[row.dataset.rowType];
        if (!cfg) return false;

        // Only react to the right fields for this event kind
        const fields = isTyping ? cfg.typingFields : cfg.changeFields;
        if (!fields.some(f => target.name.endsWith('-' + f))) return false;

        const required = isTyping ? cfg.required.concat(cfg.requiredTyping) : cfg.required;
        for (const f of required) {
            if (fieldValue(row, f) === '') return false;
        }

        for (const group of cfg.anyOf) {
            if (!group.some(f => isFilled(fieldValue(row, f)))) return false;
        }

        return true;
    };

    // Backwards compatibility with existing templates
    window.invoiceRowReady = window.rowReady;
    window.moveRowReady = window.rowReady;
})();