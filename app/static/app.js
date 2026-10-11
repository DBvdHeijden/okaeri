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
        document.cookie = `theme=${next}; path=/; max-age=31536000; samesite=lax`;
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

  // Background work (model download, indexing) in Settings: refresh the text until it's done.
  const progress = document.querySelector("[data-progress]");
  if (progress?.textContent) {
    const poll = setInterval(async () => {
      const text = await (await fetch("/progress")).text();
      progress.textContent = text;
      if (!text) clearInterval(poll);
    }, 5000);
  }

  // Post a form in the background; the page changes right away, and changes back if the save fails.
  // Success is a redirect (the server sends you back), which fetch reports as an opaque redirect.
  const save = (form, body, revert) =>
    fetch(form.action, { method: "POST", body, redirect: "manual" })
      .then((r) => { if (!r.ok && r.type !== "opaqueredirect") revert(); }, revert);

  // Hide: the story goes at once; History › Hidden brings it back. If the save fails, reload to show
  // the feed as it really is.
  document.addEventListener("submit", (e) => {
    if (!e.target.matches("[data-hide]")) return;
    e.preventDefault();
    const row = e.target.closest(".row");
    save(e.target, null, () => location.reload());
    if (paging) paging.remove(row);
    else row.remove();
  });

  // Onboarding ratings save in place; pressing the chosen one again takes the rating back.
  document.addEventListener("submit", (e) => {
    if (!e.target.matches("[data-rate]")) return;
    e.preventDefault();
    const buttons = [...e.target.querySelectorAll("button")];
    const before = buttons.map((btn) => btn.getAttribute("aria-pressed"));
    const rating = e.submitter.getAttribute("aria-pressed") === "true" ? "none" : e.submitter.value;
    for (const btn of buttons) btn.setAttribute("aria-pressed", btn.value === rating);
    save(e.target, new URLSearchParams({ rating }), () => buttons.forEach((btn, i) => btn.setAttribute("aria-pressed", before[i])));
  });

  // Feed paging: split rows into pages that fit the viewport, so the page never
  // scrolls. Arrow buttons (and ←/→ keys) cycle through them, wrapping around.
  let paging = null;
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const LEAVE_MS = 120;

  function initPaging() {
    const feed = document.querySelector(".feed");
    const pager = document.querySelector("[data-pager]");
    if (!feed || !pager) return;
    let rows = [...feed.querySelectorAll(".row")];
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
      const anchor = pages[current]?.find((row) => rows.includes(row));  // stay on this page, even if its first row left
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
      // Reserve the full height, so the pager stays put on short pages.
      feed.style.minHeight = `${available}px`;

      const keep = pages.findIndex((p) => p.includes(anchor));
      show(keep < 0 ? 0 : keep, animate);
      feed.dataset.paged = "";
    };

    const remove = (row) => {
      rows = rows.filter((r) => r !== row);
      row.remove();
      paginate();
    };

    paging = { pager, paginate, move, remove };
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

  // Tabs (Settings and onboarding step 4). All and History can only be hidden; custom tabs can also be edited.
  // On save the rows become the "tabs" JSON in settings.json.
  const tabsEditor = document.querySelector("[data-tabs]");
  if (tabsEditor) {
    const list = tabsEditor.querySelector("[data-tab-list]");
    const addBtn = tabsEditor.querySelector("[data-add-tab]");
    const rows = () => [...list.querySelectorAll("[data-tab-row]")];
    // A source the formats and topics no longer offer is hidden; it doesn't count (the editor itself may be closed).
    const picked = (row, kind) => [...row.querySelectorAll(`[data-pick="${kind}"]:checked`)].filter((c) => !c.closest("label").hidden);

    // Each row narrows the one above: only sources in the picked formats and topics are offered.
    const narrow = (row) => {
      const formats = picked(row, "format").map((c) => c.value);
      const topics = picked(row, "topic").map((c) => c.value);
      let left = 0;
      for (const box of row.querySelectorAll('[data-pick="source"]')) {
        const fits = (!formats.length || formats.includes(box.dataset.format)) &&
          (!topics.length || box.dataset.topics.split(" ").some((t) => topics.includes(t)));
        box.closest("label").hidden = !fits;
        left += fits;
      }
      const chosen = picked(row, "source").length;
      row.querySelector("[data-source-count]").textContent = !left ? "none" : chosen ? `${chosen} of ${left}` : `all ${left}`;
    };
    const update = () => {
      const custom = rows().filter((row) => !row.dataset.builtin);
      addBtn.hidden = custom.length >= Number(tabsEditor.dataset.max);
      const shown = rows().filter((row) => !row.classList.contains("is-hidden")).length;
      tabsEditor.querySelector("[data-tabs-count]").textContent = `${shown} shown`;
      for (const row of custom) {
        narrow(row);
        row.querySelector("[data-tab-title]").textContent = row.querySelector("[data-tab-name]").value.trim() || "New tab";
        const parts = [...picked(row, "format"), ...picked(row, "topic")].map((c) => c.value)
          .concat(picked(row, "source").map((c) => c.closest("label").textContent.trim()));
        row.querySelector("[data-tab-summary]").textContent = parts.join(" · ") || "Everything";
      }
    };
    const toggleEditor = (row) => {
      const editor = row.querySelector("[data-tab-editor]");
      editor.hidden = !editor.hidden;
      row.querySelector("[data-edit-tab]").textContent = editor.hidden ? "Edit" : "Done";
      if (!editor.hidden) row.querySelector("[data-tab-name]").focus();
    };

    list.addEventListener("click", (e) => {
      const row = e.target.closest("[data-tab-row]");
      const sortBtn = e.target.closest("[data-sort-tab]");
      if (sortBtn) {
        sortBtn.dataset.sort = sortBtn.dataset.sort === "recommended" ? "latest" : "recommended";
        sortBtn.textContent = `Sort: ${sortBtn.dataset.sort}`;
        return;
      }
      if (e.target.closest("[data-hide-tab]")) {
        const hidden = row.classList.toggle("is-hidden");
        e.target.textContent = hidden ? "Show" : "Hide";
      } else if (e.target.closest("[data-edit-tab]")) {
        toggleEditor(row);
      } else if (e.target.closest("[data-remove-tab]")) {
        row.remove();
      } else {
        return;
      }
      update();
    });
    list.addEventListener("input", update);
    addBtn.addEventListener("click", () => {
      // New custom tabs go before History, which stays last.
      const row = tabsEditor.querySelector("[data-tab-template]").content.firstElementChild.cloneNode(true);
      list.insertBefore(row, list.querySelector('[data-builtin="history"]'));
      toggleEditor(row);
      update();
    });
    update();

    tabsEditor.closest("form").addEventListener("submit", () => {
      tabsEditor.querySelector("[name=tabs]").value = JSON.stringify(rows().map((row) => ({
        builtin: row.dataset.builtin,
        name: row.querySelector("[data-tab-name]")?.value.trim(),
        tags: [...picked(row, "format"), ...picked(row, "topic")].map((c) => c.value),
        sources: picked(row, "source").map((c) => c.value),  // only those still offered
        hidden: row.classList.contains("is-hidden"),
        sort: row.querySelector("[data-sort-tab]")?.dataset.sort,
      })));
    });
  }

  // Onboarding and settings
  const form = document.querySelector("[data-onboarding]");
  if (form) {
    const count = form.querySelector("[data-selected-count]");
    const checks = form.querySelectorAll(".check");
    const selectAll = form.querySelector("[data-select-all]");
    const allChecked = () => [...checks].every((c) => c.checked);
    const updateCount = () => {
      const n = form.querySelectorAll(".check:checked").length;
      count.textContent = `${n} selected`;
      if (selectAll) selectAll.textContent = allChecked() ? "Deselect all" : "Select all";
      for (const group of form.querySelectorAll("[data-group]")) {
        const label = group.querySelector("[data-group-count]");
        if (label) label.textContent =
          `${group.querySelectorAll(".check:checked").length} of ${group.querySelectorAll(".check").length}`;
      }
    };
    form.addEventListener("change", updateCount);
    // One button: selects everything, or clears everything once all is selected.
    selectAll?.addEventListener("click", () => {
      const on = !allChecked();
      for (const c of checks) c.checked = on;
      updateCount();
    });
    if (selectAll) selectAll.hidden = false;
    updateCount();

    const search = document.querySelector("[data-source-search]");
    // Enter in the search box filters; it shouldn't submit the settings form around it.
    search?.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    const noResults = form.querySelector("[data-no-results]");
    search?.addEventListener("input", () => {
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
        // Collapsible sections open while searching, so matches are visible; close again when cleared.
        if (group.tagName === "DETAILS") group.open = q !== "" && visible > 0;
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
