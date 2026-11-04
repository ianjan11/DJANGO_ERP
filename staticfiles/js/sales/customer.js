document.addEventListener('customerCreated', (e) => {
    const { id, name } = e.detail;

    // add to select
    const select = document.getElementById('customer-select');
    const option = new Option(name, id, true, true);
    select.appendChild(option);
    if (typeof $ !== 'undefined') $(select).trigger('change');

    // ✅ properly close modal and clean up backdrop
    const modalEl = document.getElementById('customerModal');
    const modal = bootstrap.Modal.getInstance(modalEl);

    if (modal) {
        modal.hide();
    }

    // ✅ force cleanup backdrop
    modalEl.addEventListener('hidden.bs.modal', () => {
        document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }, { once: true });  // ✅ once:true so it doesn't stack
});