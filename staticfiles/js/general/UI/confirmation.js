(function () {
    let pendingAction = null;

    function getEls() {
        return {
            confirmBox: document.getElementById("confirmBox"),
            confirmMessage: document.getElementById("confirmMessage"),
        };
    }

    function showConfirm(message, onAccept, onCancel) {
        const { confirmBox, confirmMessage } = getEls();
        if (!confirmBox) {
            console.warn("showConfirm: #confirmBox not found in DOM");
            return;
        }
        confirmMessage.textContent = message || "Are you sure?";
        confirmBox.style.display = "block";
        pendingAction = { accept: onAccept, cancel: onCancel || null };
    }

    function hideConfirm() {
        const { confirmBox } = getEls();
        if (confirmBox) confirmBox.style.display = "none";
        pendingAction = null;
    }

    window.showConfirm = showConfirm;
    window.hideConfirm = hideConfirm;

    // Delegated click handling (unchanged)
    document.addEventListener("click", function (event) {
        if (event.target.closest("#cancelConfirm")) {
            if (pendingAction?.cancel) pendingAction.cancel();
            hideConfirm();
            return;
        }

        if (event.target.closest("#acceptConfirm")) {
            if (pendingAction?.accept) pendingAction.accept();
            hideConfirm();
            return;
        }

        const btn = event.target.closest("[data-confirm]");
        if (btn && !btn.hasAttribute("hx-confirm")) {
            event.preventDefault();
            showConfirm(btn.dataset.confirm, function () {
                const action = btn.dataset.action;
                if (action && typeof window[action] === "function") {
                    window[action](btn);
                }
            });
        }
    });

    // htmx 4: confirm interception
    document.addEventListener("htmx:confirm", function (event) {
        const detail = event.detail || {};
        const ctx = detail.ctx;

        // v4 passes a request context (ctx); fall back to the older shape.
        // event.target is the element that triggered the request in both.
        const trigger = ctx?.sourceElement || detail.elt || event.target;
        const question = detail.question || ctx?.confirm || trigger?.getAttribute?.("hx-confirm");

        if (!question) return;
        event.preventDefault();

        const oldValue = trigger?.dataset?.oldValue;

        // No real change from the last confirmed value, so drop the request
        if (trigger && oldValue !== undefined && trigger.value === oldValue) {
            detail.dropRequest?.();
            return;
        }

        showConfirm(
            question,
            function () {
                if (trigger?.dataset) trigger.dataset.oldValue = trigger.value;
                // true = skip the confirm step so it doesn't re-trigger
                detail.issueRequest(true);
            },
            function () {
                detail.dropRequest?.();
                if (trigger && oldValue !== undefined) {
                    trigger.value = oldValue;
                    if (typeof $ !== "undefined" && $(trigger).data("select2")) {
                        $(trigger).trigger("change.select2");
                    }
                }
            }
        );
    });

    // htmx 4 event name
    document.addEventListener("htmx:after:swap", function (e) {
        if (!document.getElementById("confirmBox")) {
            console.warn("#confirmBox missing after swap on:", e.target);
        }
    });

    window.submitForm = function (btn) {
        const form = btn.closest("form");
        if (form) form.submit();
    };

    window.redirectToUrl = function (btn) {
        const url = btn.dataset.url;
        if (url) window.location.href = url;
    };
})();