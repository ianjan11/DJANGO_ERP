(function () {
  // 1. Enable global view transitions
  htmx.config.globalViewTransitions = true;

  // 2. Intercept deletion requests before they swap out
  document.body.addEventListener('htmx:before:swap', function (e) {
    const target = e.detail.target;

    // HTMX 4/Fetch API response properties:
    // - Status code: e.detail.response.status
    // - Response string: e.detail.serverResponse
    const status = e.detail.response ? e.detail.response.status : 200;
    const responseText = e.detail.serverResponse || '';
    const isEmpty = responseText.trim() === '';

    // If backend returns 204 No Content or empty 200 OK targeting a table row
    if (target && target.tagName === 'TR' && (status === 204 || (status === 200 && isEmpty))) {
      target.classList.add('htmx-swapping-transition');
    }
  });

  // 3. Entry animations for newly added rows
  document.body.addEventListener('htmx:after:settle', function () {
    const newRows = document.querySelectorAll('.new-invoice-row');
    newRows.forEach(row => {
      row.classList.add('htmx-added-row');
      row.addEventListener('animationend', () => {
        row.classList.remove('htmx-added-row', 'new-invoice-row');
      }, { once: true });
    });
  });

})();