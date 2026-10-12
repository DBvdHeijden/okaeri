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

  // Onboarding sample step: a rating saves in the background, the tally counts up, and the story makes way
  // for a new one (none of the stories on screen; from another source if there is one).
  document.addEventListener("submit", async (e) => {
    if (!e.target.matches("[data-rate]")) return;
    e.preventDefault();
    const row = e.target.closest(".rate-row");
    const rating = e.submitter.value;
    for (const btn of e.target.querySelectorAll("button")) btn.disabled = true;  // one rating per story
    save(e.target, new URLSearchParams({ rating }), () => location.reload());

    const tally = document.querySelector("[data-tally]");
    const kind = rating === "up" ? "liked" : "disliked";
    tally.dataset[kind] = Number(tally.dataset[kind]) + 1;
    tally.textContent = `${tally.dataset.liked} liked · ${tally.dataset.disliked} not for me`;

    const rows = [...row.parentElement.children];
    const query = new URLSearchParams({
      shown: rows.map((r) => r.dataset.id).join(","),
      sources: rows.filter((r) => r !== row).map((r) => r.dataset.source).join(","),
    });
    const res = await fetch(`/onboarding/sample/next?${query}`).catch(() => null);
    if (res?.status !== 200) return row.remove();  // nothing left to show
    const template = document.createElement("template");
    template.innerHTML = (await res.text()).trim();
    const next = template.content.firstElementChild;
    if (!REDUCED) next.classList.add("entering");
    row.replaceWith(next);
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

    // The rows on screen leave quickly. Shared by the pager and by switching tabs or views.
    const leave = async () => {
      if (REDUCED) return;
      for (const row of pages[current]) {
        row.classList.remove("entering");
        row.classList.add("leaving");
      }
      await new Promise((r) => setTimeout(r, LEAVE_MS));
    };

    // Rows leave quickly, then the next page loads in top to bottom.
    const move = async (d) => {
      const token = ++moving;
      await leave();
      if (token !== moving) return;
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

    paging = { pager, paginate, move, remove, leave };
    paginate(true);
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-prev]")) paging?.move(-1);
    else if (e.target.closest("[data-next]")) paging?.move(1);
  });

  // Switching tabs or views (Latest / Recommended, Opened / Liked / Hidden) goes like turning a page: the rows
  // leave first, and the new page's rows load in as usual. Ctrl/Cmd-click etc. still open a new tab.
  document.addEventListener("click", async (e) => {
    const link = e.target.closest(".tabs a, .view-switch a");
    if (!link || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    await paging?.leave();
    location.href = link.href;
  });
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.matches(".view-switch") || "left" in form.dataset) return;  // the second time round, it goes
    e.preventDefault();
    await paging?.leave();
    form.dataset.left = "";
    form.requestSubmit(e.submitter);
  });
  // Coming back with the browser's back button can restore the page as it was left: rows faded out.
  addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    for (const row of document.querySelectorAll(".row.leaving")) row.classList.remove("leaving");
    for (const form of document.querySelectorAll(".view-switch[data-left]")) delete form.dataset.left;
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

  // Tabs (Settings and the onboarding tabs step). All and History can only be hidden; custom tabs can also be edited.
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

    // Ranking dials: a click glides the needle to the pointer, a drag follows it, and letting go settles
    // on the nearest 0.1. The browser jumps the value straight to the pointer, so while a glide runs we
    // put the value back and ease towards where it wanted to go.
    const motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tenth = (v) => Math.min(Math.max(Math.round(v * 10) / 10, 0), 1);
    const easeOut = (t) => 1 - (1 - t) ** 3;
    for (const dial of form.querySelectorAll(".dial")) {
      let shown = +dial.value, target = shown, tween = 0, gliding = false, pressed = false;
      const show = (v) => {
        shown = v;
        dial.value = v;
        dial.style.setProperty("--v", v);
        dial.nextElementSibling.value = tenth(v).toFixed(1);
        dial.parentElement.toggleAttribute("data-off", tenth(v) === 0);
      };
      // Eases from where the needle is to `target`, which may keep moving while it runs.
      const glide = (ms) => {
        const id = ++tween, from = shown, start = performance.now();
        gliding = true;
        const frame = (now) => {
          if (id !== tween) return;  // a newer glide took over
          const t = motion ? Math.min((now - start) / ms, 1) : 1;
          show(t < 1 ? from + (target - from) * easeOut(t) : target);
          if (t < 1) requestAnimationFrame(frame);
          else gliding = false;
        };
        requestAnimationFrame(frame);
      };
      const settle = () => {
        if (target === tenth(target) && !pressed) return;  // pointerup and change both land here
        pressed = false;
        target = tenth(target);
        glide(160);
      };
      dial.addEventListener("pointerdown", () => { pressed = true; });
      dial.addEventListener("input", () => {
        target = +dial.value;
        if (!pressed && !gliding) return show(target);
        dial.value = shown;
        if (!gliding) glide(140);
      });
      // pointerup too: a quick click can end before the needle moves, and then there's no change event.
      dial.addEventListener("pointerup", settle);
      dial.addEventListener("change", settle);
      dial.addEventListener("keydown", (e) => {
        const dir = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
        if (!dir) return;
        e.preventDefault();
        target = tenth(tenth(target) + dir / 10);
        glide(160);
      });
    }

    const notice = document.querySelector("[data-notice]");
    for (const btn of document.querySelectorAll("[data-not-yet]")) {
      btn.addEventListener("click", () => {
        notice.textContent = `${btn.textContent.trim()} isn't there yet, but it's coming.`;
      });
    }
  }
})();
