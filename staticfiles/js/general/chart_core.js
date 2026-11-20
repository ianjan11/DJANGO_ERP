
(function () {
  'use strict';

  // ============================================================
  // Shared chart theme
  // ============================================================

  const DEFAULTS = {
    purple:     '#1f2a67',
    purpleSoft: '#9fb0e3',
    indigo:     '#1f2a67',
    slate:      '#4a5aa8',
    periwinkle: '#d4dbf3',
    mist:       '#e6e9f7',
    lavender:   '#f4f5fc',
    ink:        '#1b2250',
    muted:      '#9aa1bf',
    rose:       '#e59ab0',
    card:       '#ffffff',
  };

  const DEFAULT_FONT = "'Inter', 'DM Sans', system-ui, sans-serif";

  let C = { ...DEFAULTS };
  let FONT = DEFAULT_FONT;

  function token(name, fallback) {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim();

    return value || fallback;
  }

  function loadTheme() {
    const accent = token('--color-deep-indigo', DEFAULTS.indigo);

    C = {
      ...DEFAULTS,
      purple: accent,
      indigo: accent,
      mist: token('--color-mist', DEFAULTS.mist),
      ink: token('--color-deep-ink', DEFAULTS.ink),
      muted: token('--color-fog', DEFAULTS.muted),
      card: token('--surface-card', DEFAULTS.card),
    };

    FONT = token('--font-suisseintl', DEFAULT_FONT);

    return C;
  }

  // ============================================================
  // Shared chart helpers
  // ============================================================

  const fmt = value =>
    Number(value).toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });

  function base(type, height) {
    return {
      type,
      height,
      fontFamily: FONT,
      foreColor: C.muted,
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      parentHeightOffset: 0,
      dropShadow: { enabled: false },
       animations: {
        enabled: true,
        easing: 'easeinout',
        speed: 600,
        animateGradually: { enabled: true, delay: 40 },
        dynamicAnimation: { enabled: false },   // was true; it re-animates every updateOptions
      },


    };
  }

  function grid(options = {}) {
    return {
      borderColor: C.mist,
      strokeDashArray: 0,
      xaxis: { lines: { show: false } },
      yaxis: { lines: { show: options.y !== false } },
      padding: {
        top: 0,
        right: 10,
        bottom: 0,
        left: 6,
      },
    };
  }

  function axisLabel(extra = {}) {
    return {
      style: {
        fontSize: '10px',
        fontFamily: FONT,
        colors: C.muted,
        fontWeight: 500,
      },
      ...extra,
    };
  }

  function tip(unit, extra = {}) {
    return {
      theme: 'light',
      style: {
        fontSize: '11px',
        fontFamily: FONT,
      },
      y: {
        formatter: value => `${fmt(value)} ${unit}`,
      },
      marker: { show: true },
      ...extra,
    };
  }

  function noDataOpts() {
    return {
      text: 'No data yet',
      align: 'center',
      verticalAlign: 'middle',
      style: {
        color: C.muted,
        fontSize: '12px',
        fontFamily: FONT,
      },
    };
  }

  // ============================================================
  // ApexCharts instance management
  // ============================================================

  const instances = {};

  function destroy(selector) {
    const instance = instances[selector];

    if (!instance) return;

    try {
      instance.chart.destroy();
    } catch (error) {
      console.warn('[charts] destroy error:', selector, error);
    }

    delete instances[selector];
  }

  function isMounted(selector, element) {
    const instance = instances[selector];

    return Boolean(
      instance &&
      instance.element === element &&
      element.isConnected
    );
  }

  function mount(selector, options) {
    const element = document.querySelector(selector);

    if (!element) {
      console.warn('[charts] container not found:', selector);
      return null;
    }

    // Avoid destroying and recreating a chart unnecessarily.
    // This prevents animations from replaying on unrelated HTMX swaps.
    if (isMounted(selector, element)) {
      return instances[selector].chart;
    }

    // Destroy the previous instance if its element was replaced.
    destroy(selector);

    element.innerHTML = '';

    const chart = new ApexCharts(element, options);

    instances[selector] = {
      element,
      chart,
    };

    chart.render().catch(error => {
      console.error('[charts] render error:', selector, error);
    });

    return chart;
  }

  function pruneDetached() {
    Object.keys(instances).forEach(selector => {
      const instance = instances[selector];

      if (!instance.element.isConnected) {
        destroy(selector);
      }
    });
  }

  // ============================================================
  // Data fetching
  // ============================================================

  async function fetchData(url) {
    try {
      const response = await fetch(url, {
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();

    } catch (error) {
      console.error('[charts] fetch error:', error);
      return null;
    }
  }

  // ============================================================
  // App chart registration
  // ============================================================

  const modules = {};
  const loading = {};

  function register(name, config) {
    if (modules[name]) {
      console.warn(`[charts] module already registered: ${name}`);
      return;
    }

    modules[name] = config;
  }

  function getModuleUrl(config) {
    const holder = document.querySelector(config.urlSelector);

    if (holder) {
      return holder.getAttribute(config.urlAttribute);
    }

    return config.fallbackUrl || null;
  }

  async function bootModule(name) {
    const config = modules[name];

    if (!config || loading[name]) return;

    const available = config.selectors.filter(selector =>
      document.querySelector(selector)
    );

    if (!available.length) return;

    const pending = available.filter(selector => {
      const element = document.querySelector(selector);
      return !isMounted(selector, element);
    });

    if (!pending.length) return;

    const url = getModuleUrl(config);

    if (!url) {
      console.warn(`[charts] URL not found for module: ${name}`);
      return;
    }

    if (typeof ApexCharts === 'undefined') {
      console.error('[charts] ApexCharts is not loaded.');
      return;
    }

    loading[name] = true;

    try {
      const data = await fetchData(url);

      if (!data) return;

      loadTheme();

      config.render(data, {
        theme: C,
        font: FONT,
        fmt,
        base,
        grid,
        axisLabel,
        tip,
        noDataOpts,
        mount,
      });

    } catch (error) {
      console.error(`[charts] module initialization failed: ${name}`, error);

    } finally {
      loading[name] = false;
    }
  }

  function bootCharts() {
    pruneDetached();

    Object.keys(modules).forEach(name => {
      bootModule(name);
    });
  }

  // ============================================================
  // HTMX and DOM lifecycle
  // ============================================================

  let timer = null;

  function scheduleBoot() {
    clearTimeout(timer);
    timer = setTimeout(bootCharts, 30);
  }

  [
    'DOMContentLoaded',
    'pageshow',
    'popstate',

    // HTMX 2.x
    'htmx:afterSwap',
    'htmx:afterSettle',
    'htmx:afterOnLoad',
    'htmx:historyRestore',

    // HTMX 4.x
    'htmx:after:swap',
    'htmx:after:settle',
    'htmx:after:load',
    'htmx:history:restore',
    'htmx:after:init',
  ].forEach(name => {
    document.addEventListener(name, scheduleBoot);
    window.addEventListener(name, scheduleBoot);
  });

  // Observe inserted elements. This also handles containers inserted
  // by code that does not trigger an HTMX event.
  function watchDom() {
    if (!document.body || watchDom.active) return;

    watchDom.active = true;

    new MutationObserver(mutations => {
      for (const mutation of mutations) {
        if (mutation.addedNodes.length) {
          scheduleBoot();
          return;
        }
      }
    }).observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watchDom);
  } else {
    watchDom();
  }

  // ============================================================
  // Public API
  // ============================================================

  window.ChartCore = {
    register,
    boot: bootCharts,
    destroy,
    pruneDetached,

    get theme() {
      return C;
    },
  };

  window.bootCharts = bootCharts;

})();
