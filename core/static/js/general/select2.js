function initSelect2(scope = document) {
    const $scope = $(scope);
    const $widgets = $scope.find('.select2-widget').add($scope.filter('.select2-widget'));

    $widgets.each(function () {
        const $this = $(this);

        if ($this.hasClass('select2-hidden-accessible')) {
            return;
        }

        const $modal = $this.closest('.modal');

        $this.select2({
            placeholder: $this.data('placeholder') || 'Search...',
            allowClear: $this.data('allow-clear') !== undefined
                ? $this.data('allow-clear')
                : true,
            theme: 'odoo-line',
            width: '100%',
            dropdownParent: $modal.length ? $modal : $(document.body)
        });

        // Bind once per element (avoids duplicate handlers if re-initialized)
        $this.off('select2:select.sync select2:unselect.sync select2:clear.sync')
             .on('select2:select.sync select2:unselect.sync select2:clear.sync', function () {
                 this.dispatchEvent(new Event('change', { bubbles: true }));
             });
    });
}

function destroySelect2(scope) {
    const $scope = $(scope);
    $scope.find('.select2-widget').add($scope.filter('.select2-widget')).each(function () {
        if ($(this).hasClass('select2-hidden-accessible')) {
            $(this).select2('destroy');
        }
    });
}

document.addEventListener('htmx:before:cleanup', function (event) {
    destroySelect2(event.target);
});

// Per-element init (keeps existing behaviour)
document.addEventListener('htmx:after:init', function (event) {
    initSelect2(event.target);
});

// FIX: swapped-in markup without hx-* attributes never gets after:init,
// so re-scan after every swap. Idempotent thanks to the guard above.
document.addEventListener('htmx:after:swap', function () {
    initSelect2(document);
});
document.addEventListener('htmx:after:settle', function () {
    initSelect2(document);
});

$(function () {
    initSelect2();
});

const paymentModal = document.getElementById('paymentModal');
if (paymentModal) {
    paymentModal.addEventListener('shown.bs.modal', function () {
        initSelect2(paymentModal);
    });
}