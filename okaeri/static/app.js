(() => {
  const root = document.documentElement;

  // Theme: explicit choice overrides prefers-color-scheme.
  const currentTheme = () =>
    root.dataset.theme ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  for (const btn of document.querySelectorAll("[data-theme-toggle]")) {
    btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      const apply = () => {
        root.dataset.theme = next;
        try { localStorage.setItem("theme", next); } catch (e) {}
      };
      const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!document.startViewTransition || reduced) return apply();
      // Dark drops down over the page; light pulls it back up.
      root.dataset.themeTransition = next === "dark" ? "down" : "up";
      document.startViewTransition(apply).finished.finally(() => {
        delete root.dataset.themeTransition;
      });
    });
  }

  // Hide / undo. Client-side only for now; persist here later.
  function hideArticle(id) {
    const row = document.querySelector(`.row[data-id="${id}"]`);
    if (!row) return;
    row.querySelector(".row-body").hidden = true;
    const hidden = row.querySelector(".row-hidden");
    hidden.hidden = false;
    hidden.querySelector("[data-undo]").focus();
  }

  function unhideArticle(id) {
    const row = document.querySelector(`.row[data-id="${id}"]`);
    if (!row) return;
    row.querySelector(".row-hidden").hidden = true;
    row.querySelector(".row-body").hidden = false;
    row.querySelector("[data-hide]").focus();
  }

  document.addEventListener("click", (e) => {
    const row = e.target.closest(".row");
    if (!row) return;
    if (e.target.closest("[data-hide]")) hideArticle(row.dataset.id);
    else if (e.target.closest("[data-undo]")) unhideArticle(row.dataset.id);
  });

  // Feed paging: split rows into pages that fit the viewport, so the page never
  // scrolls. Arrow buttons (and ←/→ keys) cycle through them, wrapping around.
  const feed = document.querySelector(".feed");
  const pager = document.querySelector("[data-pager]");
  if (feed && pager) {
    const rows = [...feed.querySelectorAll(".row")];
    const pageNum = pager.querySelector("[data-page-num]");
    let pages = [], current = 0;

    const show = (i) => {
      current = (i + pages.length) % pages.length;
      const on = new Set(pages[current]);
      for (const row of rows) row.toggleAttribute("data-off", !on.has(row));
      pageNum.textContent = current + 1;
      pageNum.setAttribute("aria-label", `Page ${current + 1} of ${pages.length}`);
      pager.hidden = pages.length < 2;
    };

    const paginate = () => {
      const anchor = pages[current]?.[0];
      for (const row of rows) row.removeAttribute("data-off");
      pager.hidden = false;
      const padBottom = parseFloat(getComputedStyle(document.querySelector(".page")).paddingBottom);
      const pagerSpace = pager.offsetHeight + parseFloat(getComputedStyle(pager).marginTop);
      const available = innerHeight - feed.getBoundingClientRect().top - pagerSpace - padBottom - 1;

      pages = [];
      let page = [], used = 0;
      for (const row of rows) {
        const h = row.offsetHeight;
        if (page.length && used + h > available) { pages.push(page); page = []; used = 0; }
        page.push(row); used += h;
      }
      if (page.length) pages.push(page);

      const keep = pages.findIndex((p) => p.includes(anchor));
      show(keep < 0 ? 0 : keep);
      feed.dataset.paged = "";
    };

    pager.querySelector("[data-prev]").addEventListener("click", () => show(current - 1));
    pager.querySelector("[data-next]").addEventListener("click", () => show(current + 1));
    document.addEventListener("keydown", (e) => {
      if (pager.hidden || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.target.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "ArrowLeft") show(current - 1);
      else if (e.key === "ArrowRight") show(current + 1);
    });

    let resizeTimer;
    addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(paginate, 100);
    });
    paginate();
    // Web fonts change row heights; re-fit once they're in.
    document.fonts?.ready.then(paginate);
  }

  // Onboarding
  const form = document.querySelector("[data-onboarding]");
  if (form) {
    const count = form.querySelector("[data-selected-count]");
    const updateCount = () => {
      const n = form.querySelectorAll('input[name="sources"]:checked').length;
      count.textContent = `${n} selected`;
    };
    form.addEventListener("change", updateCount);
    updateCount();

    const search = document.querySelector("[data-source-search]");
    const noResults = form.querySelector("[data-no-results]");
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      let any = false;
      for (const group of form.querySelectorAll("[data-group]")) {
        let visible = 0;
        for (const source of group.querySelectorAll(".source")) {
          const match = source.dataset.name.includes(q);
          source.parentElement.hidden = !match;
          if (match) visible++;
        }
        group.hidden = visible === 0;
        any ||= visible > 0;
      }
      noResults.hidden = any;
    });

    const notice = document.querySelector("[data-notice]");
    for (const btn of document.querySelectorAll("[data-not-yet]")) {
      btn.addEventListener("click", () => {
        notice.textContent = `${btn.textContent.trim()}: not available yet.`;
      });
    }
  }
})();
