(function () {

  // ── Guard — globals must be set in the template before this script loads ──
  if (typeof PRODUCT_SALES_DATASET_URL === 'undefined') {
    console.error('PRODUCT_SALES_DATASET_URL is not defined. Add it to the template.');
    return;
  }

  let productChart = null;

  // ── Fetch ─────────────────────────────────────────────────
  async function fetchProductSalesData() {
    try {
      const response = await fetch(PRODUCT_SALES_DATASET_URL);
      if (!response.ok) throw new Error('Network response was not ok');
      return await response.json();
    } catch (error) {
      console.error('Error fetching product sales data:', error);
      return null;
    }
  }

  // ── Render ────────────────────────────────────────────────
  function renderProductSalesChart(months, quantities) {
    const chartEl = document.getElementById('stockMovementChart');
    if (!chartEl) {
      console.error('#stockMovementChart not found in DOM');
      return;
    }

    // destroy previous instance before re-rendering
    // needed when HTMX re-swaps the content panel
    if (productChart) {
      try { productChart.destroy(); } catch (_) {}
      productChart = null;
    }

    chartEl.innerHTML = '';   // clear any stale canvas

    const options = {
      chart: {
        type: 'area',
        height: 600,
        fontFamily: 'Inter, system-ui, sans-serif',
        toolbar: { show: false },
        animations: {
          enabled: true,
          speed: 650,
          animateGradually: { enabled: true, delay: 80 },
          dynamicAnimation: { enabled: true, speed: 300 },
        },
      },

      series: [{ name: 'Net Units Moved', data: quantities }],

      colors: ['#111a4a'],     // --color-deep-indigo from your token file

      stroke: { curve: 'smooth', width: 3 },

      markers: {
        size: 4,
        strokeWidth: 2,
        strokeColors: '#fff',
        colors: ['#111a4a'],
        hover: { size: 6 },
      },

      fill: {
        type: 'gradient',
        gradient: {
          shadeIntensity: 0.6,
          opacityFrom: 0.35,
          opacityTo: 0.02,
          stops: [0, 90, 100],
        },
      },

      grid: {
        borderColor: '#e3e4e8',   // --color-mist
        strokeDashArray: 4,
        xaxis: { lines: { show: false } },
        yaxis: { lines: { show: true  } },
        padding: { left: 8, right: 16, top: 0, bottom: 0 },
      },

      xaxis: {
        categories: months,
        axisBorder: { show: false },
        axisTicks:  { show: false },
        labels: {
          rotate: -30,
          style: { colors: '#717276', fontSize: '11px' },  // --color-slate
        },
      },

      yaxis: {
        min: 0,
        labels: {
          style: { colors: '#717276', fontSize: '11px' },
          formatter: val => Math.round(val),
        },
      },

      tooltip: {
        theme: 'light',
        x: { show: true },
        y: { formatter: val => `${val} units` },
      },

      legend: { show: false },
    };

    productChart = new ApexCharts(chartEl, options);
    productChart.render();
  }

  // ── Init ─────────────────────────────────────────────────
  async function initProductSalesChart() {
    const data = await fetchProductSalesData();
    if (!data) return;
    renderProductSalesChart(data.months, data.quantities);
  }

  // ── Run on load ───────────────────────────────────────────
  // The chart renders when this script runs (called from template after DOM ready)
  // It also re-renders when HTMX swaps back to this panel via nav click
  if (document.getElementById('stockMovementChart')) {
    initProductSalesChart();
  }

  // ── Re-render after HTMX swaps this panel back in ─────────
  document.addEventListener('htmx:afterSwap', function handler(e) {
    if (document.getElementById('stockMovementChart')) {
      initProductSalesChart();
      // do NOT removeEventListener — the user may navigate away and back multiple times
    }
  });

})();   // fixed: was missing the closing ()