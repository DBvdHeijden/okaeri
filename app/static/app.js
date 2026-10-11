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

  // Hide / undo: the server records it; collapse the row in place instead of reloading.
  document.addEventListener("submit", (e) => {
    const row = e.target.closest(".row");
    if (!row) return;
    e.preventDefault();
    fetch(e.target.action, { method: "POST", redirect: "manual" });
    const hiding = e.target.matches("[data-hide]");
    row.querySelector(".row-body").hidden = hiding;
    row.querySelector(".row-hidden").hidden = !hiding;
    row.querySelector(hiding ? "[data-undo] button" : "[data-hide] button").focus();
  });

  // Feed paging: split rows into pages that fit the viewport, so the page never
  // scrolls. Arrow buttons (and ←/→ keys) cycle through them, wrapping around.
  // initPaging() runs again whenever the feed is swapped by a tab switch.
  let paging = null;
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const LEAVE_MS = 120;

  function initPaging() {
    const feed = document.querySelector(".feed");
    const pager = document.querySelector("[data-pager]");
    paging = null;
    if (!feed || !pager) return;
    const rows = [...feed.querySelectorAll(".row")];
    const pageNum = pager.querySelector("[data-page-num]");
    let pages = [], current = 0, moving = 0;

    const show = (i, animate) => {
      current = (i + pages.length) % pages.length;
      const on = new Set(pages[current]);
      for (const row of rows) {
        row.toggleAttribute("data-off", !on.has(row));
        // A plain re-fit (resize, fonts loaded) lets running entrances finish.
        if (animate || !on.has(row)) row.classList.remove("entering", "leaving");
      }
      if (animate && !REDUCED) {
        void feed.offsetWidth; // restart the animation on rows that were already visible
        pages[current].forEach((row, n) => {
          row.style.setProperty("--i", n);
          row.classList.add("entering");
        });
      }
      pageNum.textContent = current + 1;
      pageNum.setAttribute("aria-label", `Page ${current + 1} of ${pages.length}`);
      pager.hidden = pages.length < 2;
    };

    // Rows leave quickly, then the next page loads in top to bottom.
    const move = async (d) => {
      const token = ++moving;
      if (!REDUCED) {
        for (const row of pages[current]) {
          row.classList.remove("entering");
          row.classList.add("leaving");
        }
        await new Promise((r) => setTimeout(r, LEAVE_MS));
        if (token !== moving) return;
      }
      show(current + d, true);
    };

    const paginate = (animate = false) => {
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
      show(keep < 0 ? 0 : keep, animate);
      feed.dataset.paged = "";
    };

    paging = { pager, paginate, move };
    paginate(true);
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-prev]")) paging?.move(-1);
    else if (e.target.closest("[data-next]")) paging?.move(1);
  });
  document.addEventListener("keydown", (e) => {
    if (!paging || paging.pager.hidden || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (e.key === "ArrowLeft") paging.move(-1);
    else if (e.key === "ArrowRight") paging.move(1);
  });
  let resizeTimer;
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => paging?.paginate(), 100);
  });
  initPaging();
  // Web fonts change row heights; re-fit once they're in.
  document.fonts?.ready.then(() => paging?.paginate());

  // Tab switching without a page load: fetch the new list, fade the old one out,
  // swap it in and fade back in. Keeps the attractor running and avoids a flash.
  // Any failure (or a redirect, e.g. to onboarding) falls back to normal navigation.
  const region = document.querySelector("[data-feed-region]");
  const tabs = document.querySelector(".tabs");
  if (region && tabs) {
    const FADE_MS = REDUCED ? 0 : LEAVE_MS;
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    let latest = 0;

    const switchTo = async (url, push) => {
      const token = ++latest;
      region.classList.add("is-fading");
      try {
        const [html] = await Promise.all([
          fetch(url).then((r) => {
            if (!r.ok || r.redirected) throw new Error("fallback");
            return r.text();
          }),
          wait(FADE_MS),
        ]);
        if (token !== latest) return; // a newer click won
        const doc = new DOMParser().parseFromString(html, "text/html");
        const next = doc.querySelector("[data-feed-region]");
        if (!next) throw new Error("fallback");
        region.innerHTML = next.innerHTML;
        const currentHref = doc.querySelector('.tabs [aria-current="page"]')?.getAttribute("href");
        for (const a of tabs.querySelectorAll("a")) {
          if (a.getAttribute("href") === currentHref) a.setAttribute("aria-current", "page");
          else a.removeAttribute("aria-current");
        }
        if (push) history.pushState(null, "", url);
        initPaging();
        requestAnimationFrame(() => region.classList.remove("is-fading"));
      } catch (err) {
        location.href = url;
      }
    };

    tabs.addEventListener("click", (e) => {
      const a = e.target.closest("a");
      if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      if (a.getAttribute("aria-current") !== "page") switchTo(a.href, true);
    });
    addEventListener("popstate", () => switchTo(location.href, false));
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
