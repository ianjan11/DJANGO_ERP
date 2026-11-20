document.addEventListener("DOMContentLoaded", initInventoryCharts);
document.addEventListener("htmx:afterSwap", initInventoryCharts);

function initInventoryCharts() {
    // Prevent double-binding if script runs multiple times
    const warehouseSelect = document.getElementById("warehouseSelect");
    const locationSelect  = document.getElementById("locationSelect");

    // Guard: Only run if we are actually on the dashboard view
    if (!document.getElementById("bestSellingChart") && !document.getElementById("stockMovementChartDashboard")) {
        return;
    }

    let stockChart = null;
    let bestSellingChart = null;
    let leastSellingChart = null;
    let deliveryPieChart = null;
    let receiptPieChart = null;
    let transferPieChart = null;
    let returnPieChart = null;
    let topProductsChart = null;

    // Fallback URL if global variable isn't set
    const datasetUrl = typeof PRODUCT_SALES_DATASET_URL !== "undefined"
        ? PRODUCT_SALES_DATASET_URL
        : window.location.pathname;

    async function fetchInventoryChartData(warehouseId = null, locationId = null) {
        let url = datasetUrl + "?";
        if (warehouseId) url += `warehouse_id=${warehouseId}&`;
        if (locationId) url += `location_id=${locationId}&`;

        try {
            const res = await fetch(url, {
                headers: { "HX-Request": "true" }
            });
            if (!res.ok) throw new Error("Network response was not ok");
            return await res.json();
        } catch (e) {
            console.error("Error fetching inventory chart data:", e);
            return null;
        }
    }

    // 1️⃣ Area Chart – Sales Trend
    function renderTrendChart(months, quantities) {
        const chartEl = document.getElementById("stockMovementChartDashboard");
        if (!chartEl) return;

        if (stockChart) { stockChart.destroy(); stockChart = null; }

        const options = {
            chart: { type: "area", height: 320, toolbar: { show: false } },
            series: [{ name: "Sales per Month", data: quantities }],
            colors: ["#4f46e5"],
            xaxis: {
                categories: months,
                labels: { style: { colors: "#6b7280", fontSize: "12px" } }
            },
            stroke: { curve: "smooth", width: 3 },
            fill: {
                type: "gradient",
                gradient: { shadeIntensity: 0.6, opacityFrom: 0.45, opacityTo: 0.05, stops: [0, 90, 100] }
            },
            yaxis: {
                min: 0,
                labels: { style: { colors: "#6b7280", fontSize: "12px" }, formatter: val => Math.round(val) }
            },
            grid: { borderColor: "#e5e7eb", strokeDashArray: 4 },
            tooltip: { y: { formatter: val => `${val} units` } }
        };

        stockChart = new ApexCharts(chartEl, options);
        stockChart.render();
    }

    // 2️⃣ Horizontal Bar Chart – Best Selling
    function renderBestSellingChart(labels, data, background) {
        const chartEl = document.getElementById("bestSellingChart");
        if (!chartEl) return;
        if (bestSellingChart) { bestSellingChart.destroy(); bestSellingChart = null; }

        const options = {
            chart: { type: "bar", height: 300, toolbar: { show: false } },
            plotOptions: { bar: { horizontal: true, borderRadius: 4 } },
            series: [{ name: "Quantity Sold", data: data }],
            colors: background || ["#4f46e5"],
            xaxis: { categories: labels },
            grid: { borderColor: "#e5e7eb" },
            tooltip: { y: { formatter: val => `${val} units` } }
        };

        bestSellingChart = new ApexCharts(chartEl, options);
        bestSellingChart.render();
    }

    // 3️⃣ Horizontal Bar Chart – Least Selling
    function renderLeastSellingChart(labels, data, background) {
        const chartEl = document.getElementById("leastSellingChart");
        if (!chartEl) return;
        if (leastSellingChart) { leastSellingChart.destroy(); leastSellingChart = null; }

        const options = {
            chart: { type: "bar", height: 300, toolbar: { show: false } },
            plotOptions: { bar: { horizontal: true, borderRadius: 4 } },
            series: [{ name: "Quantity Sold", data: data }],
            colors: background || ["#ef4444"],
            xaxis: { categories: labels },
            grid: { borderColor: "#e5e7eb" },
            tooltip: { y: { formatter: val => `${val} units` } }
        };

        leastSellingChart = new ApexCharts(chartEl, options);
        leastSellingChart.render();
    }

    // 4️⃣ Donut/Pie Chart Renderer
    function renderPieChart(elementId, labels, series, chartInstanceRef) {
        const chartEl = document.getElementById(elementId);
        if (!chartEl) return chartInstanceRef;
        if (chartInstanceRef) { chartInstanceRef.destroy(); chartInstanceRef = null; }

        const options = {
            chart: { type: "donut", height: 220 },
            labels: labels,
            series: series,
            colors: ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"],
            legend: { position: "bottom", fontSize: "11px" },
            dataLabels: { enabled: true }
        };

        const newChart = new ApexCharts(chartEl, options);
        newChart.render();
        return newChart;
    }

    // 5️⃣ Column Chart – Top Products per Month
    function renderTopProductsColumnChart(months, seriesData) {
        const chartEl = document.getElementById("topProductsColumnChart");
        if (!chartEl) return;
        if (topProductsChart) { topProductsChart.destroy(); topProductsChart = null; }

        const options = {
            chart: { type: "bar", height: 320, stacked: true, toolbar: { show: false } },
            series: seriesData,
            xaxis: { categories: months },
            colors: ["#4f46e5", "#06b6d4", "#10b981", "#f59e0b", "#ec4899"],
            grid: { borderColor: "#e5e7eb" },
            legend: { position: "top" }
        };

        topProductsChart = new ApexCharts(chartEl, options);
        topProductsChart.render();
    }

    // Main Execution Flow
    async function updateDashboardCharts() {
        const warehouseId = warehouseSelect ? warehouseSelect.value : null;
        const locationId  = locationSelect ? locationSelect.value : null;

        const data = await fetchInventoryChartData(warehouseId, locationId);
        if (!data) return;

        if (data.line_chart) renderTrendChart(data.line_chart.labels, data.line_chart.data);
        if (data.bar_chart) renderBestSellingChart(data.bar_chart.labels, data.bar_chart.data, data.bar_chart.background);
        if (data.least_selling_chart) renderLeastSellingChart(data.least_selling_chart.labels, data.least_selling_chart.data, data.least_selling_chart.background);

        if (data.pie_delivery) deliveryPieChart = renderPieChart("deliveryPieChart", data.pie_delivery.labels, data.pie_delivery.series, deliveryPieChart);
        if (data.pie_receipts) receiptPieChart = renderPieChart("receiptPieChart", data.pie_receipts.labels, data.pie_receipts.series, receiptPieChart);
        if (data.pie_transfers) transferPieChart = renderPieChart("transferPieChart", data.pie_transfers.labels, data.pie_transfers.series, transferPieChart);
        if (data.pie_returns) returnPieChart = renderPieChart("returnPieChart", data.pie_returns.labels, data.pie_returns.series, returnPieChart);

        if (data.apex_top_products) renderTopProductsColumnChart(data.apex_top_products.months, data.apex_top_products.series);
    }

    updateDashboardCharts();
}