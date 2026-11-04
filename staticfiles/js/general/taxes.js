// tax.js

// Update badge labels when checkbox changes
function updateTaxLabel(checkbox) {
  const wrapper = checkbox.closest('.tax-dropdown-wrapper');
  const label = wrapper.querySelector('.tax-selected-label');
  const checked = wrapper.querySelectorAll('.tax-dropdown-menu input[type="checkbox"]:checked');

  label.innerHTML = checked.length === 0
    ? '<span class="tax-placeholder">Taxes...</span>'
    : Array.from(checked)
        .map(cb => `<span class="tax-badge">${cb.closest('.tax-option').textContent.trim()}</span>`)
        .join('');

  // dispatch so htmx picks up the change
  wrapper.dispatchEvent(new Event('change', { bubbles: true }));
}



// close tax dropdown when clicking outside
document.addEventListener('click', function (e) {
  if (!e.target.closest('.tax-dropdown-wrapper')) {
    document.querySelectorAll('.tax-toggle:checked')
      .forEach(toggle => toggle.checked = false);
  }
});