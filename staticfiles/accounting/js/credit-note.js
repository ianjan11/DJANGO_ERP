(() => {
    let errorTimeout = null;


    // ============================================================
    // Helpers
    // ============================================================

    function getModal() {
        return document.getElementById("CreditNoteModal");
    }


    function getErrorBox() {
        return document.getElementById("form-error");
    }


    function getTableBody() {
        return document.getElementById("credit-items-body");
    }


    function getProductSelect() {
        return document.getElementById("product-select");
    }


    function getRows() {
        const tableBody = getTableBody();

        if (!tableBody) {
            return [];
        }

        return tableBody.querySelectorAll(
            "tr[data-line-id]"
        );
    }


    function hasRows() {
        return getRows().length > 0;
    }


    function rowExists(lineId) {
        const tableBody = getTableBody();

        if (!tableBody) {
            return false;
        }

        return !!tableBody.querySelector(
            `tr[data-line-id="${CSS.escape(String(lineId))}"]`
        );
    }


    // ============================================================
    // Error handling
    // ============================================================

    function showError(message) {
        const errorBox = getErrorBox();

        if (!errorBox) {
            return;
        }

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

        if (!errorBox) {
            return;
        }

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

        if (!Number.isFinite(number)) {
            return "0.00";
        }

        return number.toLocaleString(
            undefined,
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }
        );
    }


    // ============================================================
    // Error response formatting
    // ============================================================

    function formatErrors(errors) {

        if (
            errors === null ||
            errors === undefined
        ) {
            return "Unknown error";
        }


        if (typeof errors === "string") {
            return errors;
        }


        if (Array.isArray(errors)) {

            return errors
                .map(entry => {

                    if (
                        entry &&
                        typeof entry === "object" &&
                        "line" in entry &&
                        "error" in entry
                    ) {
                        return (
                            `Line ${entry.line}: ` +
                            formatErrors(entry.error)
                        );
                    }

                    return formatErrors(entry);
                })
                .join(" | ");
        }


        if (typeof errors === "object") {

            return Object.entries(errors)
                .map(([field, messages]) => {

                    if (Array.isArray(messages)) {
                        return (
                            `${field}: ` +
                            messages.join(", ")
                        );
                    }

                    return (
                        `${field}: ` +
                        formatErrors(messages)
                    );
                })
                .join(" | ");
        }


        return String(errors);
    }


    // ============================================================
    // Empty table
    // ============================================================

    function resetItemsTable() {
        const tableBody = getTableBody();

        if (!tableBody) {
            return;
        }

        tableBody.innerHTML = `
            <tr id="no-items-row">
                <td colspan="5" class="table-empty">
                    <div class="table-empty-icon">
                        <i class="bi bi-inbox"></i>
                    </div>

                    <div class="table-empty-title">
                        No products added yet
                    </div>

                    <div class="table-empty-desc">
                        Select an invoice line above and click
                        Add Line.
                    </div>
                </td>
            </tr>
        `;
    }


    // ============================================================
    // Reset form
    // ============================================================

    function resetCreditForm() {

        resetItemsTable();

        clearError();

        const productSelect = getProductSelect();

        if (productSelect) {
            productSelect.value = "";
        }
    }


    // ============================================================
    // Validate credit amount
    // ============================================================

    function validateCreditAmount(input) {

        if (!input) {
            return false;
        }

        const value = Number(input.value);
        const max = Number(input.dataset.maxAmount);

        if (!Number.isFinite(value)) {
            return false;
        }

        if (!Number.isFinite(max)) {
            return false;
        }

        if (value <= 0) {
            return false;
        }

        if (value > max) {
            return false;
        }

        return true;
    }


    // ============================================================
    // Add invoice line
    // ============================================================

    document.addEventListener(
        "click",
        function (e) {

            const addButton =
                e.target.closest("#add-product-btn");

            if (!addButton) {
                return;
            }


            const productSelect =
                getProductSelect();

            const tableBody =
                getTableBody();


            if (
                !productSelect ||
                !tableBody
            ) {
                return;
            }


            const option =
                productSelect.selectedOptions[0];


            if (
                !option ||
                !option.value
            ) {
                showError(
                    "Please select an invoice line."
                );

                return;
            }


            // ----------------------------------------------------
            // Invoice line identity
            // ----------------------------------------------------

            const lineId = option.value;


            if (rowExists(lineId)) {

                showError(
                    "This invoice line has already been added."
                );

                return;
            }


            // ----------------------------------------------------
            // Line information
            // ----------------------------------------------------

            const productName =
                option.dataset.productName ||
                "Unknown product";


            const invoiceQty =
                Number(
                    option.dataset.quantity || 0
                );


            const invoiceAmount =
                Number(
                    option.dataset.amount || 0
                );


            const availableAmount =
                Number(
                    option.dataset.availableAmount || 0
                );


            const productId =
                option.dataset.productId || "";


            // ----------------------------------------------------
            // Validate available credit
            // ----------------------------------------------------

            if (
                !Number.isFinite(availableAmount) ||
                availableAmount <= 0
            ) {

                showError(
                    `${productName} has no remaining amount available for credit.`
                );

                return;
            }


            // ----------------------------------------------------
            // Remove empty row
            // ----------------------------------------------------

            const noItemsRow =
                document.getElementById("no-items-row");

            if (noItemsRow) {
                noItemsRow.remove();
            }


            // ----------------------------------------------------
            // Create credit line
            // ----------------------------------------------------

            const row =
                document.createElement("tr");


            row.dataset.lineId =
                lineId;


            row.innerHTML = `
                <td>

                    <strong>
                        ${productName}
                    </strong>

                    <input
                        type="hidden"
                        name="line_id_${lineId}"
                        value="${lineId}"
                    >

                    <input
                        type="hidden"
                        name="product_id_${lineId}"
                        value="${productId}"
                    >

                </td>


                <td class="col-left">
                    ${invoiceQty}
                </td>


                <td class="col-right">
                    ${formatAmount(invoiceAmount)}
                </td>


                <td class="col-right">

                    <input
                        type="number"
                        name="credit_amount_${lineId}"
                        class="form-control credit-amount"
                        min="0.01"
                        max="${availableAmount}"
                        step="0.01"
                        value="${availableAmount.toFixed(2)}"
                        data-max-amount="${availableAmount}"
                        required
                    >

                    <small class="text-muted">
                        Max:
                        ${formatAmount(availableAmount)}
                    </small>

                </td>


                <td class="col-center">

                    <button
                        type="button"
                        class="btn btn-sm btn-danger remove-credit-row"
                    >
                        Remove
                    </button>

                </td>
            `;


            tableBody.appendChild(row);


            productSelect.value = "";


            clearError();
        },
        true
    );


    // ============================================================
    // Remove invoice line
    // ============================================================

    document.addEventListener(
        "click",
        function (e) {

            const removeButton =
                e.target.closest(
                    ".remove-credit-row"
                );


            if (!removeButton) {
                return;
            }


            const row =
                removeButton.closest("tr");


            if (!row) {
                return;
            }


            row.remove();


            if (!hasRows()) {
                resetItemsTable();
            }


            clearError();
        },
        true
    );


    // ============================================================
    // Credit amount input validation
    // ============================================================

    document.addEventListener(
        "input",
        function (e) {

            const input =
                e.target.closest(".credit-amount");


            if (!input) {
                return;
            }


            const max =
                Number(
                    input.dataset.maxAmount
                );


            let value =
                Number(input.value);


            if (!Number.isFinite(value)) {
                return;
            }


            if (value < 0) {
                input.value = "0";
                return;
            }


            if (value > max) {

                input.value =
                    max.toFixed(2);

                showError(
                    `Credit amount cannot exceed ${formatAmount(max)}.`
                );

                return;
            }


            clearError();
        }
    );


    // ============================================================
    // Validate all lines before HTMX request
    // ============================================================

    document.body.addEventListener(
        "htmx:beforeRequest",
        function (e) {

            const modal =
                e.target.closest(
                    "#CreditNoteModal"
                );


            if (!modal) {
                return;
            }


            // ----------------------------------------------------
            // At least one line
            // ----------------------------------------------------

            if (!hasRows()) {

                e.preventDefault();

                showError(
                    "Add at least one invoice line to credit."
                );

                return;
            }


            // ----------------------------------------------------
            // Validate every amount
            // ----------------------------------------------------

            let valid = true;


            getRows().forEach(row => {

                const input =
                    row.querySelector(
                        ".credit-amount"
                    );


                if (
                    !validateCreditAmount(input)
                ) {
                    valid = false;
                }

            });


            if (!valid) {

                e.preventDefault();

                showError(
                    "Please enter a valid credit amount for every line."
                );

                return;
            }


            clearError();
        }
    );


    // ============================================================
    // HTMX response
    // ============================================================

    document.body.addEventListener(
        "htmx:afterRequest",
        function (e) {

            const modal =
                e.target.closest(
                    "#CreditNoteModal"
                );


            if (!modal) {
                return;
            }


            if (!e.detail.successful) {

                showError(
                    "An error occurred while creating the credit note."
                );

                return;
            }


            let data;


            try {

                data =
                    JSON.parse(
                        e.detail.xhr.responseText
                    );

            } catch (error) {

                showError(
                    "Unexpected response from server."
                );

                return;
            }


            // ----------------------------------------------------
            // Server validation failed
            // ----------------------------------------------------

            if (!data.success) {

                showError(
                    formatErrors(data.errors)
                );

                return;
            }


            // ----------------------------------------------------
            // Success
            // ----------------------------------------------------

            if (typeof notify === "function") {

                notify(
                    data.message ||
                    "Credit note created successfully.",
                    "success"
                );
            }


            const modalElement =
                getModal();


            if (
                modalElement &&
                window.bootstrap
            ) {

                const modalInstance =
                    bootstrap.Modal
                        .getOrCreateInstance(
                            modalElement
                        );


                modalInstance.hide();
            }

        }
    );


    // ============================================================
    // Reset when modal closes
    // ============================================================

    document.addEventListener(
        "hidden.bs.modal",
        function (e) {

            if (
                e.target?.id !==
                "CreditNoteModal"
            ) {
                return;
            }


            resetCreditForm();
        }
    );

})();