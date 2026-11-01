(function () {
    // Native focus fallback (plain selects/inputs)
    document.addEventListener("focusin", function (e) {
        const currency = e.target.closest("#currency-select");
        if (!currency) return;
        currency.dataset.oldValue = currency.value;
    });

    // Select2-aware capture (this field uses select2-widget)
    document.addEventListener("DOMContentLoaded", function () {
        if (typeof $ === "undefined") return;
        $(document).on("select2:opening", "#currency-select", function () {
            this.dataset.oldValue = this.value;
        });
    });
})();