function syncRowBtn() {
    const btn = document.getElementById('row-btn');
    const source = document.getElementById('partner-select');

    if (!btn || !source) return;

    btn.style.display = source.value ? 'inline-flex' : 'none';
}

// Initial page load
document.addEventListener('DOMContentLoaded', () => {
    syncRowBtn();

    $(document).on('change', '#partner-select', syncRowBtn);
});

// HTMX 4 swaps (CHANGED: 'htmx:afterSwap' -> 'htmx:after:swap')
document.body.addEventListener('htmx:after:swap', () => {
    syncRowBtn();
});

// HTMX 4 element loads (CHANGED: 'htmx:load' -> 'htmx:load:elt')
document.body.addEventListener('htmx:load:elt', () => {
    syncRowBtn();
});