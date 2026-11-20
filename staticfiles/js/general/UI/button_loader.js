(function () {
    const loadingButtons = new WeakMap();

    function findLoadingButton(event) {
        const candidates = [
            event.target,
            event.detail && event.detail.elt,
            event.detail && event.detail.ctx && event.detail.ctx.sourceElement,
        ];

        for (const el of candidates) {
            if (el instanceof Element) {
                const btn = el.closest('button.js-loading-button');
                if (btn) return btn;
            }
        }
        return null;
    }

    function cleanupButton(btn) {
        const state = loadingButtons.get(btn);

        if (state && state.spinner && state.spinner.isConnected) {
            state.spinner.remove();
        }
        // Also remove any stray spinner added by a duplicate trigger
        btn.querySelectorAll(':scope > .spinner-border').forEach((el) => el.remove());

        const shouldStayDisabled = Boolean(state && state.wasDisabled);
        btn.disabled = shouldStayDisabled;
        if (!shouldStayDisabled) {
            btn.removeAttribute('disabled');
        }

        if (!state || state.wasAriaBusy === null) {
            btn.removeAttribute('aria-busy');
        } else {
            btn.setAttribute('aria-busy', state.wasAriaBusy);
        }

        btn.removeAttribute('data-old-value');
        btn.classList.remove('is-loading', 'disabled', 'htmx-request');
        loadingButtons.delete(btn);
    }

    document.addEventListener('htmx:before:request', function (event) {
        if (event.defaultPrevented) return;
        const btn = findLoadingButton(event);
        if (!btn) return;

        // If already tracked, clean stale state first so we don't stack spinners
        if (loadingButtons.has(btn)) {
            cleanupButton(btn);
        }

        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm me-2';
        spinner.setAttribute('role', 'status');
        spinner.setAttribute('aria-hidden', 'true');

        loadingButtons.set(btn, {
            spinner,
            wasDisabled: btn.hasAttribute('disabled') || btn.disabled,
            wasAriaBusy: btn.getAttribute('aria-busy'),
        });

        btn.disabled = true;
        btn.setAttribute('aria-busy', 'true');
        btn.prepend(spinner);
    });

    document.addEventListener('htmx:finally:request', function (event) {
        const btn = findLoadingButton(event);
        if (!btn) return;
        cleanupButton(btn);
    });

    // Extra guard if an error/abort event fires without finally or with a different target
    ['htmx:error', 'htmx:abort', 'htmx:response:error', 'htmx:send:error'].forEach((evtName) => {
        document.addEventListener(evtName, function (event) {
            const btn = findLoadingButton(event);
            if (btn) cleanupButton(btn);
        });
    });
})();