 (function () {
    document.querySelectorAll('[data-account-menu]').forEach(function (wrap) {
      var btn  = wrap.querySelector('.app-account-btn');
      var menu = wrap.querySelector('.nav-dropdown');

      function set(open) {
        btn.classList.toggle('open', open);
        menu.classList.toggle('open', open);
        btn.setAttribute('aria-expanded', open);
      }

      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        set(!menu.classList.contains('open'));
      });
      document.addEventListener('click', function (e) {
        if (!wrap.contains(e.target)) set(false);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { set(false); btn.focus(); }
      });
    });
  })();
