(function () {
  "use strict";

  const SEL = {
    row: "tr.purchase-row, tr.invoice-row, tr.order-row",
    product:  'select[name$="-product"]',
    price:    'input[name$="-price_unit"]',
    discount: 'input[name$="-discount_percent"]',
    quantity: 'input[name$="-quantity"]',
    feedback: ".invalid-feedback",
    description: 'textarea[name$="-description"], input[name$="-description"]',
   };

  function getRow(el) { return el.closest(SEL.row); }

  function setInvalid(input, message) {
    input.classList.add("is-invalid");
    const fb = input.closest("td")?.querySelector(SEL.feedback);
    if (fb) fb.textContent = message;
  }

  function clearInvalid(input) {
    input.classList.remove("is-invalid");
    const fb = input.closest("td")?.querySelector(SEL.feedback);
    if (fb) fb.textContent = "";
  }

  function onProductChange(select) {
    const row = getRow(select);
    if (!row) return;



    const priceInput    = row.querySelector(SEL.price);
    const discountInput = row.querySelector(SEL.discount);
    const quantityInput = row.querySelector(SEL.quantity);
    const descriptionInput       = row.querySelector(SEL.description)



    if (!select.value) {
      if (priceInput)    { priceInput.value    = "";  clearInvalid(priceInput); }
      if (discountInput) { discountInput.value = "0"; discountInput.removeAttribute("max"); }
      if (quantityInput) { quantityInput.value = "";  quantityInput.removeAttribute("max"); clearInvalid(quantityInput); }
      if (descriptionInput){ descriptionInput.value = ""; clearInvalid(descriptionInput) }
      return;  // nothing to save
    }

    const opt         = select.selectedOptions[0];
    const price       = opt.dataset.price             ?? "";
    const maxDiscount = opt.dataset.maxDiscountPercent ?? "";
    const stock       = opt.dataset.stock              ?? "";
    const desc        = opt.dataset.description ?? "";



    if (priceInput) {
      priceInput.value = price;

    }

    if (discountInput) {
      discountInput.value = "0";
      maxDiscount !== "" ? discountInput.setAttribute("max", maxDiscount) : discountInput.removeAttribute("max");
      clearInvalid(discountInput);
    }

    if (quantityInput) {
      quantityInput.value = "1";
      quantityInput.setAttribute("min", "1");
      stock !== "" ? quantityInput.setAttribute("max", stock) : quantityInput.removeAttribute("max");
      clearInvalid(quantityInput);
    }

    if (descriptionInput) {
    descriptionInput.value = desc;
}

    // Fire one clean autosave after the browser has painted the new values
    requestAnimationFrame(() => htmx.trigger(row, "save-row"));
  }

  function onDiscountInput(input) {
    const max = parseFloat(input.getAttribute("max"));
    if (isNaN(max)) return;
    parseFloat(input.value) > max
      ? setInvalid(input, `Max discount: ${max}%`)
      : clearInvalid(input);
  }

  function onQuantityInput(input) {
    const max = parseFloat(input.getAttribute("max"));
    if (isNaN(max)) return;
    parseFloat(input.value) > max
      ? setInvalid(input, `Only ${max} in stock`)
      : clearInvalid(input);
  }

  // ── Event delegation ──────────────────────────────────────────────────────
  document.addEventListener("change", (e) => {
    if (e.target.matches(SEL.product)) {
      onProductChange(e.target);
    }
  });

  document.addEventListener("input", (e) => {
    if (e.target.matches(SEL.discount)) onDiscountInput(e.target);
    if (e.target.matches(SEL.quantity)) onQuantityInput(e.target);
  });



})();