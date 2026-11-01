(() => {
    let errorTimeout = null;

    // ============================================================
    // Helpers
    // ============================================================

    function getModal() {
        return document.getElementById("ReturnModal");
    }

    function getErrorBox() {
        return document.getElementById("form-error");
    }

    function getTableBody() {
        return document.getElementById("returns-items-body");
    }

    function getProductSelect() {
        return document.getElementById("product-select");
    }

    function getRows() {
        const tableBody = getTableBody();
        if (!tableBody) return [];
        return tableBody.querySelectorAll("tr[data-line-id]");
    }

    function hasRows() {
        return getRows().length > 0;
    }

    function rowExists(lineId) {
        const tableBody = getTableBody();
        if (!tableBody) return false;
        return !!tableBody.querySelector(`tr[data-line-id="${CSS.escape(String(lineId))}"]`);
    }

    // ============================================================
    // Error handling
    // ============================================================

    function showError(message) {
        const errorBox = getErrorBox();
        if (!errorBox) return;

        errorBox.textContent = message;
        errorBox.style.display = "block";

        if (errorTimeout) {
            clearTimeout(errorTimeout);
        }

        errorTimeout = setTimeout(() => {
            clearError();
        }, 5000);
    }

    function clearError() {
        const errorBox = getErrorBox();
        if (!errorBox) return;

        if (errorTimeout) {
            clearTimeout(errorTimeout);
            errorTimeout = null;
        }

        errorBox.textContent = "";
        errorBox.style.display = "none";
    }

    // ============================================================
    // Formatting
    // ============================================================

    function formatAmount(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return "0.00";
        return number.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    // ============================================================
    // Error response formatting
    // ============================================================

    function formatErrors(errors) {
        if (errors === null || errors === undefined) return "Unknown error";
        if (typeof errors === "string") return errors;

        if (Array.isArray(errors)) {
            return errors.map(entry => {
                if (entry && typeof entry === "object" && "line" in entry && "error" in entry) {
                    return `Line ${entry.line}: ${formatErrors(entry.error)}`;
                }
                return formatErrors(entry);
            }).join(" | ");
        }

        if (typeof errors === "object") {
            return Object.entries(errors).map(([field, messages]) => {
                if (Array.isArray(messages)) {
                    return `${field}: ${messages.join(", ")}`;
                }
                return `${field}: ${formatErrors(messages)}`;
            }).join(" | ");
        }

        return String(errors);
    }

    // ============================================================
    // Empty table
    // ============================================================

    function resetItemsTable() {
        const tableBody = getTableBody();
        if (!tableBody) return;

        tableBody.innerHTML = `
            <tr id="no-items-row">
                <td colspan="3" class="table-empty">
                    <div class="table-empty-icon">
                        <i class="bi bi-inbox"></i>
                    </div>
                    <div class="table-empty-title">
                        No products added yet
                    </div>
                    <div class="table-empty-desc">
                        Select a picking line above and click Add Line.
                    </div>
                </td>
            </tr>
        `;
    }

    // ============================================================
    // Reset form
    // ============================================================

    function resetReturnForm() {
        resetItemsTable();
        clearError();
        const productSelect = getProductSelect();
        if (productSelect) {
            productSelect.value = "";
        }
    }

    // ============================================================
    // Validate return quantity
    // ============================================================

    function validateReturnQuantity(input) {
        if (!input) return false;
        const value = Number(input.value);
        const max = Number(input.dataset.maxAmount);

        if (!Number.isFinite(value) || !Number.isFinite(max)) return false;
        if (value <= 0 || value > max) return false;
        return true;
    }

    // ============================================================
    // Add picking line
    // ============================================================

    document.addEventListener("click", function (e) {
        const addButton = e.target.closest("#add-product-btn");
        if (!addButton) return;

        const productSelect = getProductSelect();
        const tableBody = getTableBody();

        if (!productSelect || !tableBody) return;

        const option = productSelect.selectedOptions[0];
        if (!option || !option.value) {
            showError("Please select a picking line.");
            return;
        }

        const lineId = option.value;
        if (rowExists(lineId)) {
            showError("This picking line has already been added.");
            return;
        }

        const productName = option.dataset.productName || "Unknown product";
        const deliveredQty = Number(option.dataset.quantity || 0);
        const availableAmount = Number(option.dataset.availableQuantity || 0);
        const productId = option.dataset.productId || "";

        if (!Number.isFinite(availableAmount) || availableAmount <= 0) {
            showError(`${productName} has no remaining quantity available for return.`);
            return;
        }

        const noItemsRow = document.getElementById("no-items-row");
        if (noItemsRow) {
            noItemsRow.remove();
        }

        const row = document.createElement("tr");
        row.dataset.lineId = lineId;

        row.innerHTML = `
            <td>
                <strong>${productName}</strong>
                <input type="hidden" name="line_id_${lineId}" value="${lineId}">
                <input type="hidden" name="product_id_${lineId}" value="${productId}">
                <div class="text-muted small">Delivered: ${deliveredQty}</div>
            </td>

            <td class="col-right">
                <input
                    type="number"
                    name="return_qty_${lineId}"
                    class="form-control return-qty"
                    min="1"
                    max="${availableAmount}"
                    step="1"
                    value="${availableAmount.toFixed(2)}"
                    data-max-amount="${availableAmount}"
                    required
                >
                <small class="text-muted">Max: ${formatAmount(availableAmount)}</small>
            </td>

            <td class="col-center">
                <button type="button" class="btn btn-sm btn-danger remove-return-row">
                    Remove
                </button>
            </td>
        `;

        tableBody.appendChild(row);
        productSelect.value = "";
        clearError();
    }, true);

    // ============================================================
    // Remove picking line
    // ============================================================

    document.addEventListener("click", function (e) {
        const removeButton = e.target.closest(".remove-return-row");
        if (!removeButton) return;

        const row = removeButton.closest("tr");
        if (!row) return;

        row.remove();

        if (!hasRows()) {
            resetItemsTable();
        }

        clearError();
    }, true);

    // ============================================================
    // Return quantity input validation
    // ============================================================

    document.addEventListener("input", function (e) {
        const input = e.target.closest(".return-qty");
        if (!input) return;

        const max = Number(input.dataset.maxAmount);
        let value = Number(input.value);

        if (!Number.isFinite(value)) return;

        if (value < 0) {
            input.value = "0";
            return;
        }

        if (value > max) {
            input.value = max.toFixed(2);
            showError(`Return quantity cannot exceed ${formatAmount(max)}.`);
            return;
        }

        clearError();
    });

    // ============================================================
    // Validate all lines before HTMX request
    // ============================================================

    document.body.addEventListener("htmx:beforeRequest", function (e) {
        const modal = e.target.closest("#ReturnModal");
        if (!modal) return;

        if (!hasRows()) {
            e.preventDefault();
            showError("Add at least one line to return.");
            return;
        }

        let valid = true;
        getRows().forEach(row => {
            const input = row.querySelector(".return-qty");
            if (!validateReturnQuantity(input)) {
                valid = false;
            }
        });

        if (!valid) {
            e.preventDefault();
            showError("Please enter a valid return quantity for every line.");
            return;
        }

        clearError();
    });

    // ============================================================
    // HTMX response
    // ============================================================

    document.body.addEventListener("htmx:afterRequest", function (e) {
        const modal = e.target.closest("#ReturnModal");
        if (!modal) return;

        if (!e.detail.successful) {
            showError("An error occurred while processing the return.");
            return;
        }

        let data;
        try {
            data = JSON.parse(e.detail.xhr.responseText);
        } catch (error) {
            showError("Unexpected response from server.");
            return;
        }

        if (!data.success) {
            showError(formatErrors(data.errors));
            return;
        }

        if (typeof notify === "function") {
            notify(data.message || "Return processed successfully.", "success");
        }

        const modalElement = getModal();
        if (modalElement && window.bootstrap) {
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalElement);
            modalInstance.hide();
        }
    });

    // ============================================================
    // Reset when modal closes
    // ============================================================

    document.addEventListener("hidden.bs.modal", function (e) {
        if (e.target?.id !== "ReturnModal") return;
        resetReturnForm();
    });

})();