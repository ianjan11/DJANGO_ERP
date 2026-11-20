(function () {
  'use strict';

  if (!window.ChartCore) {
    console.error('[charts] chart_core.js must load before accounting_charts.js');
    return;
  }

  // ── Status donut: interactive center update on slice click ──
  function renderStatusDonut(selector, data, noun, h) {
    const C = h.theme, fmt = h.fmt;
    const series = data.series || [];
    const total = series.reduce((a, b) => a + b, 0);
    let selected = null;

    const labelText = () => (selected === null ? noun : data.labels[selected]);
    const valueText = () => fmt(selected === null ? total : series[selected]);

    function paintCenter(chartContext) {
      const total_cfg = chartContext.w.config.plotOptions.pie.donut.labels.total;
      total_cfg.label = labelText();
      const root = chartContext.el;
      const lbl = root.querySelector('.apexcharts-datalabel-label');
      const val = root.querySelector('.apexcharts-datalabel-value');
      if (lbl) lbl.textContent = labelText();
      if (val) val.textContent = valueText();
    }

    h.mount(selector, {
      chart: {
        ...h.base('donut', 230),
        events: {
          dataPointSelection: function (event, chartContext, config) {
            const i = config.dataPointIndex;
            selected = selected === i ? null : i;
            setTimeout(() => paintCenter(chartContext), 0);
          },
          dataPointMouseLeave: function (event, chartContext) {
            setTimeout(() => paintCenter(chartContext), 0);
          },
        },
      },
      labels: data.labels,
      series: total ? series : [],
      colors: [C.purpleSoft, C.slate, C.purple, C.rose],
      stroke: { width: 4, colors: [C.card] },
      dataLabels: { enabled: false },
      plotOptions: {
        pie: {
          expandOnClick: true,
          donut: {
            size: '80%',
            labels: {
              show: true,
              name:  { show: true, fontSize: '11px', fontWeight: 400, color: C.purple, offsetY: 20 },
              value: { show: true, fontSize: '34px', fontWeight: 300, color: C.purple, offsetY: -12,
                       formatter: v => fmt(v) },
              total: { show: true, showAlways: true, label: noun, fontSize: '11px', fontWeight: 400,
                       color: C.purpleSoft,
                       formatter: () => (selected === null ? total : series[selected]) },
            },
          },
        },
      },
      legend: {
        position: 'bottom', fontSize: '10px', fontWeight: 500,
        labels: { colors: C.muted },
        markers: { width: 7, height: 7, radius: 7, offsetX: -2 },
        itemMargin: { horizontal: 6, vertical: 2 },
      },
      states: { hover: { filter: { type: 'lighten', value: 0.05 } }, active: { filter: { type: 'none' } } },
      noData: h.noDataOpts(),
      tooltip: h.tip(noun, { fillSeriesColor: false }),
    });
  }

  // ── Accounting Financial Trend (Invoices vs Bills Multi-Series Area with distinct colors) ──
  function renderFinancialTrend(labels, series, h) {
    const C = h.theme;
    const short = labels.map(l => String(l).split(' ')[0]);

    h.mount('#accountingTrendChart', {
      chart: h.base('area', 320),
      series,
      colors: [C.indigo, C.rose], // Distinct primary colors for Invoices vs Bills
      stroke: { curve: 'smooth', width: 2, lineCap: 'round' },
      fill: {
        type: 'gradient',
        gradient: {
          shade: 'light',
          type: 'vertical',
          shadeIntensity: 0.5,
          inverseColors: false,
          opacityFrom: 0.35,
          opacityTo: 0.0,
          stops: [0, 100]
        },
      },
      markers: { size: 0, hover: { size: 5, sizeOffset: 0 } },
      dataLabels: { enabled: false },
      xaxis: {
        categories: short,
        axisBorder: { show: false }, axisTicks: { show: false },
        tooltip: { enabled: false },
        labels: h.axisLabel({ rotate: 0, hideOverlappingLabels: true }),
      },
      yaxis: { labels: h.axisLabel({ formatter: v => h.fmt(Math.round(v)) }) },
      grid: h.grid(),
      legend: { position: 'top', horizontalAlign: 'right', fontSize: '11px', fontWeight: 500, labels: { colors: C.muted } },
      noData: h.noDataOpts(),
      tooltip: h.tip('currency'),
    });
  }

  // ── Ranking Bar Chart (Top Customers / Top Vendors) ──
  function renderRanking(selector, data, color, h) {
    const C = h.theme, fmt = h.fmt;
    const height = Math.max(180, (data.labels || []).length * 54 + 30);

    h.mount(selector, {
      chart: h.base('bar', height),
      series: [{ name: 'Value', data: data.data || [] }],
      colors: [color],
      plotOptions: { bar: { horizontal: true, barHeight: '26%', borderRadius: 10,
                            borderRadiusApplication: 'around', dataLabels: { position: 'top' } } },
      dataLabels: {
        enabled: true, textAnchor: 'start', offsetX: 8,
        formatter: v => fmt(v),
        style: { fontSize: '11px', fontWeight: 600, colors: [C.ink] },
        background: { enabled: false },
      },
      xaxis: { categories: data.labels || [], axisBorder: { show: false }, axisTicks: { show: false },
               labels: { show: false } },
      yaxis: { labels: { style: { fontSize: '11px', fontFamily: h.font, colors: C.ink, fontWeight: 500 },
                         maxWidth: 160 } },
      grid: { ...h.grid({ y: false }), padding: { top: 0, right: 40, bottom: 0, left: 8 } },
      legend: { show: false },
      states: { hover: { filter: { type: 'lighten', value: 0.05 } } },
      noData: h.noDataOpts(),
      tooltip: h.tip('currency'),
    });
  }

  ChartCore.register('accounting-dashboard', {
    urlSelector: '[data-accounting-charts-url]',
    urlAttribute: 'data-accounting-charts-url',
    selectors: [
      '#moveStatePieChart', '#paymentStatePieChart', '#journalPieChart',
      '#accountingTrendChart', '#topCustomersChart', '#topVendorsChart',
    ],

    render(r, h) {
      if (r.line_chart)        renderFinancialTrend(r.line_chart.labels, r.line_chart.series, h);
      if (r.top_customers)     renderRanking('#topCustomersChart', r.top_customers, h.theme.indigo, h);
      if (r.top_vendors)       renderRanking('#topVendorsChart',   r.top_vendors,   h.theme.purple, h);

      if (r.pie_move_states)    renderStatusDonut('#moveStatePieChart',    r.pie_move_states,    'entries',  h);
      if (r.pie_payment_states) renderStatusDonut('#paymentStatePieChart', r.pie_payment_states, 'invoices', h);
      if (r.pie_journals)       renderStatusDonut('#journalPieChart',      r.pie_journals,       'journals', h);
    },
  });
})();