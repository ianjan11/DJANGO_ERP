document.addEventListener("DOMContentLoaded", function () {

    // ── ELEMENTS ──────────────────────────────────────────────
    const form     = document.getElementById("product-form");
    const errorBox = document.getElementById("product-error");
    const modalEl  = document.getElementById("addProductModal");
    const tbody    = document.querySelector("#product-table tbody");

    if (!form || !modalEl) return;

    let modal = bootstrap.Modal.getInstance(modalEl);
    if (!modal) modal = new bootstrap.Modal(modalEl);

    // ── HELPERS ───────────────────────────────────────────────
    function getCSRFToken() {
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        return token ? token.value : "";
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.style.display = "block";
        errorBox.innerText = message;
    }

    function clearError() {
        if (!errorBox) return;
        errorBox.style.display = "none";
        errorBox.innerText = "";
    }

    function clearForm() {
        form.reset();
        clearError();
    }

    function getField(id) {
        const el = document.getElementById(id);
        return el ? el.value.trim() : "";
    }

    // ── BUILD FormData from the actual <form> element ─────────
    // Using FormData directly reads every <input>, <select>, <textarea>
    // inside the form — no manual field mapping needed.
    // Django reads this via request.POST exactly like a normal form submit.
    function buildFormData() {
        return new FormData(form);
    }

    // ── STATUS BADGE ──────────────────────────────────────────
    function stockBadge(stock) {
        stock = parseFloat(stock) || 0;
        if (stock <= 0)  return `<span class="po-badge cancelled"><span class="dot"></span>Out of Stock</span>`;
        if (stock <= 50) return `<span class="po-badge pending"><span class="dot"></span>Low</span>`;
        return                  `<span class="po-badge received"><span class="dot"></span>In Stock</span>`;
    }

    // ── INJECT ROW INTO TABLE ─────────────────────────────────
    function insertProductRow(product) {
        if (!tbody) return;

        const emptyRow = tbody.querySelector(".po-empty");
        if (emptyRow) emptyRow.closest("tr").remove();

        const price = parseFloat(product.default_price || 0).toFixed(2);

        const row = `
            <tr>
                <td style="font-weight:500;">${product.name}</td>
                <td><span style="font-family:'DM Mono',monospace; font-weight:600;">0</span></td>
                <td><span style="font-family:'DM Mono',monospace; color:var(--text-secondary);">0</span></td>
                <td><span class="po-total">${parseFloat(price).toLocaleString('en-US', {minimumFractionDigits:2})}</span></td>
                <td>${stockBadge(0)}</td>
                <td style="text-align:center;">
                    <a href="/stock/${product.id}/" class="po-action-btn">
                        <i class="bi bi-eye"></i> View
                    </a>
                </td>
            </tr>`;

        tbody.insertAdjacentHTML("afterbegin", row);
    }

    // ── MAIN SUBMIT ───────────────────────────────────────────
    async function submitProduct(action) {
        clearError();

        if (!getField("product-name")) {
            showError("Product name is required.");
            return;
        }
        if (!getField("product-sku")) {
            showError("Product SKU is required.");
            return;
        }

        const formData = buildFormData();

        try {
            const response = await fetch(CREATE_PRODUCT_URL, {
                method: "POST",
                headers: {
                    // Do NOT set Content-Type manually — the browser sets it
                    // automatically with the correct multipart boundary when
                    // using FormData. Setting it manually breaks parsing.
                    "X-CSRFToken": getCSRFToken(),
                },
                body: formData,
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                if (data.errors) {
                    const messages = Object.entries(data.errors)
                        .map(([field, err]) => {
                            const label = field
                                .replace(/_/g, ' ')
                                .replace(/\b\w/g, l => l.toUpperCase());
                            return `${label}: ${Array.isArray(err) ? err.join(", ") : err}`;
                        })
                        .join(" · ");
                    showError(messages);
                } else {
                    showError(data.error || "Product creation failed.");
                }
                return;
            }

            insertProductRow(data.product);

            if (action === "save") {
                modal.hide();
                clearForm();
            } else {
                // Save & Add Another — keep modal open, reset form, refocus
                clearForm();
                const nameField = document.getElementById("product-name");
                if (nameField) nameField.focus();
            }

        } catch (err) {
            console.error("Product creation error:", err);
            showError("An unexpected error occurred. Please try again.");
        }
    }

    // ── BUTTON HANDLERS ───────────────────────────────────────
    const saveBtn = document.getElementById("add-product-btn");
    if (saveBtn) {
        saveBtn.addEventListener("click", (e) => {
            e.preventDefault();
            submitProduct("save");
        });
    }

    const saveAnotherBtn = document.getElementById("add-product-add-another-btn");
    if (saveAnotherBtn) {
        saveAnotherBtn.addEventListener("click", (e) => {
            e.preventDefault();
            submitProduct("save-add-another");
        });
    }

    // Clear form and errors when modal is closed
    modalEl.addEventListener("hidden.bs.modal", () => {
        clearForm();
    });

});