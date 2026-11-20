// static/js/navbar.js — load once in base.html
(function () {
  if (window.__navbarBound) return;
  window.__navbarBound = true;

  const closeAll = () => {
    document.querySelectorAll("[data-dropdown].open, .nav-dropdown.open").forEach(el => {
      el.classList.remove("open");
      if (el.matches("[data-dropdown]")) el.setAttribute("aria-expanded", "false");
    });
  };

  // Open / toggle / click-outside in one event handler
  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-dropdown]");
    if (!btn) return closeAll();

    const dd = document.getElementById("dropdown-" + btn.dataset.dropdown);
    const wasOpen = dd && dd.classList.contains("open");
    closeAll();
    if (dd && !wasOpen) {
      dd.classList.add("open");
      btn.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
    }
  });

  document.addEventListener("keydown", e => e.key === "Escape" && closeAll());
  document.addEventListener("htmx:afterRequest", closeAll);

  // ── Active state synchronization ──
  // Strip trailing slashes so "/sales/orders/" and "/sales/orders" compare equal.
  const norm = p => (p.length > 1 ? p.replace(/\/+$/, "") : p);

  // Segment-aware prefix match:
  //  - "/" (Home) only matches the exact root, never every page
  //  - "/sales/orders" matches "/sales/orders/12/" but NOT "/sales/orders-archive/"
  const matches = (path, url) => {
    path = norm(path);
    url = norm(url);
    if (url === "/") return path === "/";
    return path === url || path.startsWith(url + "/");
  };

  // The nav link the user last clicked. If the page we landed on still matches
  // it, that link wins - so a tie between two links sharing a path can't
  // highlight the wrong one.
  let clicked = null;

  function setSelected(best) {
    const links = [...document.querySelectorAll("#app-navbar [data-nav-url]")];
    links.forEach(l => {
      const on = l === best;
      l.classList.toggle("selected", on);
      if (on) l.setAttribute("aria-current", "page");
      else l.removeAttribute("aria-current");
    });
    document.querySelectorAll("#app-navbar .nav-dropdown-wrap").forEach(wrap => {
      const hasActive = !!wrap.querySelector(".nav-dd-link.selected");
      const btn = wrap.querySelector("[data-dropdown]");
      if (btn) btn.classList.toggle("selected", hasActive);
    });
  }

  // Highlight immediately on click, without waiting for the response to settle.
  document.addEventListener("click", e => {
    const link = e.target.closest("#app-navbar [data-nav-url]");
    if (!link) return;
    clicked = link;
    setSelected(link);
  });

  function syncNav() {
    const path = location.pathname;
    const links = [...document.querySelectorAll("#app-navbar [data-nav-url]")];

    const byLength = links
      .filter(l => matches(path, l.dataset.navUrl))
      .sort((a, b) => norm(b.dataset.navUrl).length - norm(a.dataset.navUrl).length)[0];

    const best = (clicked && document.contains(clicked) && matches(path, clicked.dataset.navUrl))
      ? clicked
      : byLength;

    // Pages with no matching link (e.g. a partner detail page) keep whatever is
    // already highlighted (from the server's is_active or the previous page)
    // instead of wiping the highlight.
    if (!best) return;

    setSelected(best);
  }

  ["DOMContentLoaded", "htmx:pushedIntoHistory", "htmx:historyRestore", "htmx:afterSettle"]
    .forEach(evt => document.addEventListener(evt, syncNav));
  window.addEventListener("popstate", () => { clicked = null; syncNav(); });
})();
