document.addEventListener("DOMContentLoaded", function () {

    const warehouseSelect = document.getElementById("warehouseSelect");
    const locationSelect  = document.getElementById("locationSelect");

    let stockChart = null;

    async function fetchProductSalesData(warehouseId = null, locationId = null) {
        let url = PRODUCT_SALES_DATASET_URL + "?";
        if (warehouseId) url += `warehouse_id=${warehouseId}&`;
        if (locationId) url += `location_id=${locationId}&`;

        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error("Network response was not ok");
            return await res.json();
        } catch (e) {
            console.error("Error fetching chart data:", e);
            return null;
        }
    }

    function renderChart(months, quantities) {
        const chartEl = document.getElementById("stockMovementPerLocation");

        if (stockChart) {
            stockChart.destroy();
            stockChart = null;
        }

        const options = {
            chart: {
                type: "area",
                height: 200,
                toolbar: { show: false }
            },
            series: [{
                name: "Sales per Month",
                data: quantities
            }],
            colors: ["#4f46e5"],

            xaxis: {
                categories: months,
                axisBorder: { show: false },
                axisTicks: { show: false },
                labels: {
                    style: {
                        colors: "#6b7280",
                        fontSize: "12px"
                    }
                }
            },
             stroke: {
            curve: "smooth",
            width: 3,

        },
             markers: {
                size: 4,
                strokeWidth: 2,
                hover: {
                    size: 6
                }
            },
         fill: {
            type: "gradient",
            gradient: {
                shadeIntensity: 0.6,
                opacityFrom: 0.45,
                opacityTo: 0.05,
                stops: [0, 90, 100]
            }
        },
            yaxis: {
                min: 0,
                labels: {
                    style: {
                        colors: "#6b7280",
                        fontSize: "12px"
                    },
                    formatter: val => Math.round(val)
                }
            },
              grid: {
                borderColor: "#e5e7eb",
                strokeDashArray: 4,
                padding: {
                    left: 10,
                    right: 10
                }
            },
              tooltip: {
                theme: "light",
                x: {
                    show: true
                },
                y: {
                    formatter: val => `${val} units`
                }
            },
            legend: {
                position: "top",
                horizontalAlign: "right",
                fontSize: "13px",
                
            }

        };

        stockChart = new ApexCharts(chartEl, options);
        stockChart.render();
    }

    async function updateChart() {
        const warehouseId = warehouseSelect.value || null;
        const locationId  = locationSelect.value || null;

        if (!locationId) {
            if (stockChart) {
                stockChart.destroy();
                stockChart = null;
            }
            return;
        }

        const data = await fetchProductSalesData(warehouseId, locationId);
        if (data) renderChart(data.months, data.quantities);
    }

    // Warehouse change
    warehouseSelect.addEventListener("change", async function () {
        const warehouseId = this.value;

        locationSelect.innerHTML = '<option value="">Select Location</option>';
        locationSelect.disabled = true;

        if (!warehouseId) {
            updateChart();
            return;
        }

        const locUrl = "{% url 'get_locations_by_warehouse' 0 %}".replace("0", warehouseId);
        const res = await fetch(locUrl);
        const data = await res.json();

        if (data.success) {
            locationSelect.disabled = false;
            data.locations.forEach(loc => {
                locationSelect.innerHTML += `<option value="${loc.id}">${loc.name}</option>`;
            });
        }

        updateChart();
    });

    locationSelect.addEventListener("change", updateChart);

    // Initial load
    updateChart();

});