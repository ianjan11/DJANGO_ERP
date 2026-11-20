(function () {
  'use strict';

  if (!window.ChartCore) {
    console.error('[charts] chart_core.js must load before sales_charts.js');
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

  // ── Sales Revenue Trend ──
  function renderSalesTrend(labels, data, h) {
    const C = h.theme, fmt = h.fmt;
    const peak = Math.max(...data, 0);
    const idx = data.indexOf(peak);
    const short = labels.map(l => String(l).split(' ')[0]);

    h.mount('#stockMovementChartDashboard', {
      chart: h.base('area', 320),
      series: [{ name: 'Revenue', data }],
      colors: [C.indigo],
      stroke: { curve: 'smooth', width: 1.6, lineCap: 'round' },
      fill: {
        type: 'gradient',
        gradient: { shade: 'light', type: 'vertical', shadeIntensity: 0,
                    gradientToColors: [C.card], opacityFrom: 0.16, opacityTo: 0.0, stops: [0, 100] },
      },
      markers: {
        size: 0,
        hover: { size: 5, sizeOffset: 0 },
        colors: [C.card], strokeColors: C.indigo, strokeWidth: 2,
        discrete: peak > 0 ? [{ seriesIndex: 0, dataPointIndex: idx, size: 6, shape: 'circle',
                                fillColor: C.card, strokeColor: C.indigo }] : [],
      },
      dataLabels: { enabled: false },
      xaxis: {
        categories: short,
        axisBorder: { show: false }, axisTicks: { show: false },
        tooltip: { enabled: false },
        labels: h.axisLabel({ rotate: 0, hideOverlappingLabels: true }),
        crosshairs: { stroke: { color: C.periwinkle, width: 1, dashArray: 4 } },
      },
      yaxis: { labels: h.axisLabel({ formatter: v => fmt(Math.round(v)) }) },
      grid: h.grid(),
      legend: { show: false },
      noData: h.noDataOpts(),
      tooltip: h.tip('currency', {
        x: { show: true, formatter: (v, o) => labels[(o && o.dataPointIndex) ?? idx] || v },
      }),
    });
  }

  // ── Top 5 Products per Month ──
  function renderTopProducts(months, series, h) {
    const C = h.theme;
    h.mount('#topProductsColumnChart', {
      chart: { ...h.base('bar', 320), stacked: false },
      series,
      colors: ['#1f2a67', '#4a5aa8', '#7f8fd0', '#aebbe8', '#d4dbf3'],
      plotOptions: {
        bar: {
          columnWidth: '55%',
          borderRadius: 6,
          borderRadiusApplication: 'end',
        },
      },
      stroke: { width: 2, colors: [C.card] },
      dataLabels: { enabled: false },
      xaxis: {
        categories: months,
        axisBorder: { show: false }, axisTicks: { show: false },
        labels: h.axisLabel({ rotate: 0, hideOverlappingLabels: true,
                              formatter: v => (typeof v === 'string' ? v.split(' ')[0] : v) }),
      },
      yaxis: { min: 0, labels: h.axisLabel({ formatter: v => h.fmt(Math.round(v)) }) },
      grid: h.grid(),
      legend: {
        position: 'top', horizontalAlign: 'left', fontSize: '11px', fontWeight: 500,
        labels: { colors: C.muted },
        markers: { width: 7, height: 7, radius: 7, offsetX: -2 },
        itemMargin: { horizontal: 10, vertical: 4 },
      },
      states: { hover: { filter: { type: 'lighten', value: 0.05 } } },
      noData: h.noDataOpts(),
      tooltip: h.tip('units', { shared: false, intersect: true }),
    });
  }

  // ── Ranking Bar Chart (Best / Least / Top Customers) ──
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
      tooltip: h.tip('units'),
    });
  }

  ChartCore.register('sales-dashboard', {
    urlSelector: '[data-sales-charts-url]',
    urlAttribute: 'data-sales-charts-url',
    selectors: [
      '#quotationPieChart', '#salesOrderPieChart', '#deliveryPieChart', '#invoicePieChart',
      '#stockMovementChartDashboard', '#topProductsColumnChart',
      '#bestSellingChart', '#leastSellingChart', '#topCustomersChart',
    ],

    render(r, h) {
      if (r.line_chart)        renderSalesTrend(r.line_chart.labels, r.line_chart.data, h);
      if (r.apex_top_products) renderTopProducts(r.apex_top_products.months, r.apex_top_products.series, h);

      if (r.best_selling)      renderRanking('#bestSellingChart',  r.best_selling,  h.theme.purple, h);
      if (r.least_selling)     renderRanking('#leastSellingChart', r.least_selling, h.theme.slate, h);
      if (r.top_customers)     renderRanking('#topCustomersChart', r.top_customers, h.theme.indigo, h);

      if (r.pie_quotations) renderStatusDonut('#quotationPieChart',  r.pie_quotations,  'quotes',     h);
      if (r.pie_sales)      renderStatusDonut('#salesOrderPieChart', r.pie_sales,       'orders',     h);
      if (r.pie_delivery)   renderStatusDonut('#deliveryPieChart',   r.pie_delivery,    'deliveries', h);
      if (r.pie_invoices)   renderStatusDonut('#invoicePieChart',    r.pie_invoices,    'invoices',   h);
    },
  });
})();