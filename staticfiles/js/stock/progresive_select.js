document.addEventListener("DOMContentLoaded", function () {

    const warehouseSelect = document.getElementById("warehouseSelect");
    const locationSelect  = document.getElementById("locationSelect");
    const adjustSection   = document.getElementById("adjust-transfer-section"); // wrap your adjust/transfer form in this
    const reservedQty     = document.getElementById("reservedQty");
    const availableQty    = document.getElementById("availableQty");
    const onHandQty       = document.getElementById("onHandQty");


    adjustSection.style.display = "none";

    /* -----------------------------
       Warehouse → Locations
    ----------------------------- */
    warehouseSelect.addEventListener("change", function () {

        const warehouseId = this.value;

        locationSelect.innerHTML = '<option value="">Select Location</option>';
        locationSelect.disabled = true;

        reservedQty.textContent = "0";
        availableQty.textContent = "0";
        onHandQty.textContent = "0";



        if (!warehouseId) return;

        const url = GET_LOCATIONS_BASE.replace("/0/", `/${warehouseId}/`);

        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (!data.success) return;
                locationSelect.disabled = false;
                data.locations.forEach(loc => {
                    locationSelect.innerHTML +=
                        `<option value="${loc.id}">${loc.name}</option>`;
                });


            })
            .catch(err => console.error("Location fetch error:", err));
    });

    /* -----------------------------
       Location → Stock
    ----------------------------- */
    locationSelect.addEventListener("change", function () {
          if (this.value) {
            adjustSection.style.display = "block"; // show if location selected
        } else {
            adjustSection.style.display = "none"; // hide if no location
        }
        const locationId = this.value;
        SELECTED_QUANT_ID = null;  // reset for safety
        reservedQty.textContent  = "0";
        availableQty.textContent = "0";
        onHandQty.textContent    = "0";

        if (!locationId) return;

        const url =
            GET_PRODUCT_BASE.replace("/0/", `/${PRODUCT_ID}/`) +
            `?location_id=${locationId}`;

        fetch(url)
            .then(res => res.json())
            .then(data => {
                reservedQty.textContent  = data.reserved ?? 0;
                availableQty.textContent = data.available ?? 0;
                onHandQty.textContent    = data.on_hand ?? 0;
                SELECTED_QUANT_ID = data.quant.id;
            })
            .catch(err => console.error("Stock fetch error:", err));
    });

});
