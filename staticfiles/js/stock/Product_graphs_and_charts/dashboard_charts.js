(function () {

  // ── Design tokens ─────────────────────────────────────────
  const COLORS = {
    accent:  "#1f2a67",
    success: "#c4cacbd0",
    warning: "#212122ab",
    danger:  "#ef4444",
    info:    "#06b6d4",
    purple:  "#481e91",
    text:    "#101828",
    muted:   "#667085",
    surface: "#c2c2c3",
    light:   "#d5ecf9",
    border:  "#f0f0f4",
  };

  const PALETTE = [
    COLORS.accent, COLORS.success, COLORS.warning, COLORS.surface,
    COLORS.light,  COLORS.purple,  COLORS.info,    COLORS.danger,
  ];

  const BASE = {
    fontFamily: "'DM Sans', sans-serif",
    foreColor:  COLORS.muted,
    toolbar:    { show: false },
    animations: {
      enabled: true, speed: 600,
      animateGradually: { enabled: true, delay: 100 },
      dynamicAnimation: { enabled: true, speed: 300 },
    },
  };

  const GRID = {
    borderColor: COLORS.border,
    strokeDashArray: 4,
    xaxis: { lines: { show: false } },
    yaxis: { lines: { show: true  } },
    padding: { top: 0, right: 16, bottom: 0, left: 8 },
  };

  const TOOLTIP_STYLE = {
    style: { fontSize: "13px", fontFamily: "'DM Sans', sans-serif" },
    x: { show: true },
  };

  // ── Track rendered instances so we can destroy before re-render ──
  const _instances = {};

  function destroyChart(id) {
    if (_instances[id]) {
      try { _instances[id].destroy(); } catch (_) {}
      delete _instances[id];
    }
  }

  function mountChart(id, options) {
    destroyChart(id);
    const el = document.querySelector(id);
    if (!el) return;
    el.innerHTML = ''; // clear any previous canvas
    const chart = new ApexCharts(el, options);
    chart.render();
    _instances[id] = chart;
  }

  // ── Data fetch ────────────────────────────────────────────
  async function fetchData(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error('Network response was not ok');
      return await res.json();
    } catch (err) {
      console.error('Chart fetch error:', err);
      return null;
    }
  }

  // ── Donut — Delivery status ───────────────────────────────
  function renderDeliveryStatusChart(labels, series) {
    mountChart('#D-Chart', {
      chart: { ...BASE, type: 'donut', height: 260 },
      labels,
      series,
      colors: PALETTE,
      plotOptions: {
        pie: {
          donut: {
            size: '72%',
            labels: {
              show: true,
              name:  { show: true, fontSize: '13px', fontFamily: BASE.fontFamily, color: COLORS.muted, offsetY: -6 },
              value: { show: true, fontSize: '22px', fontWeight: 700, fontFamily: "'DM Mono', monospace", color: COLORS.text, offsetY: 6 },
              total: {
                show: true, label: 'Total', fontSize: '12px',
                fontFamily: BASE.fontFamily, color: COLORS.muted,
                formatter: w => w.globals.seriesTotals.reduce((a, b) => a + b, 0),
              },
            },
          },
        },
      },
      dataLabels: { enabled: false },
      legend: {
        position: 'bottom', fontFamily: BASE.fontFamily, fontSize: '12px',
        fontWeight: 500, markers: { width: 8, height: 8, radius: 8 },
        itemMargin: { horizontal: 10, vertical: 4 },
      },
      stroke: { width: 0 },
      tooltip: { ...TOOLTIP_STYLE, y: { formatter: val => `${val} deliveries` } },
    });
  }

  // ── Area — Sales trend ────────────────────────────────────
  function renderSalesTrendChart(labels, data) {
    mountChart('#stockMovementChartDashboard', {
      chart: { ...BASE, type: 'area', height: 305 },
      series: [{ name: 'Sales', data }],
      colors: [COLORS.accent],
      xaxis: {
        categories: labels,
        axisBorder: { show: false }, axisTicks: { show: false },
        labels: { rotate: -35, style: { fontSize: '11px', fontFamily: BASE.fontFamily, colors: COLORS.muted } },
      },
      yaxis: {
        min: 0,
        labels: { style: { fontSize: '11px', fontFamily: BASE.fontFamily, colors: COLORS.muted }, formatter: val => Math.round(val) },
      },
      grid: GRID,
      stroke: { curve: 'smooth', width: 3 },
      fill: {
        type: 'gradient',
        gradient: { shadeIntensity: 0.6, opacityFrom: 0.45, opacityTo: 0.05, stops: [0, 90, 100] },
      },
      markers: {
        shape: 'square', size: 4, hover: { size: 6, sizeOffset: 2 },
        strokeWidth: 2, strokeColors: '#fff', colors: [COLORS.accent],
      },
      tooltip: { ...TOOLTIP_STYLE, y: { formatter: val => `${val} units` } },
      legend: { show: false },
    });
  }

  // ── Bar — Top products ────────────────────────────────────
  function renderTopProductsChart(months, series) {
    const coloredSeries = series.map((s, i) => ({ ...s, color: PALETTE[i % PALETTE.length] }));
    mountChart('#myChart', {
      chart: { ...BASE, type: 'bar', height: 310, stacked: false },
      series: coloredSeries,
      colors: PALETTE,
      xaxis: {
        categories: months,
        axisBorder: { show: false }, axisTicks: { show: false },
        labels: { rotate: -35, style: { fontSize: '11px', fontFamily: BASE.fontFamily, colors: COLORS.muted } },
      },
      yaxis: {
        min: 0,
        labels: { style: { fontSize: '11px', fontFamily: BASE.fontFamily, colors: COLORS.muted }, formatter: val => Math.round(val) },
      },
      grid: GRID,
      plotOptions: { bar: { columnWidth: '55%', borderRadius: 4, borderRadiusApplication: 'end' } },
      dataLabels: { enabled: false },
      legend: {
        position: 'top', horizontalAlign: 'left', fontFamily: BASE.fontFamily,
        fontSize: '12px', fontWeight: 500,
        markers: { width: 8, height: 8, radius: 4 },
        itemMargin: { horizontal: 10 },
      },
      tooltip: { ...TOOLTIP_STYLE, shared: true, intersect: false, y: { formatter: val => `${val} units` } },
    });
  }

  // ── Init ──────────────────────────────────────────────────
  async function initCharts(url) {
    const result = await fetchData(url);
    if (!result) return;

    if (result.line_chart)       renderSalesTrendChart(result.line_chart.labels, result.line_chart.data);
    if (result.apex_top_products) renderTopProductsChart(result.apex_top_products.months, result.apex_top_products.series);
    if (result.pie_chart_series)  renderDeliveryStatusChart(result.pie_chart_series.labels, result.pie_chart_series.series);
  }

  // ── Event delegation ─────────────────────────────────────
  // fires on nav click (user navigates to dashboard)
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.dashboard-page');
    if (!btn) return;
    // wait for HTMX to finish swapping before rendering charts
    document.addEventListener('htmx:afterSwap', function handler(ev) {
      if (ev.detail.target.id === 'inventory-display') {
        document.removeEventListener('htmx:afterSwap', handler);
        const url = btn.dataset.chartsUrl || window.CHARTS_URL;
        if (url) initCharts(url);
      }
    });
  });

  // fires if dashboard is the default page on load
  document.addEventListener('DOMContentLoaded', function () {
    const el = document.querySelector('#myChart, #D-Chart, #stockMovementChartDashboard');
    if (el && window.CHARTS_URL) initCharts(window.CHARTS_URL);
  });

})();